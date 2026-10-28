import asyncio
import copy
import json
import math
import re
import time
import uuid
from pathlib import Path

from .codex import CodexEngine, find_codex
from .compatible import CompatibleEngine
from .http import APIClient
from .storage import SessionStore, SettingsStore, atomic_json
from .speech import SpeechInput
from .auth import ChatGPTAuth


class AgentService:
    def __init__(self, settings_root: Path, data_root: Path, plugin_root: Path, user_home: Path):
        self.settings = SettingsStore(settings_root / "settings.json", user_home)
        self.sessions = SessionStore(data_root / "sessions")
        self.data_root = data_root
        self.plugin_root = plugin_root
        self.task: asyncio.Task | None = None
        self.starting = False
        self.active_id: str | None = None
        self.waiters: dict[str, asyncio.Future] = {}
        self.auth = ChatGPTAuth(data_root / "codex", lambda: find_codex(self.settings.value["codex_path"], self.plugin_root))
        self.speech = SpeechInput(data_root / "speech", self.auth.transcribe)

    def bootstrap(self) -> dict:
        return {
            "settings": self.settings.public(), "sessions": self.sessions.list(),
            "active_id": self.active_id,
            "codex_available": bool(find_codex(self.settings.value["codex_path"], self.plugin_root)),
            "speech": self.speech.capabilities(),
            "auth": self.auth.snapshot(),
        }

    def report_frontend(self, details: dict):
        if not isinstance(details, dict) or not re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}", str(details.get("version", ""))):
            raise ValueError("前端版本格式无效")
        report = {"version": details["version"], "seen_at": time.time()}
        for key in ("viewport_height", "global_viewport_height", "panel_top", "panel_height", "messages_height", "visible_messages_height", "composer_height"):
            value = details.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or not -10000 <= value <= 10000:
                raise ValueError("前端尺寸格式无效")
            report[key] = round(value, 2)
        if type(details.get("same_window")) is not bool:
            raise ValueError("前端窗口格式无效")
        report["same_window"] = details["same_window"]
        atomic_json(self.data_root / "diagnostics" / "frontend.json", report)

    def _busy(self):
        return self.starting or (self.task is not None and not self.task.done())

    def save_settings(self, changes: dict) -> dict:
        if self._busy():
            raise ValueError("请先停止当前任务再修改设置")
        if self.speech.busy:
            raise ValueError("请先结束录音或语音转写再修改设置")
        if self.auth.busy:
            raise ValueError("请先完成或取消 ChatGPT 登录再修改设置")
        return self.settings.update(changes)

    def create_session(self) -> dict:
        return SessionStore.public(self.sessions.create(self.settings.value))

    def delete_session(self, session_id: str):
        if self._busy() and session_id == self.active_id:
            raise ValueError("请先停止任务再删除会话")
        if self.speech.job and self.speech.job.session_id == session_id:
            raise ValueError("请先结束语音输入再删除会话")
        self.sessions.delete(session_id)

    def snapshot(self, session_id: str, revision: int = -1) -> dict:
        session = self.sessions.get(session_id)
        if session["revision"] == revision:
            return {"id": session_id, "revision": revision, "unchanged": True}
        return SessionStore.public(session)

    def _publish(self, session: dict, item_id: str, role: str, text: str,
                 append: bool = False, title: str = "", status: str | None = None):
        text = self.settings.redact(str(text))
        item = next((i for i in session["items"] if i["id"] == item_id), None)
        if item is None:
            item = {"id": item_id, "role": role, "text": "", "title": self.settings.redact(title), "status": status}
            session["items"].append(item)
        item["text"] = self.settings.redact((item["text"] if append else "") + text)[-64000:]
        if title:
            item["title"] = self.settings.redact(title)
        if status:
            item["status"] = status
        session["items"] = session["items"][-200:]
        session["revision"] += 1

    async def _ask(self, session: dict, kind: str, title: str, detail: str, questions=None):
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.waiters[request_id] = future
        request = {"id": request_id, "kind": kind, "title": title,
                   "detail": self.settings.redact(detail)[:160000], "questions": copy.deepcopy(questions or [])}
        request["title"] = self.settings.redact(title)
        for question in request["questions"]:
            for key in ("header", "question"):
                if key in question:
                    question[key] = self.settings.redact(question[key])
            question["options"] = self.settings.redact_value(question.get("options", []))
        session["pending"].append(request)
        session["status"] = "waiting"
        session["revision"] += 1
        try:
            # Unanswered approvals expire and fail closed.
            return await asyncio.wait_for(future, timeout=600)
        finally:
            self.waiters.pop(request_id, None)
            session["pending"] = [p for p in session["pending"] if p["id"] != request_id]
            session["status"] = "waiting" if session["pending"] else "running"
            session["revision"] += 1

    def respond(self, session_id: str, request_id: str, approved: bool, answers: dict | None = None):
        session = self.sessions.get(session_id)
        pending = next((p for p in session["pending"] if p["id"] == request_id), None)
        future = self.waiters.get(request_id)
        if not pending or not future or future.done():
            raise ValueError("请求已过期或已处理")
        if pending["kind"] == "input":
            if not isinstance(answers, dict) or any(
                not isinstance(v, str) or len(v) > 8000 for v in answers.values()
            ):
                raise ValueError("回答格式无效")
            if any(not answers.get(q["id"], "").strip() for q in pending["questions"]):
                raise ValueError("请回答所有问题，或停止任务")
            future.set_result(answers)
        else:
            if not isinstance(approved, bool):
                raise ValueError("审批结果无效")
            future.set_result(approved)

    async def start(self, session_id: str, prompt: str) -> dict:
        if self._busy():
            raise ValueError("已有任务正在运行，请先停止它")
        if self.auth.busy:
            raise ValueError("请先完成或取消 ChatGPT 登录")
        self.starting = True
        try:
            return await self._start(session_id, prompt)
        finally:
            self.starting = False

    async def _start(self, session_id: str, prompt: str) -> dict:
        if self.speech.busy:
            raise ValueError("请先结束语音输入，再发送任务")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
            raise ValueError("请输入 1–16000 字符的任务")
        settings = copy.deepcopy(self.settings.value)
        chatgpt = settings["engine"] == "codex" and settings["auth_mode"] == "chatgpt"
        if chatgpt:
            settings["model"] = settings["chatgpt_model"]
        if not settings["model"] and not chatgpt:
            raise ValueError("请先在连接设置中填写模型 ID")
        session = self.sessions.get(session_id)
        for key in ("engine", "auth_mode", "workspace", "base_url"):
            if session[key] != settings[key]:
                if session["items"]:
                    raise ValueError("引擎、模型、地址或工作目录已更改，请新建会话")
                session[key] = settings[key]
        if session["model"] != settings["model"]:
            if session["items"] and settings["engine"] != "codex":
                raise ValueError("模型已更改，请新建会话")
            # Codex supports overriding the model when resuming the same thread.
            session["model"] = settings["model"]
            session.pop("resolved_model", None)
        if chatgpt:
            account = await self.auth.refresh()
            if not account["signed_in"]:
                raise ValueError("请先在设置中登录 ChatGPT 账号")
            if session["items"] and session.get("auth_identity") != self.auth.identity:
                raise ValueError("登录账号已更改，请新建会话")
            session["auth_identity"] = self.auth.identity
        workspace = Path(settings["workspace"])
        workspace.mkdir(parents=True, exist_ok=True)
        if not workspace.is_dir():
            raise ValueError("工作目录无效")
        if settings["engine"] == "codex" and not find_codex(settings["codex_path"], self.plugin_root):
            raise ValueError("未找到 Codex；请安装含 Codex 的插件包，或设置二进制绝对路径")
        session["status"] = "running"
        session["permission_mode"] = settings["permission_mode"]
        session["started_at"] = time.time()
        session["progress"] = "正在准备任务"
        session["pending"] = []
        if session["title"] in ("新会话", "New chat"):
            session["title"] = self.settings.redact(prompt.strip()[:28])
        self._publish(session, uuid.uuid4().hex, "user", prompt.strip())
        try:
            self.sessions.save(session)
        except OSError as error:
            session["status"] = "failed"
            session["revision"] += 1
            raise ValueError(f"会话无法保存，任务未启动：{error}") from error
        self.active_id = session_id
        self.task = asyncio.create_task(self._run(session, settings, prompt.strip()))
        return self.snapshot(session_id)

    async def _run(self, session: dict, settings: dict, prompt: str):
        run_id = uuid.uuid4().hex

        def publish(item_id, role, text, **kwargs):
            self._publish(session, run_id + ":" + item_id, role, text, **kwargs)

        async def ask(kind, title, detail, questions=None):
            return await self._ask(session, kind, title, detail, questions)

        def progress(message):
            if session.get("progress") != message:
                session["progress"] = message
                session["revision"] += 1

        try:
            if settings["engine"] == "codex":
                engine = CodexEngine(settings, session, self.data_root / "codex",
                                     find_codex(settings["codex_path"], self.plugin_root), publish, ask, progress)
            else:
                engine = CompatibleEngine(settings, session, publish, ask)
            await engine.run(prompt)
            session["status"] = "completed"
        except asyncio.CancelledError:
            session["status"] = "cancelled"
            publish("cancelled", "system", "任务已停止。已完成的文件修改会保留。")
        except Exception as error:
            session["status"] = "failed"
            publish("error", "system", str(error) or type(error).__name__)
        finally:
            self._finish(session)

    def _finish(self, session: dict):
        session["pending"] = []
        session["revision"] += 1
        # Redact generated content only. IDs, tool names and provider routing must
        # remain stable even when a short API key coincides with their text.
        for message in session["messages"]:
            if message.get("content") is not None:
                message["content"] = self.settings.redact_value(message["content"])
            for call in message.get("tool_calls", []):
                arguments = call["function"].get("arguments", "")
                try:
                    call["function"]["arguments"] = json.dumps(
                        self.settings.redact_value(json.loads(arguments)), ensure_ascii=False,
                    )
                except (ValueError, TypeError):
                    call["function"]["arguments"] = self.settings.redact(arguments)
        try:
            self.sessions.save(session)
        except OSError as error:
            session["status"] = "failed"
            self._publish(session, uuid.uuid4().hex, "system", f"任务已结束，但会话未能保存：{error}")
        finally:
            self.active_id = None

    async def stop(self, session_id: str):
        if self._busy() and self.active_id == session_id:
            if not self.task.cancelling():
                self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                # A task cancelled before its first instruction has no finally block.
                session = self.sessions.get(session_id)
                session["status"] = "cancelled"
                self._finish(session)

    async def models(self) -> list[str]:
        settings = self.settings.value
        if settings["auth_mode"] == "chatgpt":
            return await self.auth.models()
        return await APIClient(settings["base_url"], settings["api_key"]).models()

    async def model_catalog(self) -> list[dict]:
        self._account_idle()
        if self.settings.value["auth_mode"] == "chatgpt":
            return await self.auth.model_catalog()
        return [{"model": model, "display_name": model, "is_default": False} for model in await self.models()]

    async def close(self):
        await self.speech.close()
        await self.auth.close()
        if self.active_id:
            await self.stop(self.active_id)

    async def start_recording(self, session_id: str) -> dict:
        self.sessions.get(session_id)
        if self._busy():
            raise ValueError("请先停止当前任务再录音")
        if self.auth.busy:
            raise ValueError("请先完成或取消 ChatGPT 登录")
        return await self.speech.start(session_id, self.settings.value)

    def _account_idle(self):
        if self._busy() or self.speech.busy:
            raise ValueError("请先停止任务或语音输入，再操作账号")

    async def account_status(self):
        self._account_idle()
        return await self.auth.refresh()

    async def login_chatgpt(self):
        self._account_idle()
        return await self.auth.start()

    async def cancel_login(self, login_id: str):
        return await self.auth.cancel(login_id)

    async def logout_chatgpt(self):
        self._account_idle()
        return await self.auth.logout()
