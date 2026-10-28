import asyncio
import difflib
import json
from itertools import islice
import os
import signal
import stat
from pathlib import Path

MAX_TEXT = 48_000


def tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required, "additionalProperties": False},
    }}


def definitions(allow_shell: bool) -> list[dict]:
    string = {"type": "string"}
    result = [
        tool("list_files", "List files inside the workspace; path defaults to .", {"path": string}, []),
        tool("read_file", "Read a UTF-8 file inside the workspace, up to 48 KB", {"path": string}, ["path"]),
        tool("write_file", "Create or replace a UTF-8 file; user must approve the diff",
             {"path": string, "content": string}, ["path", "content"]),
    ]
    if allow_shell:
        result.append(tool("run_command", "Run a bash command after explicit user approval; no OS sandbox",
                           {"command": string}, ["command"]))
    return result


async def kill_process(process: asyncio.subprocess.Process) -> None:
    # Always kill the group, even if the parent already exited leaving children.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


class WorkspaceTools:
    def __init__(self, root: Path, allow_shell: bool, ask, publish):
        self.root = root.resolve()
        self.allow_shell = allow_shell
        self.ask = ask
        self.publish = publish

    def resolve(self, value: str) -> Path:
        if not isinstance(value, str) or not value or "\0" in value:
            raise ValueError("文件路径无效")
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("路径超出工作目录（包括符号链接）")
        return path

    @staticmethod
    def _read_regular(path: Path, *, optional=False, require_full=False) -> bytes | None:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        except FileNotFoundError:
            if optional:
                return None
            raise
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("只支持普通文件，不能读取管道、设备或目录")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(MAX_TEXT + 1)
        finally:
            os.close(fd)
        if require_full and len(raw) > MAX_TEXT:
            raise ValueError("原文件超过 48 KB，请使用 Codex 引擎修改")
        return raw

    def _write_regular(self, original: str, path: Path, before: bytes | None, content: bytes):
        if self.resolve(original) != path:
            raise ValueError("文件链接在审批期间发生变化")
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW
        if before is None:
            flags |= os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o666)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("只支持写入普通文件")
            with os.fdopen(fd, "r+b", closefd=False) as handle:
                current = handle.read(MAX_TEXT + 1)
                if current != (before or b""):
                    raise ValueError("文件在审批期间被修改，请重新读取后再试")
                handle.seek(0)
                handle.write(content)
                handle.truncate()
        finally:
            os.close(fd)

    @staticmethod
    def _list_files(path: Path) -> str:
        with os.scandir(path) as entries:
            entries = list(islice(entries, 501))
        result = "\n".join(
            entry.name + ("/" if entry.is_dir(follow_symlinks=False) else "")
            for entry in sorted(entries[:500], key=lambda entry: entry.name)
        )[:MAX_TEXT]
        return result + ("\n[目录超过 500 项，已截断]" if len(entries) > 500 else "")

    async def execute(self, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments)
            if not isinstance(args, dict):
                raise ValueError("工具参数必须是对象")
            allowed = {"list_files": {"path"}, "read_file": {"path"},
                       "write_file": {"path", "content"}, "run_command": {"command"}}
            if name not in allowed or set(args) - allowed[name]:
                raise ValueError("未知工具或参数")
            if name == "run_command":
                return await self._command(args["command"])
            path = self.resolve(args.get("path", "."))
            if name == "list_files":
                return await asyncio.to_thread(self._list_files, path)
            if name == "read_file":
                raw = await asyncio.to_thread(self._read_regular, path)
                return raw[:MAX_TEXT].decode("utf-8", errors="replace") + (
                    "\n[文件过长，已截断]" if len(raw) > MAX_TEXT else ""
                )
            if name == "write_file":
                content = args["content"]
                if not isinstance(content, str) or len(content.encode()) > MAX_TEXT:
                    raise ValueError("文件内容超过 48 KB 或格式无效")
                before_raw = await asyncio.to_thread(self._read_regular, path, optional=True, require_full=True)
                before = before_raw.decode("utf-8") if before_raw is not None else ""
                diff = "".join(difflib.unified_diff(
                    before.splitlines(keepends=True), content.splitlines(keepends=True),
                    fromfile=str(path.relative_to(self.root)), tofile=str(path.relative_to(self.root)),
                ))
                accepted = await self.ask("approval", "修改文件", f"{path}\n\n{diff or '(内容相同)'}")
                if not accepted:
                    return "用户拒绝了文件修改。"
                write = asyncio.create_task(asyncio.to_thread(
                    self._write_regular, args["path"], path, before_raw, content.encode("utf-8"),
                ))
                try:
                    await asyncio.shield(write)
                except asyncio.CancelledError:
                    # A running thread cannot be cancelled. Finish this approved
                    # write before Stop returns and a later task can touch files.
                    await asyncio.gather(write, return_exceptions=True)
                    raise
                return f"已保存 {path.relative_to(self.root)}"
            raise ValueError("未知工具")
        except (ValueError, OSError, KeyError, TypeError) as error:
            return f"工具错误：{error}"

    async def _command(self, command: str) -> str:
        if not self.allow_shell:
            raise ValueError("命令执行未启用")
        if not isinstance(command, str) or not command.strip() or len(command) > 8000:
            raise ValueError("命令无效或过长")
        if not await self.ask("approval", "执行命令（无系统沙箱）", f"目录：{self.root}\n\n{command}"):
            return "用户拒绝了命令执行。"
        # API credentials are deliberately excluded from command environments.
        env = {k: v for k, v in os.environ.items()
               if k in ("HOME", "USER", "LANG", "LC_ALL", "PATH", "TERM", "TMPDIR")}
        process = await asyncio.create_subprocess_exec(
            "/bin/bash", "--noprofile", "--norc", "-c", command,
            cwd=self.root, env=env, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, start_new_session=True,
        )
        output = bytearray()

        async def consume():
            while True:
                chunk = await process.stdout.read(4096)
                if not chunk:
                    break
                room = MAX_TEXT - len(output)
                if room > 0:
                    output.extend(chunk[:room])
            await process.wait()

        try:
            await asyncio.wait_for(consume(), timeout=60)
        except asyncio.TimeoutError:
            return output.decode("utf-8", errors="replace") + "\n[命令超时，已终止进程组]"
        finally:
            await kill_process(process)
        return f"exit_code={process.returncode}\n" + output.decode("utf-8", errors="replace")
