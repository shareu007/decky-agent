"""ChatGPT device-code sign-in. Codex alone owns credential storage/refresh."""
import asyncio
import base64
import copy
import hashlib
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .codex_rpc import CodexRPC
from .storage import atomic_json
from .http import ChatGPTSpeechClient, SpeechHTTPError, TLSVerificationError

LOGIN_SECONDS = 600


class AccountClient(CodexRPC):
    def __init__(self, binary: str, home: Path, catalog: Path | None = None):
        super().__init__(binary, home, home, catalog=catalog)
        self.completions = asyncio.Queue()

    def _notification(self, method: str, params: dict):
        if method == "account/login/completed":
            self.completions.put_nowait(params)

    def _disconnected(self, failure: str):
        self.completions.put_nowait(None)


class ChatGPTAuth:
    def __init__(self, home: Path, binary):
        self.home, self.binary = home, binary
        self.lock = asyncio.Lock()
        self.client: AccountClient | None = None
        self.watcher: asyncio.Task | None = None
        self.login: dict | None = None
        self.account: dict | None = None
        self.identity: str | None = None
        self.account_id: str | None = None
        self.phase = "unknown"
        self.error = ""
        self.closed = False
        self.owner_path = home / "decky-account-context.json"
        try:
            self.owner = json.loads(self.owner_path.read_text())["owner"]
        except (OSError, ValueError, KeyError, TypeError):
            self.owner = uuid.uuid4().hex

    @property
    def busy(self):
        return self.lock.locked() or self.login is not None

    def snapshot(self) -> dict:
        return {"phase": self.phase, "busy": self.busy, "signed_in": self.account is not None and self.phase == "signed_in",
                "account": copy.deepcopy(self.account), "login": copy.deepcopy(self.login), "error": self.error}

    async def _open(self, use_catalog=False):
        if self.closed:
            raise ValueError("插件正在关闭")
        binary = self.binary()
        if not binary:
            raise ValueError("未找到 Codex，请安装完整运行时或在高级设置中填写路径")
        root = Path(__file__).resolve().parents[1]
        bundled = root / "bin" / "codex"
        catalog = root / "resources" / "codex-models.json"
        local_catalog = use_catalog and bundled.is_file() and Path(binary).resolve() == bundled.resolve()
        self.client = AccountClient(binary, self.home, catalog=catalog if local_catalog else None)
        await self.client.connect()
        return self.client

    async def _close_client(self):
        client, self.client = self.client, None
        if client:
            await client.close()

    async def _read_account(self, client: AccountClient):
        result = await client.request("account/read", {"refreshToken": False})
        account = result.get("account")
        self.account = None
        self.identity = None
        self.account_id = None
        if account and account.get("type") == "chatgpt":
            # Only these display fields cross the Decky RPC boundary. Never read
            # auth.json or forward the raw account response to the frontend.
            self.account = {"email": str(account.get("email") or "")[:320],
                            "plan": str(account.get("planType") or "")[:80]}
            routing = result.get("workspaceRouting") or {}
            self.account_id = routing.get("chatgptAccountId")
            # Codex also enforces workspace binding when restoring its threads.
            atomic_json(self.owner_path, {"owner": self.owner})
            identity = [account.get("email"), routing.get("chatgptAccountId"), self.owner]
            self.identity = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        self.phase = "signed_in" if self.account else "signed_out"
        self.error = ""

    def _failure(self, message: str):
        self.account = None
        self.identity = None
        self.account_id = None
        self.phase = "error"
        self.error = message

    async def refresh(self) -> dict:
        async with self.lock:
            if self.login:
                return self.snapshot()
            self.phase, self.error = "checking", ""
            try:
                await self._read_account(await self._open())
            except Exception:
                self._failure("无法读取 ChatGPT 登录状态，请检查网络和 Codex 运行时后重试")
                raise ValueError(self.error) from None
            finally:
                await self._close_client()
            return self.snapshot()

    async def start(self) -> dict:
        async with self.lock:
            if self.login:
                return self.snapshot()
            self.phase, self.error = "starting", ""
            try:
                client = await self._open()
                result = await client.request("account/login/start", {"type": "chatgptDeviceCode"})
                url = str(result.get("verificationUrl", ""))
                parsed = urlsplit(url)
                code = str(result.get("userCode", ""))
                if (result.get("type") != "chatgptDeviceCode" or not result.get("loginId")
                        or parsed.scheme != "https" or parsed.netloc != "auth.openai.com"
                        or parsed.path != "/codex/device" or parsed.query or parsed.fragment
                        or not re.fullmatch(r"[A-Z0-9-]{6,24}", code)):
                    raise ValueError("Invalid official device-code response")
                self.login = {"id": result["loginId"], "url": url, "code": code}
                self.phase = "waiting"
                self.watcher = asyncio.create_task(self._wait(client, result["loginId"]))
                return self.snapshot()
            except BaseException as error:
                await self._close_client()
                self._failure("无法开始登录。请检查网络，并在 ChatGPT 安全设置中启用设备码登录后重试。")
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise ValueError(self.error) from None

    async def _wait(self, client: AccountClient, login_id: str):
        try:
            async def completion():
                while True:
                    event = await client.completions.get()
                    if event is None:
                        raise RuntimeError("Codex disconnected")
                    if event.get("loginId") == login_id:
                        return event
            event = await asyncio.wait_for(completion(), LOGIN_SECONDS)
            async with self.lock:
                if not self.login or self.login["id"] != login_id:
                    return
                try:
                    if not event.get("success"):
                        raise ValueError("Login failed")
                    # A new managed login is a new session authority, even when
                    # the account has no email. Old conversations require a new
                    # session instead of crossing accounts after re-login.
                    self.owner = uuid.uuid4().hex
                    await self._read_account(client)
                    if not self.account:
                        raise ValueError("No ChatGPT account")
                except Exception:
                    self._failure("登录未完成或已过期，请重新获取授权码")
                self.login = None
                self.watcher = None
                await self._close_client()
        except asyncio.CancelledError:
            pass
        except Exception:
            async with self.lock:
                if self.login and self.login["id"] == login_id:
                    self._failure("登录已过期或连接中断，请重试")
                    self.login = None
                    self.watcher = None
                    await self._close_client()

    async def _cancel_locked(self):
        watcher, self.watcher = self.watcher, None
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        if self.login and self.client:
            try:
                await self.client.request("account/login/cancel", {"loginId": self.login["id"]}, timeout=3)
            except Exception:
                pass
        self.login = None
        await self._close_client()

    async def cancel(self, login_id: str) -> dict:
        async with self.lock:
            if not self.login or self.login["id"] != login_id:
                return self.snapshot()
            await self._cancel_locked()
            self.phase, self.error = "unknown", ""
            return self.snapshot()

    async def logout(self) -> dict:
        async with self.lock:
            await self._cancel_locked()
            try:
                client = await self._open()
                await client.request("account/logout", {})
                self.account, self.identity = None, None
                self.account_id = None
                self.phase, self.error = "signed_out", ""
            except Exception:
                self._failure("退出登录失败，请重试")
                raise ValueError(self.error) from None
            finally:
                await self._close_client()
            return self.snapshot()

    async def models(self) -> list[str]:
        return [entry["model"] for entry in await self.model_catalog()]

    async def model_catalog(self) -> list[dict]:
        async with self.lock:
            if self.login:
                raise ValueError("请先完成登录")
            try:
                async with asyncio.timeout(12):
                    client = await self._open(use_catalog=True)
                    await self._read_account(client)
                    if not self.account:
                        raise ValueError("请先登录 ChatGPT")
                    models, cursors, cursor = {}, set(), None
                    for _ in range(10):
                        result = await client.request("model/list", {"cursor": cursor, "limit": 100, "includeHidden": False})
                        for entry in result.get("data", []):
                            model = entry.get("model")
                            if isinstance(model, str) and 0 < len(model) <= 256 and not entry.get("hidden"):
                                label = entry.get("displayName")
                                models.setdefault(model, {"model": model,
                                    "display_name": label[:256] if isinstance(label, str) and label else model,
                                    "is_default": entry.get("isDefault") is True})
                        cursor = result.get("nextCursor")
                        if not cursor:
                            return list(models.values())
                        if cursor in cursors:
                            break
                        cursors.add(cursor)
                    raise ValueError("模型列表分页无效")
            except Exception:
                raise ValueError("无法读取 ChatGPT 模型列表，请检查登录状态和网络；也可留空使用默认模型") from None
            finally:
                await self._close_client()

    async def transcribe(self, audio: bytes) -> str:
        async with self.lock:
            if self.login:
                raise ValueError("请先完成 ChatGPT 登录")
            try:
                client = await self._open()
                await self._read_account(client)
                if not self.account:
                    raise ValueError("请先登录 ChatGPT 后使用账号语音输入")
                for refresh in (False, True):
                    # This compatibility RPC is backend-only. Neither the token
                    # response nor JWT claims are exposed through plugin methods.
                    auth = await client.request("getAuthStatus", {"includeToken": True, "refreshToken": refresh})
                    token = auth.get("authToken")
                    if (auth.get("authMethod") != "chatgpt" or not isinstance(token, str)
                            or not 1 < len(token) < 32000 or "\r" in token or "\n" in token):
                        raise ValueError("ChatGPT 登录已失效，请重新登录")
                    account_id = self.account_id
                    if not account_id:
                        try:
                            payload = token.split(".")[1]
                            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                            account_id = claims.get("https://api.openai.com/auth", {}).get("chatgpt_account_id")
                        except (ValueError, IndexError, TypeError):
                            pass
                    if account_id is not None and (not isinstance(account_id, str) or not re.fullmatch(r"[A-Za-z0-9_:-]{1,200}", account_id)):
                        raise ValueError("ChatGPT 账号信息无效，请重新登录")
                    try:
                        return await ChatGPTSpeechClient(token, account_id, client.user_agent).transcribe(audio)
                    except SpeechHTTPError as error:
                        if error.status == 401 and not refresh:
                            continue
                        if error.status == 403:
                            raise ValueError("当前账号无法使用 ChatGPT 语音转写；可在高级设置中配置独立语音 API") from None
                        raise
            except (SpeechHTTPError, TLSVerificationError, ValueError):
                raise
            except Exception:
                raise ValueError("ChatGPT 语音转写连接失败或超时，请稍后重试") from None
            finally:
                await self._close_client()

    async def close(self):
        self.closed = True
        # Closing the transport releases an in-flight login/status request before
        # waiting for the state lock; plugin unload must not leave a login process.
        if self.client:
            await self.client.close()
        async with self.lock:
            await self._cancel_locked()
