import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import decky_control


class DeploymentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / "plugin.zip"
        with zipfile.ZipFile(self.archive, "w") as z:
            z.writestr("Decky Agent/package.json", json.dumps({"version": "0.1.7"}))
            z.writestr("Decky Agent/plugin.json", json.dumps({"name": "Decky Agent"}))
        self.events = []
        self.refresh_failure = False
        owner = self

        class FakeDecky:
            def __init__(self):
                self.sequence = 0
                self.prompt = True

            async def __aenter__(self):
                owner.events.append("connected")
                return self

            async def __aexit__(self, *_):
                owner.events.append("disconnected")

            async def send(self, route, args):
                self.sequence += 1
                owner.events.append(route)
                return self.sequence

            async def receive(self):
                if self.prompt:
                    self.prompt = False
                    return {"type": 5, "event": "loader/add_plugin_install_prompt",
                            "args": ["Decky Agent", "0.1.7", "test-request"]}
                return {"type": 1, "id": self.sequence}

            async def call(self, route, *args):
                owner.events.append(route)
                if owner.refresh_failure:
                    raise RuntimeError("frontend refresh failed")

        self.decky = patch.object(decky_control, "Decky", FakeDecky)
        self.decky.start()
        self.addCleanup(self.decky.stop)

    async def test_install_refreshes_steam_ui_after_releasing_the_install_socket(self):
        with contextlib.redirect_stdout(io.StringIO()):
            await decky_control.install(self.archive)
        self.assertIn("utilities/restart_webhelper", self.events)
        self.assertLess(self.events.index("disconnected"), self.events.index("utilities/restart_webhelper"))

    async def test_explicit_skip_does_not_refresh_the_steam_ui(self):
        with contextlib.redirect_stdout(io.StringIO()):
            await decky_control.install(self.archive, refresh_ui=False)
        self.assertNotIn("utilities/restart_webhelper", self.events)

    async def test_refresh_failure_is_reported_instead_of_claiming_the_ui_is_updated(self):
        self.refresh_failure = True
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "frontend refresh failed"):
            await decky_control.install(self.archive)
        self.assertNotIn('"frontend_refresh_requested": true', output.getvalue())
