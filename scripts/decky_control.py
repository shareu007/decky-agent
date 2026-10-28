#!/usr/bin/env python3
"""Local Decky administration for this plugin, using its authenticated API.

Run on the target device. Requires aiohttp. Does not print Decky's auth token.
"""
import argparse
import asyncio
import hashlib
import json
import random
import re
from pathlib import Path
from urllib.parse import quote
import zipfile

import aiohttp

PLUGIN = "Decky Agent"
BASE = "http://127.0.0.1:1337"


class Decky:
    async def __aenter__(self):
        self.client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90))
        try:
            async with self.client.get(BASE + "/auth/token") as response:
                response.raise_for_status()
                self.token = await response.text()
            self.ws = await self.client.ws_connect(BASE + "/ws?auth=" + quote(self.token), heartbeat=10)
        except BaseException:
            await self.client.close()
            raise
        self.sequence = random.randrange(1_000_000_000, 2_000_000_000)
        self.pending = set()
        return self

    async def __aexit__(self, *_):
        await self.ws.close()
        await self.client.close()

    async def send(self, route, args):
        self.sequence += 1
        self.pending.add(self.sequence)
        await self.ws.send_json({"type": 0, "id": self.sequence, "route": route, "args": args})
        return self.sequence

    async def receive(self):
        message = await asyncio.wait_for(self.ws.receive(), 60)
        if message.type != aiohttp.WSMsgType.TEXT:
            raise ConnectionError("Decky WebSocket reconnected")
        data = message.json()
        if data.get("type") in (1, -1, 2) and data.get("id") in self.pending:
            await self.ws.send_json({"type": 3, "id": data["id"]})
            self.pending.discard(data["id"])
        return data

    async def call(self, route, *args):
        call_id = await self.send(route, list(args))
        while True:
            data = await self.receive()
            if data.get("id") != call_id:
                continue
            if data["type"] == -1:
                raise RuntimeError(data.get("error", {}).get("message", "Decky method failed"))
            return data.get("result")

    async def plugin(self, method, *args):
        return await self.call("loader/call_plugin_method", PLUGIN, method, *args)


async def refresh_frontend():
    # Decky 3.3 has one active WebSocket. The installer receives import_plugin
    # events itself, so a successful backend install does not refresh Steam's
    # already-mounted React module. Restart through Decky's supported UI route
    # and release this connection before the new frontend reconnects.
    async with Decky() as decky:
        await decky.call("utilities/restart_webhelper")
    print(json.dumps({"frontend_refresh_requested": True, "frontend_verified": False}))


async def install(archive: Path, refresh_ui=True):
    archive = archive.resolve()
    with zipfile.ZipFile(archive) as package:
        metadata = json.loads(package.read(PLUGIN + "/package.json"))
        manifest = json.loads(package.read(PLUGIN + "/plugin.json"))
        if manifest["name"] != PLUGIN:
            raise ValueError("Archive is not Decky Agent")
    with archive.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    confirmed = False
    async with Decky() as decky:
        await decky.send("utilities/install_plugin", [archive.as_uri(), PLUGIN, metadata["version"], digest, 0])
        confirm_id = None
        try:
            while True:
                data = await decky.receive()
                if data.get("type") == 5 and data.get("event") == "loader/add_plugin_install_prompt":
                    args = data["args"]
                    if args[0] == PLUGIN:
                        confirm_id = await decky.send("utilities/confirm_plugin_install", [args[2]])
                        confirmed = True
                if confirm_id and data.get("id") == confirm_id:
                    if data["type"] == -1:
                        raise RuntimeError(data.get("error", {}).get("message", "Installation failed"))
                    break
        except ConnectionError:
            if not confirmed:
                raise
    print(json.dumps({"install_submitted": confirmed, "version": metadata["version"], "sha256": digest}))
    if refresh_ui:
        await refresh_frontend()


async def main(args):
    if args.command == "install":
        await install(Path(args.archive), refresh_ui=not args.skip_ui_refresh)
        return
    if args.command == "refresh-frontend":
        await refresh_frontend()
        return
    async with Decky() as decky:
        if args.command == "health":
            plugins = await decky.call("loader/get_plugins")
            plugin = next((entry for entry in plugins if entry["name"] == PLUGIN), None)
            if not plugin:
                raise RuntimeError("Decky Agent is not loaded")
            state = await decky.plugin("get_bootstrap")
            print(json.dumps({"plugin": plugin, "backend_ready": True, "codex_available": state["codex_available"],
                              "speech": state["speech"], "api_key_set": state["settings"]["api_key_set"],
                              "auth": {key: state.get("auth", {}).get(key) for key in ("phase", "signed_in", "busy")},
                              "model_configured": bool(state["settings"]["model"])}))
        elif args.command == "call":
            result = await decky.plugin(args.method, *json.loads(args.args))
            print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    install_parser = sub.add_parser("install")
    install_parser.add_argument("archive")
    install_parser.add_argument("--skip-ui-refresh", action="store_true", help="只安装后端文件，不重载 Steam 界面")
    sub.add_parser("refresh-frontend", help="通过 Decky 官方接口重载 Steam 界面组件")
    sub.add_parser("health")
    call = sub.add_parser("call")
    call.add_argument("method")
    call.add_argument("args", nargs="?", default="[]")
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except Exception as error:
        # aiohttp exceptions may contain the WebSocket URL, including the token.
        raise SystemExit(re.sub(r"auth=[^\s&'\"]+", "auth=[REDACTED]", str(error))) from None
