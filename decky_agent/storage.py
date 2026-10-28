import copy
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from .permissions import MODES


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def normalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("API 地址必须是 http:// 或 https:// 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API 地址不能包含账号、密码、查询参数或片段")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("API 端口无效") from error
    path = parsed.path.rstrip("/")
    for suffix in ("/chat/completions", "/audio/transcriptions", "/responses", "/models"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class SettingsStore:
    def __init__(self, path: Path, user_home: Path):
        self.path = path
        self.defaults = {
            "language": "zh-CN",
            "engine": "codex",
            "auth_mode": "api",
            "chatgpt_model": "",
            "base_url": "https://api.openai.com/v1",
            "model": "",
            "api_key": "",
            "workspace": str(user_home / "decky-agent-workspace"),
            "codex_path": "",
            "allow_shell": False,
            "network_access": False,
            "permission_mode": "ask",
            "instructions": "请用中文交流。先检查工作目录，再完成任务并验证结果。",
            "max_steps": 20,
            "speech_enabled": False,
            "speech_base_url": "",
            "speech_model": "gpt-transcribe",
            "speech_api_key": "",
        }
        self.value = copy.deepcopy(self.defaults)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.value.update({k: v for k, v in data.items() if k in self.defaults})

    def public(self) -> dict:
        result = copy.deepcopy(self.value)
        result["api_key_set"] = bool(result.pop("api_key"))
        result["speech_api_key_set"] = bool(result.pop("speech_api_key"))
        return result

    def redact(self, text: str) -> str:
        for secret in sorted({self.value["api_key"], self.value["speech_api_key"]}, key=len, reverse=True):
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text

    def redact_value(self, value):
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, list):
            return [self.redact_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self.redact_value(v) for k, v in value.items()}
        return value

    def update(self, changes: dict) -> dict:
        if not isinstance(changes, dict):
            raise ValueError("配置格式无效")
        value = copy.deepcopy(self.value)
        for key in self.defaults:
            if key not in changes:
                continue
            entry = changes[key]
            if isinstance(self.defaults[key], bool):
                if not isinstance(entry, bool):
                    raise ValueError(f"{key} 必须为布尔值")
            elif isinstance(self.defaults[key], int):
                if type(entry) is not int or not 1 <= entry <= 50:
                    raise ValueError("工具轮数应在 1–50 之间")
            elif not isinstance(entry, str) or len(entry) > 12000:
                raise ValueError(f"{key} 格式无效或过长")
            value[key] = entry.strip() if isinstance(entry, str) and key != "instructions" else entry
        # Blank password input means keep the stored key; clearing is explicit.
        for key in ("api_key", "speech_api_key"):
            if changes.get(key) == "":
                value[key] = self.value[key]
            if changes.get("clear_" + key) is True:
                value[key] = ""
            if "\n" in value[key] or "\r" in value[key]:
                raise ValueError("API Key 不能包含换行")
        if value["engine"] not in ("codex", "compatible"):
            raise ValueError("未知引擎")
        if value["auth_mode"] not in ("api", "chatgpt"):
            raise ValueError("未知登录方式")
        if value["permission_mode"] not in MODES:
            raise ValueError("未知权限模式")
        if value["language"] not in ("zh-CN", "en"):
            raise ValueError("未知界面语言")
        if value["engine"] != "codex" and value["auth_mode"] != "api":
            raise ValueError("ChatGPT 账号登录仅支持 Codex 引擎")
        value["base_url"] = normalize_url(value["base_url"])
        if value["speech_base_url"]:
            value["speech_base_url"] = normalize_url(value["speech_base_url"])
        account_speech = value["auth_mode"] == "chatgpt" and not value["speech_base_url"]
        if value["speech_enabled"] and not value["speech_model"] and not account_speech:
            raise ValueError("启用语音输入时需要填写转写模型")
        workspace = Path(value["workspace"]).expanduser()
        if not workspace.is_absolute():
            raise ValueError("工作目录必须为绝对路径")
        if workspace == Path("/"):
            raise ValueError("请选择具体的项目目录")
        value["workspace"] = str(workspace.resolve())
        if value["codex_path"] and not Path(value["codex_path"]).is_absolute():
            raise ValueError("Codex 路径必须为绝对路径")
        atomic_json(self.path, value)
        self.value = value
        return self.public()


class SessionStore:
    def __init__(self, root: Path):
        self.root = root
        self.sessions: dict[str, dict] = {}
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime)[-30:]:
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
                if session["id"] != path.stem or not isinstance(session["items"], list):
                    continue
                session["status"] = "idle"
                session["pending"] = []
                session.setdefault("auth_mode", "api")
                session.setdefault("auth_identity", None)
                session.setdefault("permission_mode", "ask")
                session["started_at"] = None
                session["progress"] = ""
                self.sessions[session["id"]] = session
            except (ValueError, KeyError, TypeError):
                continue

    def create(self, settings: dict) -> dict:
        if len(self.sessions) >= 30:
            raise ValueError("最多保留 30 个会话，请先删除旧会话")
        session_id = uuid.uuid4().hex
        session = {
            "id": session_id, "title": "New chat" if settings.get("language") == "en" else "新会话", "items": [], "pending": [],
            "status": "idle", "engine": settings["engine"],
            "auth_mode": settings.get("auth_mode", "api"), "auth_identity": None,
            "workspace": settings["workspace"],
            "model": settings.get("chatgpt_model", "") if settings.get("auth_mode") == "chatgpt" else settings["model"],
            "base_url": settings["base_url"], "thread_id": None,
            "messages": [], "revision": 0,
            "started_at": None, "progress": "",
            "permission_mode": settings.get("permission_mode", "ask"),
        }
        self.sessions[session_id] = session
        self.save(session)
        return session

    def get(self, session_id: str) -> dict:
        if session_id not in self.sessions:
            raise ValueError("会话不存在")
        return self.sessions[session_id]

    def save(self, session: dict) -> None:
        atomic_json(self.root / f"{session['id']}.json", session)

    def delete(self, session_id: str) -> None:
        self.get(session_id)
        (self.root / f"{session_id}.json").unlink(missing_ok=True)
        del self.sessions[session_id]

    def list(self) -> list[dict]:
        return [
            {k: s[k] for k in ("id", "title", "engine", "status", "model")}
            for s in reversed(list(self.sessions.values()))
        ]

    @staticmethod
    def public(session: dict) -> dict:
        return copy.deepcopy({k: v for k, v in session.items() if k not in ("messages", "auth_identity")})
