import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
import json
from unittest.mock import AsyncMock

from decky_agent.codex import CodexEngine, find_codex
from decky_agent.service import AgentService


class CodexTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "fake-codex"
        fixture = Path(__file__).parent / "fixtures" / "fake_codex.py"
        self.binary.write_text(f"#!{sys.executable}\n" + fixture.read_text())
        self.binary.chmod(0o755)
        self.service = AgentService(self.root / "settings", self.root / "data", self.root, self.root)
        self.service.save_settings({"model": "custom", "codex_path": str(self.binary)})
        self.session = self.service.sessions.create(self.service.settings.value)

    async def wait_for(self, predicate):
        async def poll():
            while not predicate():
                await asyncio.sleep(.01)
        await asyncio.wait_for(poll(), 5)

    async def test_official_protocol_streaming_approval_and_resume(self):
        await self.service.start(self.session["id"], "first task")
        await self.wait_for(lambda: self.session["status"] == "waiting")
        pending = self.session["pending"][0]
        self.assertIn("pwd", pending["detail"])
        self.service.respond(self.session["id"], pending["id"], True)
        await asyncio.wait_for(self.service.task, 5)
        self.assertEqual(self.session["status"], "completed")
        self.assertEqual(self.session["thread_id"], "thread-1")
        self.assertEqual([i["text"] for i in self.session["items"] if i["role"] == "assistant"], ["hello deck"])
        # A fresh app-server resumes the same persisted thread on the next turn.
        await self.service.start(self.session["id"], "second task")
        await self.wait_for(lambda: self.session["status"] == "waiting")
        self.service.respond(self.session["id"], self.session["pending"][0]["id"], False)
        await asyncio.wait_for(self.service.task, 5)
        self.assertEqual(self.session["items"][-1]["text"], "declined")

    async def test_stop_while_waiting_cleans_up_requests_and_process(self):
        await self.service.start(self.session["id"], "task")
        await self.wait_for(lambda: self.session["status"] == "waiting")
        await asyncio.wait_for(self.service.stop(self.session["id"]), 5)
        self.assertEqual(self.session["status"], "cancelled")
        self.assertEqual(self.session["pending"], [])
        self.assertEqual(self.service.waiters, {})
        self.assertTrue((Path(self.session["workspace"]) / "interrupt.marker").exists())

    async def test_model_reroute_updates_the_current_thread_only(self):
        engine = CodexEngine(self.service.settings.value, self.session, self.root / "codex", str(self.binary), lambda *_a, **_k: None, AsyncMock())
        self.session["thread_id"] = "thread-1"
        engine._notification("model/rerouted", {"threadId": "other-thread", "toModel": "wrong-model"})
        self.assertNotIn("resolved_model", self.session)
        engine._notification("model/rerouted", {"threadId": "thread-1", "toModel": "actual-routed-model"})
        self.assertEqual(self.session["resolved_model"], "actual-routed-model")
        self.assertEqual(self.session["revision"], 1)

    async def test_selected_permission_mode_reaches_new_and_resumed_threads_and_turns(self):
        for mode, reviewer, sandbox, policy in [
            ("ask", "user", "workspace-write", "on-request"),
            ("auto", "auto_review", "workspace-write", "on-request"),
            ("full", "user", "danger-full-access", "never"),
            ("ask", "user", "workspace-write", "on-request"),
        ]:
            with self.subTest(mode=mode):
                resumed = bool(self.session.get("thread_id"))
                self.service.save_settings({"permission_mode": mode})
                await self.service.start(self.session["id"], "permission routing test")
                await self.wait_for(lambda: self.session["status"] == "waiting")
                self.service.respond(self.session["id"], self.session["pending"][0]["id"], True)
                await asyncio.wait_for(self.service.task, 5)
                root = Path(self.session["workspace"])
                thread = json.loads((root / ("thread-resume.json" if resumed else "thread-start.json")).read_text())
                turn = json.loads((root / "turn-start.json").read_text())
                for request in [thread, turn]:
                    self.assertEqual(request["approvalPolicy"], policy)
                    self.assertEqual(request["approvalsReviewer"], reviewer)
                self.assertEqual(thread["sandbox"], sandbox)
                self.assertEqual(turn["sandboxPolicy"]["type"], "dangerFullAccess" if mode == "full" else "workspaceWrite")
                self.assertEqual(self.session["permission_mode"], mode)

    async def test_extra_permissions_require_a_decision_and_grant_only_the_requested_turn_scope(self):
        requested = {"fileSystem": {"write": [str(self.root / "extra")]}, "network": {"enabled": True}}
        for accepted in [True, False]:
            ask = AsyncMock(return_value=accepted)
            engine = CodexEngine(self.service.settings.value, self.session, self.root / "codex", str(self.binary), lambda *a, **k: None, ask)
            engine._send = AsyncMock()
            await engine._server_request({"id": "permission-1", "method": "item/permissions/requestApproval",
                "params": {"permissions": requested, "reason": "安装测试软件需要下载并写入指定目录"}})
            ask.assert_awaited_once()
            result = engine._send.call_args.args[0]["result"]
            self.assertEqual(result["permissions"], requested if accepted else {})
            self.assertEqual(result["scope"], "turn")

    async def test_auto_review_result_and_rationale_are_visible_in_chat(self):
        output = []
        engine = CodexEngine(self.service.settings.value, self.session, self.root / "codex", str(self.binary),
                             lambda *args, **kwargs: output.append((args, kwargs)), AsyncMock())
        engine._notification("item/autoApprovalReview/completed", {"reviewId": "review-1",
            "action": {"type": "command", "command": "flatpak update"},
            "review": {"status": "denied", "rationale": "请先确认待更新的软件范围"}})
        args, metadata = output[-1]
        self.assertIn("flatpak update", args[2])
        self.assertIn("确认待更新", args[2])
        self.assertEqual(metadata["title"], "自动审核已拒绝")
        self.assertEqual(metadata["status"], "failed")

    async def test_auto_mode_does_not_silently_fall_back_to_a_user_reviewer(self):
        engine = CodexEngine({**self.service.settings.value, "permission_mode": "auto"}, self.session,
                             self.root / "codex", str(self.binary), lambda *a, **k: None, AsyncMock())
        engine.connect = AsyncMock()
        engine.close = AsyncMock()
        engine.request = AsyncMock(return_value={"thread": {"id": "unsupported"}, "approvalsReviewer": "user"})
        with self.assertRaisesRegex(RuntimeError, "未启用自动审核"):
            await engine.run("test")
        self.assertEqual(engine.request.await_count, 1)
        self.assertIsNone(self.session.get("thread_id"))

    def test_missing_explicit_binary_does_not_fall_back(self):
        self.assertIsNone(find_codex(str(self.root / "missing"), self.root))
