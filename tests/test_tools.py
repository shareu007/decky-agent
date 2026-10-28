import asyncio
import json
import os
import threading
import tempfile
import unittest
from pathlib import Path

from decky_agent.tools import WorkspaceTools


class ToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.requests = []
        self.accept = True

        async def ask(*args):
            self.requests.append(args)
            return self.accept

        self.tools = WorkspaceTools(self.root, False, ask, lambda *a, **k: None)

    async def test_path_traversal_and_symlink_escape_are_blocked(self):
        outside = self.root.parent / "secret"
        outside.write_text("private")
        (self.root / "link").symlink_to(outside)
        for path in ["../secret", str(outside), "link"]:
            result = await self.tools.execute("read_file", json.dumps({"path": path}))
            self.assertIn("超出工作目录", result)
            self.assertNotIn("private", result)

    async def test_write_requires_approval_and_shows_diff(self):
        target = self.root / "test.txt"
        target.write_text("before\n")
        self.accept = False
        await self.tools.execute("write_file", json.dumps({"path": "test.txt", "content": "after\n"}))
        self.assertEqual(target.read_text(), "before\n")
        self.assertIn("-before", self.requests[0][2])
        self.assertIn("+after", self.requests[0][2])
        self.accept = True
        result = await self.tools.execute("write_file", json.dumps({"path": "test.txt", "content": "after\n"}))
        self.assertIn("已保存", result)
        self.assertEqual(target.read_text(), "after\n")

    async def test_concurrent_file_edit_invalidates_approval(self):
        target = self.root / "test.txt"
        target.write_text("before")

        async def change_while_waiting(*_):
            target.write_text("another editor")
            return True

        self.tools.ask = change_while_waiting
        result = await self.tools.execute("write_file", json.dumps({"path": "test.txt", "content": "after"}))
        self.assertIn("审批期间被修改", result)
        self.assertEqual(target.read_text(), "another editor")

    async def test_shell_is_disabled_by_default(self):
        result = await self.tools.execute("run_command", '{"command":"printf hello"}')
        self.assertIn("未启用", result)
        self.assertEqual(self.requests, [])

    async def test_approved_shell_and_cancel(self):
        self.tools.allow_shell = True
        result = await self.tools.execute("run_command", '{"command":"printf hello"}')
        self.assertIn("exit_code=0\nhello", result)
        task = asyncio.create_task(self.tools.execute("run_command", '{"command":"sleep 30"}'))
        await asyncio.sleep(.1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)

    async def test_invalid_tool_arguments_are_returned_as_errors(self):
        for name, args in [("read_file", "[]"), ("read_file", "{"), ("read_file", '{"unexpected":1}'),
                           ("no_such_tool", "{}"), ("write_file", '{"path":"a","content":42}')]:
            result = await self.tools.execute(name, args)
            self.assertIn("工具错误", result)

    async def test_fifo_read_and_write_are_rejected_without_blocking(self):
        pipe = self.root / "pipe"
        os.mkfifo(pipe)
        for name, arguments in [("read_file", {"path": "pipe"}), ("write_file", {"path": "pipe", "content": "x"})]:
            result = await asyncio.wait_for(self.tools.execute(name, json.dumps(arguments)), 1)
            self.assertIn("普通文件", result)
        self.assertEqual(self.requests, [])

    async def test_file_replaced_with_fifo_during_approval_is_rejected(self):
        target = self.root / "test.txt"
        target.write_text("before")

        async def swap(*_):
            target.unlink()
            os.mkfifo(target)
            return True

        self.tools.ask = swap
        result = await asyncio.wait_for(self.tools.execute("write_file", '{"path":"test.txt","content":"after"}'), 1)
        self.assertIn("普通文件", result)

    async def test_cancellation_waits_for_an_approved_write_to_finish(self):
        started = threading.Event()
        release = threading.Event()
        original = self.tools._write_regular

        def delayed(*args):
            started.set()
            if not release.wait(2):
                raise TimeoutError("test write not released")
            original(*args)

        self.tools._write_regular = delayed
        task = asyncio.create_task(self.tools.execute("write_file", '{"path":"a.txt","content":"approved"}'))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            task.cancel()
            await asyncio.sleep(.02)
            self.assertFalse(task.done(), "Stop must not complete while an approved write is still running")
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((self.root / "a.txt").read_text(), "approved")
