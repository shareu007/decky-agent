#!/usr/bin/env python3
"""Exercise the installed Decky process with controlled audio and account STT.

Run on the device with a synthetic 16 kHz mono PCM WAV. Capture is allowed to
reach its normal limit; its local audio is replaced before any upload. No
credentials, ambient audio or transcript are printed. Settings are unchanged.
"""
import argparse
import asyncio
import io
import json
import time
import wave
from pathlib import Path

from decky_control import Decky


async def call(method, *args):
    async with Decky() as decky:
        return await decky.plugin(method, *args)


async def main(audio_path, expected):
    audio = audio_path.read_bytes()
    with wave.open(io.BytesIO(audio), "rb") as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) == (1, 16000, 2)
    state = await call("get_bootstrap")
    assert not state["active_id"] and not state["speech"]["busy"], "Device is busy"
    settings = state["settings"]
    assert settings["auth_mode"] == "chatgpt" and settings["speech_enabled"] and not settings["speech_base_url"]
    if not state["auth"]["signed_in"]:
        state["auth"] = await call("get_account_status")
    assert state["auth"]["signed_in"], "ChatGPT login required"
    directory = Path.home() / "homebrew/data/Decky Agent/speech"
    previous = set(directory.glob("recording-*.wav"))
    session = await call("create_session")
    ticket = None
    try:
        ticket = (await call("start_recording", session["id"]))["id"]
        print(json.dumps({"stage": "capture_started", "test_audio_only": True}), flush=True)
        await asyncio.sleep(state["speech"]["max_seconds"] + 1)
        status = await call("recording_status", ticket)
        assert status["state"] == "ready", "Capture did not stop at its limit"
        candidates = set(directory.glob("recording-*.wav")) - previous
        assert len(candidates) == 1, "Cannot identify owned test audio"
        path = candidates.pop()
        assert path.parent.resolve() == directory.resolve() and not path.is_symlink()
        path.write_bytes(audio)  # The stopped recorder cannot overwrite this.
        started = time.monotonic()
        text = await call("finish_recording", ticket)
        assert expected.casefold() in text.casefold(), "Unexpected synthetic transcription"
        state = await call("get_bootstrap")
        assert not state["speech"]["busy"] and not path.exists()
        print(json.dumps({"installed_account_voice": "PASS", "seconds": round(time.monotonic() - started, 2),
                          "expected_phrase_recognized": True, "temporary_audio_removed": True}), flush=True)
    finally:
        if ticket:
            await call("cancel_recording", ticket)
        await call("delete_session", session["id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--expected", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.audio, args.expected))
