import json
import math
import stat
import tempfile
import unittest
from pathlib import Path

from decky_agent.service import AgentService


class FrontendReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.service = AgentService(root / "settings", root / "data", root, root)
        self.path = root / "data/diagnostics/frontend.json"
        self.report = {"version": "0.1.8", "same_window": False, "viewport_height": 800,
            "global_viewport_height": 0, "panel_top": 180, "panel_height": 560,
            "messages_height": 410, "visible_messages_height": 390, "composer_height": 74}

    def test_only_build_and_plugin_geometry_are_persisted(self):
        self.service.report_frontend({**self.report, "chat": "private chat must not be stored"})
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["version"], "0.1.8")
        self.assertEqual(saved["global_viewport_height"], 0)
        self.assertNotIn("private chat", self.path.read_text())
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_invalid_report_cannot_replace_the_last_valid_diagnostic(self):
        self.service.report_frontend(self.report)
        original = self.path.read_bytes()
        for bad in [{"version": "../../elsewhere"}, {"panel_height": math.nan},
                    {"viewport_height": True}, {"messages_height": 20000}, {"same_window": "no"}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.service.report_frontend({**self.report, **bad})
            self.assertEqual(self.path.read_bytes(), original)
