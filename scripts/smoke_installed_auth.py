#!/usr/bin/env python3
"""Verify the installed Decky auth RPC without logging into an account."""
import asyncio
import json

from decky_control import Decky


async def main():
    async with Decky() as decky:
        state = await decky.plugin("get_bootstrap")
        if state["active_id"] or state["speech"]["busy"] or state["auth"]["busy"]:
            raise RuntimeError("An existing task or login is active; test not started")
        account = await decky.plugin("get_account_status")
        if account["signed_in"]:
            print(json.dumps({"installed_auth_rpc": "PASS", "already_signed_in": True, "login_test_skipped": True}))
            return
        login_id = None
        try:
            account = await decky.plugin("login_chatgpt")
            login_id = account["login"]["id"]
            assert account["login"]["code"] and account["login"]["url"] == "https://auth.openai.com/codex/device"
            state = await decky.plugin("get_bootstrap")
            assert state["auth"]["phase"] == "waiting" and state["auth"]["busy"]
            await decky.plugin("cancel_chatgpt_login", login_id)
            state = await decky.plugin("get_bootstrap")
            assert not state["auth"]["busy"] and state["auth"]["login"] is None
            print(json.dumps({"installed_auth_rpc": "PASS", "official_device_code_received": True,
                              "cancelled": True, "model_calls": 0}))
        finally:
            if login_id:
                await decky.plugin("cancel_chatgpt_login", login_id)


if __name__ == "__main__":
    asyncio.run(main())
