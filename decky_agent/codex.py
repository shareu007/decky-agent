"""JSON-lines app-server adapter. The official Codex binary owns the agent loop."""
import asyncio
import json
import os
import shutil
from pathlib import Path

from .codex_rpc import CodexRPC
from .permissions import codex_permissions

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def find_codex(configured: str, plugin_root: Path) -> str | None:
    candidates = [configured] if configured else [str(plugin_root / "bin" / "codex"), shutil.which("codex")]
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), None)


class CodexEngine(CodexRPC):
    def __init__(self, settings: dict, session: dict, home: Path, binary: str, publish, ask, progress=None):
        catalog = PLUGIN_ROOT / "resources" / "codex-models.json"
        bundled = PLUGIN_ROOT / "bin" / "codex"
        use_catalog = not settings.get("codex_path") and bundled.is_file() and Path(binary).resolve() == bundled.resolve()
        super().__init__(binary, home, Path(settings["workspace"]),
                         None if settings.get("auth_mode", "api") == "chatgpt" else settings,
                         catalog=catalog if use_catalog else None, experimental=True)
        self.settings = settings
        self.session = session
        self.publish = publish
        self.ask = ask
        self.progress = progress or (lambda _message: None)
        self.finished = asyncio.get_running_loop().create_future()
        self.items: dict[str, dict] = {}
        self.turn_id = None

    def _disconnected(self, failure: str):
        if not self.finished.done():
            self.finished.set_result({"status": "failed", "error": {"message": failure}})

    def _notification(self, method: str, params: dict):
        item = params.get("item", {})
        item_id = str(item.get("id", params.get("itemId", "")))
        if method == "model/rerouted" and params.get("threadId") == self.session.get("thread_id"):
            self._resolved_model(params.get("toModel"))
        elif method == "turn/started":
            self.turn_id = params.get("turn", {}).get("id")
        elif method == "serverRequest/resolved":
            handler = self.handlers.get(params.get("requestId"))
            if handler and handler is not asyncio.current_task():
                handler.cancel()
        elif method == "item/agentMessage/delta":
            self.progress("正在生成回复")
            self.publish(item_id, "assistant", params.get("delta", ""), append=True)
        elif method in ("item/started", "item/completed"):
            self.items[item_id] = item
            kind = item.get("type")
            if kind == "agentMessage":
                # Started agent messages often have no text yet.
                if method == "item/completed" or item.get("text"):
                    self.publish(item_id, "assistant", item.get("text", ""))
            elif kind == "commandExecution":
                text = f"$ {item.get('command', '')}\n{item.get('aggregatedOutput') or ''}"
                self.publish(item_id, "tool", text, title="命令", status=item.get("status"))
            elif kind == "fileChange":
                text = "\n\n".join(f"{c.get('path', '')}\n{c.get('diff', '')}" for c in item.get("changes", []))
                self.publish(item_id, "tool", text, title="文件修改", status=item.get("status"))
        elif method == "item/commandExecution/outputDelta":
            self.publish(item_id, "tool", params.get("delta", ""), append=True)
        elif method == "turn/plan/updated":
            text = "\n".join(f"[{p.get('status', '')}] {p.get('step', '')}" for p in params.get("plan", []))
            self.publish("plan", "tool", text, title="任务计划")
        elif method == "error":
            self.publish("codex-error", "system", params.get("error", {}).get("message", "Codex 请求失败"))
        elif method in ("item/autoApprovalReview/started", "item/autoApprovalReview/completed"):
            review = params.get("review", {})
            status = review.get("status", "inProgress")
            label = {"inProgress": "自动审核中", "approved": "自动审核已批准", "denied": "自动审核已拒绝",
                     "timedOut": "自动审核超时", "aborted": "自动审核已停止"}.get(status, "自动审核")
            self.progress(label)
            action = params.get("action", {})
            detail = action.get("command") or action.get("target") or action.get("type", "")
            text = "\n".join(str(x) for x in (detail, review.get("rationale")) if x)
            self.publish("review-" + str(params.get("reviewId", "")), "tool", text, title=label,
                         status="inProgress" if status == "inProgress" else "failed" if status in ("denied", "timedOut") else "completed")
        elif method == "turn/completed" and not self.finished.done():
            self.finished.set_result(params.get("turn", {}))

    def _resolved_model(self, model):
        if isinstance(model, str) and 0 < len(model) <= 256 and self.session.get("resolved_model") != model:
            self.session["resolved_model"] = model
            self.session["revision"] = self.session.get("revision", 0) + 1

    async def _server_request(self, message: dict):
        method, params = message["method"], message.get("params", {})
        response = {"id": message["id"]}
        try:
            if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
                item = self.items.get(str(params.get("itemId")), {})
                command = params.get("command") or item.get("command")
                detail = "\n".join(str(x) for x in (
                    f"$ {command}" if command else None,
                    f"目录：{params['cwd']}" if params.get("cwd") else None,
                    params.get("reason"),
                    json.dumps({"request": params, "changes": item.get("changes", [])}, ensure_ascii=False, indent=2) if not command else None,
                ) if x)
                accepted = await self.ask("approval", "Codex 请求操作授权", detail)
                decisions = params.get("availableDecisions")
                if decisions and "accept" not in decisions and accepted:
                    accepted = False
                response["result"] = {"decision": "accept" if accepted else "decline"}
            elif method == "item/tool/requestUserInput":
                answers = await self.ask("input", "Codex 需要补充信息", "", params.get("questions", []))
                response["result"] = {"answers": {
                    q["id"]: {"answers": [answers.get(q["id"], "")]}
                    for q in params.get("questions", [])
                }}
            elif method == "item/permissions/requestApproval":
                requested = params.get("permissions") or {}
                detail = "\n".join(str(x) for x in (params.get("reason"), json.dumps(requested, ensure_ascii=False, indent=2)) if x)
                accepted = await self.ask("approval", "Codex 请求额外文件或网络权限", detail)
                response["result"] = {"permissions": requested if accepted else {}, "scope": "turn"}
            elif method == "mcpServer/elicitation/request":
                response["result"] = {"action": "decline", "content": None}
            else:
                response["error"] = {"code": -32601, "message": f"Unsupported client request: {method}"}
            await self._send(response)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.publish("approval-error", "system", f"授权处理失败：{error}")
            if not self.finished.done():
                self.finished.set_result({"status": "failed", "error": {"message": "授权处理失败"}})

    async def run(self, prompt: str):
        try:
            self.progress("正在连接 Codex")
            await self.connect()
            self.progress("正在准备会话")
            thread_policy, turn_policy = codex_permissions(self.settings)
            params = {
                "model": self.settings["model"] or None,
                "modelProvider": "openai" if self.settings.get("auth_mode", "api") == "chatgpt" else "decky",
                "cwd": self.settings["workspace"], "developerInstructions": self.settings["instructions"],
                **thread_policy,
            }
            if self.session.get("thread_id"):
                params["threadId"] = self.session["thread_id"]
                result = await self.request("thread/resume", params)
            else:
                result = await self.request("thread/start", params)
            if (self.settings.get("permission_mode") == "auto"
                    and result.get("approvalsReviewer") != "auto_review"):
                raise RuntimeError("当前 Codex 未启用自动审核，请检查 Codex 版本或组织策略，或切换为请求批准")
            self.session["thread_id"] = result["thread"]["id"]
            self._resolved_model(result.get("model"))
            self.progress("等待模型回复")
            started = await self.request("turn/start", {
                "threadId": self.session["thread_id"],
                "input": [{"type": "text", "text": prompt}],
                **turn_policy,
            })
            self.turn_id = started["turn"]["id"]
            result = await asyncio.shield(self.finished)
            if result.get("status") == "failed":
                raise RuntimeError(result.get("error", {}).get("message", "Codex 任务失败"))
            if result.get("status") == "interrupted":
                raise asyncio.CancelledError()
        except asyncio.CancelledError:
            if self.turn_id and not self.finished.done():
                # Ask Codex to clean up its own tool processes before terminating it.
                try:
                    await asyncio.wait_for(self.request("turn/interrupt", {
                        "threadId": self.session["thread_id"], "turnId": self.turn_id,
                    }), timeout=2)
                    await asyncio.wait_for(asyncio.shield(self.finished), timeout=2)
                except Exception:
                    pass
            raise
        finally:
            await self.close()

