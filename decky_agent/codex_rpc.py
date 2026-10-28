"""Private stdio transport shared by Codex turns and managed account login."""
import asyncio
import json
import os
from pathlib import Path

from .tools import kill_process


class CodexRPC:
    def __init__(self, binary: str, home: Path, cwd: Path, settings: dict | None = None, catalog: Path | None = None, experimental: bool = False):
        self.binary, self.home, self.cwd = binary, home, cwd
        self.provider_settings = settings
        self.catalog = catalog
        self.experimental = experimental
        self.user_agent = "codex_cli_rs/0.164.0"
        self.process = None
        self.reader = None
        self.stderr_reader = None
        self.pending: dict[int, asyncio.Future] = {}
        self.handlers: dict[object, asyncio.Task] = {}
        self.next_id = 0
        self.stderr_tail = ""
        self.closed = False

    async def connect(self):
        if self.closed:
            raise RuntimeError("Codex 连接已关闭")
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = {k: v for k, v in os.environ.items() if k in (
            "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "CODEX_CA_CERTIFICATE",
            "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
        )}
        env["CODEX_HOME"] = str(self.home)
        overrides = {
            "model_provider": "openai",
            "cli_auth_credentials_store": "file",
            "analytics.enabled": False,
            "shell_environment_policy.exclude": ["DECKY_AGENT_API_KEY", "OPENAI_API_KEY"],
        }
        if self.provider_settings is not None:
            settings = self.provider_settings
            overrides.update({
                "model_provider": "decky",
                "model_providers.decky.name": "Decky custom provider",
                "model_providers.decky.base_url": settings["base_url"],
                "model_providers.decky.wire_api": "responses",
                "model_providers.decky.requires_openai_auth": False,
                "model_providers.decky.supports_websockets": False,
            })
            if settings["api_key"]:
                env["DECKY_AGENT_API_KEY"] = settings["api_key"]
                overrides["model_providers.decky.env_key"] = "DECKY_AGENT_API_KEY"
        elif self.catalog and self.catalog.is_file():
            # Use the exact metadata bundled with this Codex release. Model
            # discovery failures otherwise add repeated 5-second timeouts to turns.
            overrides["model_catalog_json"] = str(self.catalog)
        argv = [self.binary, "app-server", "--listen", "stdio://"]
        for key, value in overrides.items():
            argv += ["-c", f"{key}={json.dumps(value, ensure_ascii=False)}"]
        try:
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                *argv, cwd=self.cwd, env=env, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=8 * 1024 * 1024, start_new_session=True,
            ))
            try:
                self.process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                self.process = await spawn
                raise
            if self.closed:
                raise RuntimeError("Codex 连接已关闭")
            self.reader = asyncio.create_task(self._read())
            self.stderr_reader = asyncio.create_task(self._read_stderr())
            params = {"clientInfo": {
                "name": "decky_agent", "title": "Decky Agent", "version": "0.1.9",
            }}
            if self.experimental:
                params["capabilities"] = {"experimentalApi": True}
            initialized = await self.request("initialize", params)
            agent = initialized.get("userAgent")
            if isinstance(agent, str) and 0 < len(agent) < 1024 and not any(c in agent for c in "\r\n"):
                self.user_agent = agent
            await self._send({"method": "initialized", "params": {}})
        except BaseException:
            await self.close()
            raise

    async def _send(self, message: dict):
        if not self.process or self.process.returncode is not None:
            raise RuntimeError("Codex 进程已退出")
        self.process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method: str, params: dict, timeout: float = 45) -> dict:
        self.next_id += 1
        request_id = self.next_id
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self._send({"id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(request_id, None)

    async def _read_stderr(self):
        while chunk := await self.process.stderr.read(4096):
            self.stderr_tail = (self.stderr_tail + chunk.decode("utf-8", errors="replace"))[-4000:]

    async def _read(self):
        failure = "Codex 进程意外退出"
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "method" in message:
                    if "id" in message:
                        task = asyncio.create_task(self._server_request(message))
                        request_id = message["id"]
                        self.handlers[request_id] = task
                        task.add_done_callback(lambda _task, key=request_id: self.handlers.pop(key, None))
                    else:
                        self._notification(message["method"], message.get("params", {}))
                elif message.get("id") in self.pending:
                    future = self.pending[message["id"]]
                    if not future.done():
                        if "error" in message:
                            future.set_exception(RuntimeError(message["error"].get("message", "Codex RPC 失败")))
                        else:
                            future.set_result(message.get("result", {}))
        except asyncio.CancelledError:
            raise
        except Exception:
            failure = "Codex 协议错误"
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError(failure))
            self._disconnected(failure)

    def _notification(self, method: str, params: dict):
        pass

    def _disconnected(self, failure: str):
        pass

    async def _server_request(self, message: dict):
        await self._send({"id": message["id"], "error": {"code": -32601, "message": "Unsupported client request"}})

    async def close(self):
        self.closed = True
        if self.process:
            await kill_process(self.process)
        tasks = [t for t in (self.reader, self.stderr_reader, *self.handlers.values()) if t and t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
