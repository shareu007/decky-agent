#!/usr/bin/env python3
"""Test the installed Decky backend with 3 seconds of local-only microphone audio.

Audio goes only to a temporary 127.0.0.1 endpoint, is not played or saved by the
endpoint, and the plugin removes its temporary WAV. Speech settings are restored.
"""
import array
import asyncio
import io
import json
import math
import wave

from aiohttp import web
from decky_control import Decky


async def call(method, *args):
    async with Decky() as decky:
        return await decky.plugin(method, *args)


async def main():
    original = await call("get_bootstrap")
    settings = original["settings"]
    if original["active_id"] or original["speech"]["busy"]:
        raise RuntimeError("An existing task or recording is active; test not started")
    if settings["speech_api_key_set"]:
        raise RuntimeError("A custom speech key is already configured; test will not overwrite it")
    metrics = {}

    async def transcribe(request):
        reader = await request.multipart()
        while part := await reader.next():
            if part.name == "file":
                data = bytes(await part.read())
                with wave.open(io.BytesIO(data), "rb") as audio:
                    frames = audio.getnframes()
                    rate = audio.getframerate()
                    channels = audio.getnchannels()
                    samples = array.array("h", audio.readframes(frames))
                metrics.update({"seconds": round(frames / rate, 2), "sample_rate": rate,
                                "channels": channels, "rms": round(math.sqrt(sum(n * n for n in samples) / max(1, len(samples))) / 32768, 5)})
        return web.json_response({"text": "本机录音链路测试"})

    app = web.Application()
    app.router.add_post("/v1/audio/transcriptions", transcribe)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    session_id = None
    recording_id = None
    changed = False
    try:
        await call("save_settings", {"speech_enabled": True, "speech_model": "local-device-test",
                                   "speech_base_url": f"http://127.0.0.1:{port}/v1", "clear_speech_api_key": True})
        changed = True
        session = await call("create_session")
        session_id = session["id"]
        recording = await call("start_recording", session_id)
        recording_id = recording["id"]
        await asyncio.sleep(3)
        text = await call("finish_recording", recording_id)
        assert text == "本机录音链路测试"
        assert metrics.get("sample_rate") == 16000 and metrics.get("channels") == 1
        assert metrics.get("seconds", 0) > .5
        state = await call("get_bootstrap")
        assert not state["speech"]["busy"]
        print(json.dumps({"installed_backend_microphone": "PASS", "local_only": True, **metrics}, ensure_ascii=False))
    finally:
        if recording_id:
            await call("cancel_recording", recording_id)
        if changed:
            await call("save_settings", {"speech_enabled": settings["speech_enabled"], "speech_model": settings["speech_model"],
                                       "speech_base_url": settings["speech_base_url"], "clear_speech_api_key": True})
        if session_id:
            await call("delete_session", session_id)
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
