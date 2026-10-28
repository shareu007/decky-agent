#!/usr/bin/env python3
"""Check real Codex model overrides against a localhost stub, with no user credentials."""
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


async def main(binary):
    requests = []

    async def respond(request):
        requests.append(await request.json())
        item = {"id": "message", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "model-smoke-ok", "annotations": []}]}
        events = [
            {"type": "response.created", "response": {"id": "response", "status": "in_progress", "output": []}},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": "response", "status": "completed", "output": [item],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}},
        ]
        return web.Response(text="".join("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n" for event in events), content_type="text/event-stream")

    app = web.Application()
    app.router.add_post("/responses", respond)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        with tempfile.TemporaryDirectory(prefix="decky-models-smoke-") as folder:
            root = Path(folder)
            settings = {"auth_mode": "api", "base_url": f"http://127.0.0.1:{port}", "api_key": "",
                        "workspace": str(root), "model": "", "instructions": "Reply without tools.", "network_access": False}
            session = {"thread_id": None}

            async def refuse(*_):
                raise AssertionError("A text-only stub must not execute tools")

            class Probe(CodexEngine):
                async def request(self, method, params, **kwargs):
                    result = await super().request(method, params, **kwargs)
                    if method in ("thread/start", "thread/resume"):
                        assert result.get("model"), "Missing effective model in native response"
                    return result

            first_id = default = None
            for index in range(3):
                model = "" if index != 1 else ("gpt-5.3-codex" if default != "gpt-5.3-codex" else "gpt-5.4")
                output = []
                engine = Probe({**settings, "model": model}, session, root / "codex", binary, lambda *a, **k: output.append(a), refuse)
                await asyncio.wait_for(engine.run("Reply model-smoke-ok. Do not use tools."), 40)
                first_id = first_id or session["thread_id"]
                default = default or session["resolved_model"]
                assert session["thread_id"] == first_id, "Model selection must keep the thread"
                assert session["resolved_model"] == (model or default), (model, default, session["resolved_model"])
                assert requests[-1]["model"] == session["resolved_model"], "Displayed model differs from inference payload"
                assert any("model-smoke-ok" in str(item) for item in output), "Missing model output"
                print(json.dumps({"selected": model or "automatic", "effective_model": session["resolved_model"], "same_thread": True, "local_inference_matches": True}), flush=True)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex"))
    args = parser.parse_args()
    if not args.codex:
        parser.error("Provide --codex /path/to/codex")
    asyncio.run(main(str(Path(args.codex).resolve())))
