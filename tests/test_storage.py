import json
import os
import tempfile
import unittest
from pathlib import Path

from decky_agent.storage import SessionStore, SettingsStore, normalize_url


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = SettingsStore(self.root / "settings.json", self.root)

    def test_key_remains_backend_only_and_file_is_private(self):
        self.store.update({"api_key": "test-secret", "model": "custom"})
        self.assertNotIn("test-secret", json.dumps(self.store.public()))
        self.assertTrue(self.store.public()["api_key_set"])
        self.assertEqual(os.stat(self.store.path).st_mode & 0o777, 0o600)
        self.store.update({"api_key": ""})
        self.assertEqual(self.store.value["api_key"], "test-secret")
        self.store.update({"clear_api_key": True})
        self.assertFalse(self.store.public()["api_key_set"])

    def test_full_gui_payload_preserves_boolean_and_numeric_settings(self):
        payload = {**self.store.public(), "api_key": "test-key", "allow_shell": True,
                   "network_access": False, "max_steps": 12, "model": "custom"}
        self.store.update(payload)
        restored = SettingsStore(self.store.path, self.root)
        self.assertIs(restored.value["allow_shell"], True)
        self.assertIs(restored.value["network_access"], False)
        self.assertEqual(restored.value["max_steps"], 12)
        self.assertEqual(restored.value["model"], "custom")

    def test_permission_mode_migration_persistence_and_rejection_are_explicit(self):
        self.store.path.write_text('{"model":"old-model"}')
        restored = SettingsStore(self.store.path, self.root)
        self.assertEqual(restored.value["permission_mode"], "ask")
        restored.update({"permission_mode": "auto"})
        self.assertEqual(SettingsStore(self.store.path, self.root).public()["permission_mode"], "auto")
        before = restored.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "权限模式"):
            restored.update({"permission_mode": "anything"})
        self.assertEqual(restored.path.read_bytes(), before)

    def test_url_normalization_preserves_custom_proxy_path(self):
        self.assertEqual(normalize_url("http://localhost:11434/v1/chat/completions/"), "http://localhost:11434/v1")
        self.assertEqual(normalize_url("https://proxy.test/api/v2/responses"), "https://proxy.test/api/v2")
        for value in ["file:///tmp/x", "https://a:b@example.org", "https://x/v1?key=secret", "https://x/#a", "https://x:abc"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_url(value)

    def test_interface_language_defaults_migrates_and_persists_without_changing_instructions(self):
        self.assertEqual(self.store.public()["language"], "zh-CN")
        instructions = self.store.value["instructions"]
        self.store.update({"language": "en"})
        restored = SettingsStore(self.store.path, self.root)
        self.assertEqual(restored.public()["language"], "en")
        self.assertEqual(restored.value["instructions"], instructions)
        before = restored.path.read_bytes()
        with self.assertRaises(ValueError):
            restored.update({"language": "unknown"})
        self.assertEqual(restored.path.read_bytes(), before)

    def test_invalid_settings_are_atomic(self):
        for changes in [{"workspace": "."}, {"workspace": "/"}, {"engine": "unknown"},
                        {"auth_mode": "unknown"}, {"engine": "compatible", "auth_mode": "chatgpt"},
                        {"max_steps": True}, {"max_steps": 51}, {"allow_shell": "yes"},
                        {"codex_path": "codex"}, {"api_key": "key\nInjected: yes"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.store.update(changes)
        self.assertEqual(self.store.value, self.store.defaults)
        self.assertFalse(self.store.path.exists())

    def test_sessions_restore_idle_without_pending_approvals(self):
        sessions = SessionStore(self.root / "sessions")
        session = sessions.create(self.store.value)
        session["status"] = "waiting"
        session["pending"] = [{"id": "stale"}]
        sessions.save(session)
        restored = SessionStore(self.root / "sessions").get(session["id"])
        self.assertEqual(restored["status"], "idle")
        self.assertEqual(restored["pending"], [])
        self.assertNotIn("messages", SessionStore.public(restored))
        with self.assertRaises(ValueError):
            sessions.delete("../../settings")

    def test_nested_secret_redaction_handles_quoted_keys(self):
        self.store.update({"api_key": 'secret"quote'})
        self.assertEqual(self.store.redact_value({"a": ['xsecret"quotey']}), {"a": ["x[REDACTED]y"]})

    def test_speech_settings_are_private_normalized_and_can_clear_their_key(self):
        self.store.update({"speech_enabled": True, "speech_model": "custom-transcribe",
                           "speech_base_url": "http://localhost:9000/v1/audio/transcriptions", "speech_api_key": "speech-secret"})
        self.assertEqual(self.store.value["speech_base_url"], "http://localhost:9000/v1")
        self.assertNotIn("speech-secret", json.dumps(self.store.public()))
        self.assertTrue(self.store.public()["speech_api_key_set"])
        self.store.update({"speech_api_key": ""})
        self.assertEqual(self.store.value["speech_api_key"], "speech-secret")
        self.assertEqual(self.store.redact("speech-secret"), "[REDACTED]")
        self.store.update({"clear_speech_api_key": True})
        self.assertFalse(self.store.public()["speech_api_key_set"])

    def test_enabled_speech_requires_a_model(self):
        with self.assertRaisesRegex(ValueError, "转写模型"):
            self.store.update({"speech_enabled": True, "speech_model": ""})

    def test_chatgpt_model_is_independent_of_retained_api_settings(self):
        self.store.update({"model": "api-model", "api_key": "saved-key", "auth_mode": "chatgpt", "chatgpt_model": ""})
        session = SessionStore(self.root / "sessions").create(self.store.value)
        self.assertEqual(session["model"], "")
        self.assertEqual(session["auth_mode"], "chatgpt")
        restored = SettingsStore(self.store.path, self.root)
        self.assertEqual(restored.value["model"], "api-model")
        self.assertEqual(restored.value["api_key"], "saved-key")

    def test_legacy_settings_and_sessions_migrate_to_api_authentication(self):
        self.store.path.write_text('{"engine":"codex","model":"legacy-model"}')
        restored = SettingsStore(self.store.path, self.root)
        self.assertEqual(restored.value["auth_mode"], "api")
        sessions = SessionStore(self.root / "sessions")
        session = sessions.create(restored.value)
        del session["auth_mode"]
        del session["auth_identity"]
        sessions.save(session)
        migrated = SessionStore(sessions.root).get(session["id"])
        self.assertEqual(migrated["auth_mode"], "api")
        self.assertIsNone(migrated["auth_identity"])
