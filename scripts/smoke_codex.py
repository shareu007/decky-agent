#!/usr/bin/env python3
"""Exercise real Codex against a local fake Responses API; makes no paid API call."""
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import web
from decky_agent.codex import CodexEngine


async def main():
    binary = shutil.which("codex")
    if not binary:
        raise SystemExit("需要在本机安装 Codex 才能运行真实协议 smoke test")
    requests = []

    async def respond(request):
        body = await request.json()
        requests.append(body)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        item = {"id": "msg_smoke", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "decky-smoke-ok", "annotations": []}]}
        events = [
            {"type": "response.created", "response": {"id": "resp_smoke", "status": "in_progress", "output": []}},
            {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}},
            {"type": "response.output_text.delta", "item_id": "msg_smoke", "output_index": 0, "content_index": 0, "delta": "decky-smoke-ok"},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": "resp_smoke", "status": "completed", "output": [item],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                          "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}},
        ]
        for event in events:
            await response.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())
        await response.write_eof()
        return response

    async def models(request):
        return web.json_response({"data": []})

    app = web.Application()
    app.router.add_post("/v1/responses", respond)
    app.router.add_get("/v1/models", models)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        with tempfile.TemporaryDirectory(prefix="decky-codex-smoke-") as directory:
            root = Path(directory)
            settings = {"base_url": f"http://127.0.0.1:{port}/v1", "api_key": "smoke-test-key",
                        "model": "gpt-5.3-codex", "workspace": str(root), "instructions": "Reply briefly.", "network_access": False}
            session = {"thread_id": None}
            output = []

            async def approve(*_):
                return False

            engine = CodexEngine(settings, session, root / "codex-home", binary,
                                 lambda *a, **k: output.append(a), approve)
            await asyncio.wait_for(engine.run("Reply with decky-smoke-ok. Do not use tools."), 40)
            assert requests, "Codex did not contact the custom local API"
            assert any("decky-smoke-ok" in str(item) for item in output), output
            assert session["thread_id"], "No thread ID returned"
            # Verify persisted conversations can be resumed by a fresh real process.
            engine = CodexEngine(settings, session, root / "codex-home", binary,
                                 lambda *a, **k: output.append(a), approve)
            await asyncio.wait_for(engine.run("Reply briefly again. Do not use tools."), 40)
            assert len(requests) >= 2
            print(f"PASS: real Codex initialize, custom provider, SSE output, thread resume ({len(requests)} local calls)")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
