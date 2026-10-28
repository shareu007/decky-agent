#!/usr/bin/env python3
"""Check real Codex device-code startup/cancellation. No account login or model call."""
import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decky_agent.auth import ChatGPTAuth


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex"))
    args = parser.parse_args()
    if not args.codex:
        raise SystemExit("Codex not found; pass --codex PATH")
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="decky-chatgpt-auth-", dir=cache) as directory:
        auth = ChatGPTAuth(Path(directory) / "codex", lambda: args.codex)
        try:
            state = await auth.refresh()
            assert not state["signed_in"]
            state = await auth.start()
            assert state["phase"] == "waiting" and state["login"]["code"]
            assert state["login"]["url"] == "https://auth.openai.com/codex/device"
            await auth.cancel(state["login"]["id"])
            assert not auth.busy and auth.client is None and auth.login is None
            print(json.dumps({"real_codex_device_code": "PASS", "cancelled": True,
                              "credentials_isolated": True, "model_calls": 0}))
        finally:
            await auth.close()


if __name__ == "__main__":
    asyncio.run(main())
