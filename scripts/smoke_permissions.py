#!/usr/bin/env python3
"""Verify permission overrides against real Codex and a local-only model stub.

No user credentials, system commands, installations or paid model calls.
"""
import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from decky_agent.codex import CodexEngine
from decky_agent.permissions import codex_permissions


async def main(binary):
    async def respond(request):
        await request.json()
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        item = {"id": "message", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "permission-smoke-ok", "annotations": []}]}
        events = [
            {"type": "response.created", "response": {"id": "response", "status": "in_progress", "output": []}},
            {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}},
            {"type": "response.output_text.delta", "item_id": "message", "output_index": 0, "content_index": 0, "delta": "permission-smoke-ok"},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": "response", "status": "completed", "output": [item],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                          "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}},
        ]
        for event in events:
            await response.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/responses", respond)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        with tempfile.TemporaryDirectory(prefix="decky-permissions-smoke-") as folder:
            root = Path(folder)
            settings = {"auth_mode": "api", "base_url": f"http://127.0.0.1:{port}", "api_key": "",
                        "workspace": str(root), "model": "gpt-5.3-codex", "instructions": "Reply only. Do not use tools.",
                        "network_access": False}
            session = {"thread_id": None}

            async def refuse(*_):
                raise AssertionError("No approval should be needed for a text-only local model stub")

            class Probe(CodexEngine):
                async def request(self, method, params, **kwargs):
                    result = await super().request(method, params, **kwargs)
                    if method in ("thread/start", "thread/resume"):
                        policy, turn = codex_permissions(self.settings)
                        assert result["approvalPolicy"] == policy["approvalPolicy"], result["approvalPolicy"]
                        assert result["approvalsReviewer"] == policy["approvalsReviewer"], result["approvalsReviewer"]
                        assert result["sandbox"]["type"] == turn["sandboxPolicy"]["type"], result["sandbox"]
                    return result

            first_id = None
            for mode in ("ask", "auto", "full", "ask"):
                output = []
                engine = Probe({**settings, "permission_mode": mode}, session, root / "codex", str(Path(binary).resolve()),
                               lambda *a, **k: output.append(a), refuse)
                await asyncio.wait_for(engine.run("Reply permission-smoke-ok without using tools."), 40)
                assert any("permission-smoke-ok" in str(item) for item in output)
                first_id = first_id or session["thread_id"]
                assert session["thread_id"] == first_id, "Permission changes must preserve the conversation"
                print(json.dumps({"mode": mode, "effective_native_policy": "PASS", "same_thread": True}), flush=True)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex"))
    args = parser.parse_args()
    if not args.codex:
        parser.error("Provide --codex /path/to/codex")
    asyncio.run(main(args.codex))
