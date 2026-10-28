"""Bounded microphone capture via PipeWire and an opt-in transcription API."""
import asyncio
import copy
import os
import shutil
import signal
import tempfile
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

from .http import APIClient
from .tools import kill_process

MAX_SECONDS = 60
MAX_BYTES = 4 * 1024 * 1024


def recorder_command() -> list[str] | None:
    if binary := shutil.which("pw-record"):
        return [binary]
    if binary := shutil.which("pw-cat"):
        return [binary, "--record"]
    return None


@dataclass
class Recording:
    id: str
    session_id: str
    settings: dict
    path: Path
    process: asyncio.subprocess.Process
    started: float
    state: str = "recording"
    expires: float = 0
    watcher: asyncio.Task | None = None
    upload: asyncio.Task | None = None


class SpeechInput:
    def __init__(self, root: Path, account_transcribe=None):
        self.root = root
        self.account_transcribe = account_transcribe
        self.job: Recording | None = None
        self.lock = asyncio.Lock()
        self.starting = False
        self.closed = False
        # Only our own temporary audio files are removed after a plugin restart.
        if root.exists():
            for path in root.glob("recording-*.wav"):
                path.unlink(missing_ok=True)

    @property
    def busy(self):
        return self.starting or self.job is not None

    def capabilities(self) -> dict:
        return {"available": recorder_command() is not None, "busy": self.busy, "max_seconds": MAX_SECONDS}

    def _get(self, recording_id: str) -> Recording:
        if not self.job or self.job.id != recording_id:
            raise ValueError("录音已结束或已过期，请重新录音")
        return self.job

    @staticmethod
    def _status(job: Recording) -> dict:
        return {"id": job.id, "state": job.state, "seconds": min(MAX_SECONDS, int(time.monotonic() - job.started))}

    async def start(self, session_id: str, settings: dict) -> dict:
        async with self.lock:
            if self.closed:
                raise ValueError("插件正在关闭")
            if self.busy:
                raise ValueError("已有录音或转写正在进行，请先结束它")
            if not settings["speech_enabled"]:
                raise ValueError("请先在设置 → 高级设置中启用语音输入")
            account = settings.get("auth_mode") == "chatgpt" and not settings["speech_base_url"]
            if not account and not settings["speech_model"].strip():
                raise ValueError("请先填写语音转写模型")
            command = recorder_command()
            if not command:
                raise ValueError("未找到 PipeWire 录音工具 pw-record；请在 Steam Deck 上检查音频环境")
            self.starting = True
            process = None
            path = None
            try:
                self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd, filename = tempfile.mkstemp(prefix="recording-", suffix=".wav", dir=self.root)
                os.close(fd)
                path = Path(filename)
                env = {k: v for k, v in os.environ.items() if k in (
                    "PATH", "HOME", "USER", "LANG", "LC_ALL", "XDG_RUNTIME_DIR",
                    "DBUS_SESSION_BUS_ADDRESS", "PIPEWIRE_REMOTE",
                )}
                env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
                spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                    *command, "--rate=16000", "--channels=1", "--format=s16", str(path),
                    env=env, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
                ))
                try:
                    process = await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    process = await spawn
                    raise
                job = Recording(uuid.uuid4().hex, session_id, copy.deepcopy(settings), path, process, time.monotonic())
                self.job = job
                job.watcher = asyncio.create_task(self._watch(job))
                return self._status(job)
            except BaseException:
                if process:
                    await kill_process(process)
                if path:
                    path.unlink(missing_ok=True)
                raise
            finally:
                self.starting = False

    async def _stop_capture(self, job: Recording):
        requested_stop = False
        if job.process.returncode is None:
            try:
                os.killpg(job.process.pid, signal.SIGINT)
                requested_stop = True
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(job.process.wait(), 3)
            except asyncio.TimeoutError:
                await kill_process(job.process)
                raise ValueError("录音工具没有正常停止，请重试")
        # Some PipeWire versions exit 1 after a graceful SIGINT and finalize the
        # WAV correctly. Accept this only for our stop signal and validated audio;
        # an unsolicited exit 1 still means capture failed.
        if requested_stop and job.process.returncode == 1:
            await asyncio.to_thread(self._audio, job.path)
        elif job.process.returncode not in (0, -signal.SIGINT):
            raise ValueError("录音失败，请检查默认麦克风、PipeWire 和音频权限")
        job.state = "ready"
        job.expires = time.monotonic() + 60

    async def _watch(self, job: Recording):
        try:
            while self.job is job:
                await asyncio.sleep(.25)
                async with self.lock:
                    if self.job is not job:
                        return
                    if job.state == "recording":
                        if job.process.returncode is not None:
                            job.state = "failed"
                            job.expires = time.monotonic() + 10
                            job.path.unlink(missing_ok=True)
                        elif time.monotonic() - job.started >= MAX_SECONDS or job.path.stat().st_size > MAX_BYTES:
                            try:
                                await self._stop_capture(job)
                            except ValueError:
                                job.state = "failed"
                                job.expires = time.monotonic() + 10
                                job.path.unlink(missing_ok=True)
                    elif job.state in ("ready", "failed") and time.monotonic() >= job.expires:
                        await self._discard(job)
                        return
        except asyncio.CancelledError:
            pass
        except Exception:
            async with self.lock:
                if self.job is job:
                    await self._discard(job)

    async def status(self, recording_id: str) -> dict:
        async with self.lock:
            return self._status(self._get(recording_id))

    @staticmethod
    def _audio(path: Path) -> bytes:
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("录音过大，请缩短录音")
        try:
            with wave.open(str(path), "rb") as audio:
                if audio.getnframes() < 1600:
                    raise ValueError("录音太短或没有声音数据，请重试")
                if audio.getnchannels() != 1 or audio.getframerate() != 16000 or audio.getsampwidth() != 2:
                    raise ValueError("录音格式无效，请检查 PipeWire 录音工具")
                if len(audio.readframes(audio.getnframes())) != audio.getnframes() * 2:
                    raise ValueError("录音文件不完整，请重新录音")
        except (wave.Error, EOFError) as error:
            raise ValueError("录音文件无效，请检查麦克风和音频服务") from error
        return path.read_bytes()

    async def finish(self, recording_id: str) -> str:
        job = None
        owned = False
        try:
            async with self.lock:
                job = self._get(recording_id)
                if job.state == "transcribing":
                    raise ValueError("正在转写，请稍候")
                owned = True
                if job.state == "failed":
                    raise ValueError("录音失败，请检查默认麦克风、PipeWire 和音频权限")
                if job.state == "recording":
                    await self._stop_capture(job)
                audio = await asyncio.to_thread(self._audio, job.path)
                # A separate URL never receives the chat API key implicitly.
                custom = bool(job.settings["speech_base_url"])
                job.state = "transcribing"
                if job.settings.get("auth_mode") == "chatgpt" and not custom:
                    if self.account_transcribe is None:
                        raise ValueError("ChatGPT 语音转写不可用，请重新加载插件")
                    upload = self.account_transcribe(audio)
                else:
                    client = APIClient(
                        job.settings["speech_base_url"] if custom else job.settings["base_url"],
                        job.settings["speech_api_key"] if custom else job.settings["api_key"],
                    )
                    upload = client.transcribe(audio, job.settings["speech_model"])
                job.upload = asyncio.create_task(upload)
            try:
                return await asyncio.shield(job.upload)
            except asyncio.CancelledError:
                raise ValueError("语音转写已取消") from None
        finally:
            if job and owned:
                async with self.lock:
                    if self.job is job:
                        await self._discard(job)

    async def _discard(self, job: Recording):
        if job.upload and not job.upload.done():
            job.upload.cancel()
            await asyncio.gather(job.upload, return_exceptions=True)
        if job.process.returncode is None:
            await kill_process(job.process)
        watcher = job.watcher
        if watcher and watcher is not asyncio.current_task():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        job.path.unlink(missing_ok=True)
        if self.job is job:
            self.job = None

    async def cancel(self, recording_id: str):
        async with self.lock:
            if self.job and self.job.id == recording_id:
                await self._discard(self.job)

    async def close(self):
        self.closed = True
        async with self.lock:
            if self.job:
                await self._discard(self.job)
