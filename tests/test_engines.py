import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pathlib import Path

from decky_agent.compatible import CompatibleEngine
from decky_agent.service import AgentService


class FakeClient:
    def __init__(self, turns):
        self.turns = iter(turns)
        self.requests = []

    async def request(self, path, payload):
        self.requests.append((path, json.loads(json.dumps(payload))))
        for delta, reason in next(self.turns):
            yield {"choices": [{"index": 0, "delta": delta, "finish_reason": reason}]}


class EngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.service = AgentService(root / "settings", root / "data", root, root)
        self.service.save_settings({"engine": "compatible", "model": "custom", "workspace": str(root / "workspace")})
        self.session = self.service.sessions.create(self.service.settings.value)
        Path(self.session["workspace"]).mkdir()
        self.output = []

    async def test_streamed_tool_call_arguments_and_continuation(self):
        client = FakeClient([
            [({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "write_file", "arguments": '{"path":"hello.txt",'}}]}, None),
             ({"tool_calls": [{"index": 0, "function": {"arguments": '"content":"hello"}'}}]}, "tool_calls")],
            [({"content": "保存"}, None), ({"content": "成功"}, "stop")],
        ])

        async def approve(*_):
            return True

        engine = CompatibleEngine(self.service.settings.value, self.session,
                                  lambda *a, **k: self.output.append((a, k)), approve, client)
        await engine.run("create hello")
        self.assertEqual((Path(self.session["workspace"]) / "hello.txt").read_text(), "hello")
        self.assertEqual(client.requests[1][1]["messages"][-1]["tool_call_id"], "call_1")
        self.assertEqual(self.session["messages"][-1]["content"], "保存成功")

    async def test_truncated_output_is_not_reported_success(self):
        client = FakeClient([[({"content": "partial"}, "length")]])
        engine = CompatibleEngine(self.service.settings.value, self.session, lambda *a, **k: None, None, client)
        with self.assertRaisesRegex(RuntimeError, "未完成"):
            await engine.run("work")
        self.assertEqual(self.session["messages"], [])

    async def test_cross_session_approval_is_rejected(self):
        other = self.service.sessions.create(self.service.settings.value)
        task = asyncio.create_task(self.service._ask(self.session, "approval", "test", "command"))
        await asyncio.sleep(0)
        request_id = self.session["pending"][0]["id"]
        with self.assertRaises(ValueError):
            self.service.respond(other["id"], request_id, True)
        self.service.respond(self.session["id"], request_id, False)
        self.assertFalse(await task)
        self.assertEqual(self.session["pending"], [])

    async def test_immediate_cancellation_cleans_up(self):
        await self.service.start(self.session["id"], "test")
        await self.service.stop(self.session["id"])
        self.assertIsNone(self.service.active_id)
        self.assertEqual(self.session["status"], "cancelled")

    async def test_changed_provider_requires_new_session(self):
        self.session["items"].append({"id": "1", "text": "previous task"})
        self.service.save_settings({"base_url": "http://localhost:1234/v1"})
        with self.assertRaisesRegex(ValueError, "新建会话"):
            await self.service.start(self.session["id"], "test")

    async def test_split_stream_secret_is_redacted(self):
        self.service.save_settings({"api_key": "super-secret"})
        self.service._publish(self.session, "a", "assistant", "super-")
        self.service._publish(self.session, "a", "assistant", "secret", append=True)
        self.assertEqual(self.session["items"][0]["text"], "[REDACTED]")

    async def test_completed_tools_survive_step_limit_and_resume(self):
        self.service.save_settings({"max_steps": 1})
        call = {"index": 0, "id": "saved-file", "function": {"name": "write_file", "arguments": '{"path":"a.txt","content":"done"}'}}
        client = FakeClient([[({"tool_calls": [call]}, "tool_calls")]])
        engine = CompatibleEngine(self.service.settings.value, self.session, lambda *a, **k: None, AsyncMock(return_value=True), client)
        with self.assertRaisesRegex(RuntimeError, "轮工具调用限制"):
            await engine.run("create a file")
        self.assertEqual((Path(self.session["workspace"]) / "a.txt").read_text(), "done")
        self.assertEqual(self.session["messages"][-1]["tool_call_id"], "saved-file")
        self.assertIn("已保存", self.session["messages"][-1]["content"])
        continuation = FakeClient([[({"content": "continued"}, "stop")]])
        engine = CompatibleEngine(self.service.settings.value, self.session, lambda *a, **k: None, None, continuation)
        await engine.run("continue")
        self.assertTrue(any(m.get("tool_call_id") == "saved-file" for m in continuation.requests[0][1]["messages"]))

    async def test_cancelled_tool_batch_keeps_results_and_closes_call_pairs(self):
        waiting = asyncio.Event()

        async def approve(_kind, _title, detail):
            if "b.txt" in detail:
                waiting.set()
                await asyncio.Event().wait()
            return True

        calls = [{"index": i, "id": name, "function": {"name": "write_file", "arguments": json.dumps({"path": name + ".txt", "content": name})}} for i, name in enumerate(["a", "b"])]
        engine = CompatibleEngine(self.service.settings.value, self.session, lambda *a, **k: None, approve,
                                  FakeClient([[({"tool_calls": calls}, "tool_calls")]]))
        task = asyncio.create_task(engine.run("write two files"))
        await asyncio.wait_for(waiting.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        results = [m for m in self.session["messages"] if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in results], ["a", "b"])
        self.assertIn("已保存", results[0]["content"])
        self.assertIn("被中断", results[1]["content"])
        self.assertFalse((Path(self.session["workspace"]) / "b.txt").exists())

    async def test_redaction_keeps_routing_ids_and_valid_tool_arguments(self):
        self.service.save_settings({"api_key": "1234", "base_url": "http://localhost:1234/v1"})
        self.session["base_url"] = "http://localhost:1234/v1"
        before = {k: self.session[k] for k in ("id", "engine", "workspace", "base_url")}
        self.session["messages"] = [
            {"role": "assistant", "content": "key 1234", "tool_calls": [{"id": "call-1234", "function": {"name": "read_file", "arguments": '{"path":"1234.txt"}'}}]},
            {"role": "tool", "tool_call_id": "call-1234", "content": "1234"},
        ]
        self.service._finish(self.session)
        for key, value in before.items():
            self.assertEqual(self.session[key], value)
        call = self.session["messages"][0]["tool_calls"][0]
        self.assertEqual(call["id"], "call-1234")
        self.assertEqual(json.loads(call["function"]["arguments"]), {"path": "[REDACTED].txt"})
        self.assertEqual(self.session["messages"][1]["tool_call_id"], "call-1234")
        self.assertEqual(self.session["messages"][1]["content"], "[REDACTED]")

    async def test_redaction_keeps_approval_and_question_ids(self):
        self.service.save_settings({"api_key": "1234"})
        with patch("decky_agent.service.uuid.uuid4", return_value=SimpleNamespace(hex="request-1234")):
            task = asyncio.create_task(self.service._ask(self.session, "input", "Question", "", [
                {"id": "question-1234", "question": "key 1234", "header": "input"},
            ]))
            await asyncio.sleep(0)
            request = self.session["pending"][0]
            self.assertEqual(request["id"], "request-1234")
            self.assertEqual(request["questions"][0]["id"], "question-1234")
            self.service.respond(self.session["id"], request["id"], True, {"question-1234": "answer"})
            self.assertEqual(await task, {"question-1234": "answer"})

    async def test_save_failure_still_releases_active_task(self):
        with patch("decky_agent.service.CompatibleEngine", return_value=SimpleNamespace(run=AsyncMock())):
            await self.service.start(self.session["id"], "task")
            with patch.object(self.service.sessions, "save", side_effect=OSError("disk full")):
                await self.service.task
        self.assertIsNone(self.service.bootstrap()["active_id"])
        self.assertEqual(self.session["status"], "failed")
        self.assertIn("未能保存", self.session["items"][-1]["text"])
        self.service.save_settings({"max_steps": 2})

    async def test_start_save_failure_never_leaves_a_running_session(self):
        with patch.object(self.service.sessions, "save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(ValueError, "任务未启动"):
                await self.service.start(self.session["id"], "task")
        self.assertEqual(self.session["status"], "failed")
        self.assertIsNone(self.service.active_id)
        self.assertIsNone(self.service.task)
