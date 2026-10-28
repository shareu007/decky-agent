import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from decky_agent.auth import ChatGPTAuth
from decky_agent.service import AgentService
from decky_agent.storage import atomic_json
from decky_agent.http import SpeechHTTPError
from decky_agent.codex import CodexEngine


class AuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "fake-codex"
        self.binary.write_text(f"#!{sys.executable}\n" + (Path(__file__).parent / "fixtures/fake_auth_codex.py").read_text())
        self.binary.chmod(0o755)
        self.home = self.root / "codex"
        self.auth = ChatGPTAuth(self.home, lambda: str(self.binary))
        self.addAsyncCleanup(self.auth.close)

    async def wait_for(self, predicate):
        async def poll():
            while not predicate():
                await asyncio.sleep(.01)
        await asyncio.wait_for(poll(), 4)

    def complete(self, **event):
        atomic_json(self.home / "fixture-finish.json", event)

    def signed_in(self, email="test@example.com"):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "fixture-account.json").write_text(json.dumps({"type": "chatgpt", "email": email, "planType": "plus"}))

    async def test_device_code_completion_ignores_other_attempts_and_restores(self):
        state = await self.auth.start()
        self.assertEqual(state["phase"], "waiting")
        self.assertEqual(state["login"]["code"], "TEST-1234")
        self.assertEqual(state["login"]["url"], "https://auth.openai.com/codex/device")
        self.assertEqual(self.home.stat().st_mode & 0o777, 0o700)
        await asyncio.sleep(.03)
        self.assertFalse(self.auth.snapshot()["signed_in"])
        self.complete()
        await self.wait_for(lambda: self.auth.snapshot()["signed_in"])
        self.assertIsNone(self.auth.client)
        identity = self.auth.identity
        other = ChatGPTAuth(self.home, lambda: str(self.binary))
        try:
            state = await other.refresh()
            self.assertEqual(state["account"], {"email": "test@example.com", "plan": "plus"})
            self.assertEqual(identity, other.identity)
            self.assertNotIn("accessToken", json.dumps(state))
            self.assertNotIn("never-forward", json.dumps(state))
        finally:
            await other.close()

    async def test_completion_before_login_reply_is_not_lost(self):
        self.home.mkdir()
        (self.home / "fixture-control.json").write_text('{"early":true}')
        await self.auth.start()
        await self.wait_for(lambda: self.auth.snapshot()["signed_in"])

    async def test_cancel_matches_ticket_and_removes_device_code(self):
        state = await self.auth.start()
        process = self.auth.client.process
        await self.auth.cancel("stale-attempt")
        self.assertIsNone(process.returncode)
        await self.auth.cancel(state["login"]["id"])
        self.assertIsNotNone(process.returncode)
        self.assertIsNone(self.auth.login)
        self.assertIsNone(self.auth.client)
        self.assertFalse(self.auth.busy)

    async def test_login_expiry_stops_process_and_drops_code(self):
        with patch("decky_agent.auth.LOGIN_SECONDS", .05):
            await self.auth.start()
            process = self.auth.client.process
            await self.wait_for(lambda: self.auth.phase == "error" and not self.auth.busy)
        self.assertIsNotNone(process.returncode)
        self.assertIsNone(self.auth.login)

    async def test_failed_login_does_not_forward_raw_errors(self):
        await self.auth.start()
        self.complete(success=False)
        await self.wait_for(lambda: self.auth.phase == "error")
        self.assertNotIn("token-must-not-leak", json.dumps(self.auth.snapshot()))
        self.assertIsNone(self.auth.login)

    async def test_only_official_device_url_is_accepted(self):
        self.home.mkdir()
        (self.home / "fixture-control.json").write_text('{"bad_url":true}')
        with self.assertRaises(ValueError):
            await self.auth.start()
        self.assertIsNone(self.auth.client)
        self.assertIsNone(self.auth.login)

    async def test_logout_cancels_pending_login_and_clears_persisted_account(self):
        self.signed_in()
        await self.auth.start()
        state = await self.auth.logout()
        self.assertFalse(state["signed_in"])
        self.assertFalse((self.home / "fixture-account.json").exists())
        self.assertIsNone(self.auth.login)

    async def test_official_provider_never_inherits_api_key_environment(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-inherit", "DECKY_AGENT_API_KEY": "must-not-inherit"}):
            await self.auth.refresh()
        startup = json.loads((self.home / "fixture-start.json").read_text())
        self.assertEqual(startup, {"provider": "openai", "chat_key_env": False, "openai_key_env": False, "custom_provider": False})

    async def test_model_catalog_uses_official_provider_and_pagination(self):
        self.signed_in()
        self.assertEqual(await self.auth.models(), ["codex-one", "codex-two"])
        calls = [json.loads(line) for line in (self.home / "fixture-calls.jsonl").read_text().splitlines()]
        self.assertEqual([call["params"]["cursor"] for call in calls if call["method"] == "model/list"], [None, "page2"])

    async def test_model_picker_preserves_slug_display_name_and_default_only(self):
        self.signed_in()
        self.assertEqual(await self.auth.model_catalog(), [
            {"model": "codex-one", "display_name": "Codex One", "is_default": True},
            {"model": "codex-two", "display_name": "Codex Two", "is_default": False},
        ])

    async def test_account_without_email_uses_private_persisted_session_scope(self):
        self.signed_in(None)
        self.assertTrue((await self.auth.refresh())["signed_in"])
        self.assertTrue(self.auth.identity)

    async def test_close_cleans_up_pending_login_process(self):
        await self.auth.start()
        process = self.auth.client.process
        await self.auth.close()
        self.assertIsNotNone(process.returncode)
        self.assertIsNone(self.auth.watcher)
        self.assertIsNone(self.auth.login)

    def service(self):
        service = AgentService(self.root / "config", self.root / "data", self.root, self.root)
        service.save_settings({"auth_mode": "chatgpt", "codex_path": str(self.binary)})
        self.addAsyncCleanup(service.close)
        return service

    async def test_service_requires_sign_in_and_prevents_login_settings_race(self):
        service = self.service()
        session = service.create_session()
        with self.assertRaisesRegex(ValueError, "登录"):
            await service.start(session["id"], "test")
        state = await service.login_chatgpt()
        with self.assertRaisesRegex(ValueError, "登录"):
            service.save_settings({"auth_mode": "api"})
        with self.assertRaisesRegex(ValueError, "登录"):
            await service.start(session["id"], "test")
        await service.cancel_login(state["login"]["id"])

    async def test_service_default_model_uses_builtin_provider_and_restores_thread(self):
        service = self.service()
        service.auth.home.mkdir(parents=True)
        (service.auth.home / "fixture-account.json").write_text('{"type":"chatgpt","email":"test@example.com","planType":"plus"}')
        # Old API configuration stays saved, but is not used by ChatGPT turns.
        service.save_settings({"model": "old-api-model", "api_key": "old-api-key", "base_url": "http://old-api.local/v1"})
        session = service.create_session()
        await service.start(session["id"], "first")
        await asyncio.wait_for(service.task, 5)
        await service.start(session["id"], "second")
        await asyncio.wait_for(service.task, 5)
        stored = service.sessions.get(session["id"])
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["thread_id"], "official-thread")
        self.assertEqual(stored["resolved_model"], "codex-one")
        self.assertEqual(stored["model"], "")
        calls = [json.loads(line) for line in (service.auth.home / "fixture-calls.jsonl").read_text().splitlines()]
        starts = [c for c in calls if c["method"] in ("thread/start", "thread/resume")]
        self.assertEqual([s["method"] for s in starts], ["thread/start", "thread/resume"])
        self.assertTrue(all(s["params"]["model"] is None and s["params"]["modelProvider"] == "openai" for s in starts))
        startup = json.loads((service.auth.home / "fixture-start.json").read_text())
        self.assertFalse(startup["chat_key_env"])
        self.assertEqual(service.settings.value["api_key"], "old-api-key")
        self.assertNotIn("auth_identity", service.snapshot(session["id"]))

    async def test_chatgpt_model_switch_preserves_thread_and_reports_effective_model(self):
        service = self.service()
        service.auth.home.mkdir(parents=True)
        (service.auth.home / "fixture-account.json").write_text('{"type":"chatgpt","email":"test@example.com","planType":"plus"}')
        session = service.create_session()
        for model, effective in [("", "codex-one"), ("codex-two", "codex-two"), ("", "codex-one")]:
            service.save_settings({"chatgpt_model": model})
            await service.start(session["id"], "model selection test")
            await asyncio.wait_for(service.task, 5)
            snapshot = service.snapshot(session["id"])
            self.assertEqual(snapshot["status"], "completed")
            self.assertEqual(snapshot["model"], model)
            self.assertEqual(snapshot["resolved_model"], effective)
            self.assertEqual(snapshot["thread_id"], "official-thread")
        calls = [json.loads(line) for line in (service.auth.home / "fixture-calls.jsonl").read_text().splitlines()]
        starts = [c for c in calls if c["method"] in ("thread/start", "thread/resume")]
        self.assertEqual([s["method"] for s in starts], ["thread/start", "thread/resume", "thread/resume"])
        self.assertEqual([s["params"]["model"] for s in starts], [None, "codex-two", None])

    async def test_changing_account_cannot_resume_an_existing_conversation(self):
        service = self.service()
        home = service.auth.home
        home.mkdir(parents=True)
        (home / "fixture-account.json").write_text('{"type":"chatgpt","email":"first@example.com"}')
        session = service.create_session()
        await service.start(session["id"], "first")
        await asyncio.wait_for(service.task, 5)
        (home / "fixture-account.json").write_text('{"type":"chatgpt","email":"second@example.com"}')
        with self.assertRaisesRegex(ValueError, "新建会话"):
            await service.start(session["id"], "second")

    async def test_api_conversation_cannot_switch_to_account_and_resume(self):
        service = self.service()
        service.save_settings({"auth_mode": "api", "model": "api-model"})
        session = service.sessions.create(service.settings.value)
        session["items"].append({"id": "user", "role": "user", "text": "old task"})
        service.save_settings({"auth_mode": "chatgpt"})
        with self.assertRaisesRegex(ValueError, "新建会话"):
            await service.start(session["id"], "test")

    async def test_api_mode_keeps_custom_credentials_with_a_cached_chatgpt_account(self):
        service = self.service()
        home = service.auth.home
        home.mkdir(parents=True)
        (home / "fixture-account.json").write_text('{"type":"chatgpt","email":"test@example.com"}')
        service.save_settings({"auth_mode": "api", "model": "api-model", "api_key": "custom-key"})
        session = service.create_session()
        await service.start(session["id"], "api task")
        await asyncio.wait_for(service.task, 5)
        startup = json.loads((home / "fixture-start.json").read_text())
        self.assertEqual(startup["provider"], "decky")
        self.assertTrue(startup["custom_provider"])
        self.assertTrue(startup["chat_key_env"])
        calls = [json.loads(line) for line in (home / "fixture-calls.jsonl").read_text().splitlines()]
        self.assertFalse(any(call["method"] == "account/read" for call in calls))

    async def test_account_speech_refreshes_once_on_401_and_keeps_token_private(self):
        self.signed_in()
        with patch("decky_agent.auth.ChatGPTSpeechClient") as factory:
            factory.return_value.transcribe = AsyncMock(side_effect=[SpeechHTTPError(401), "voice text"])
            self.assertEqual(await self.auth.transcribe(b"audio"), "voice text")
            self.assertEqual(factory.call_args.args[0], "fixture-account-token")
        calls = [json.loads(line) for line in (self.home / "fixture-calls.jsonl").read_text().splitlines()]
        self.assertEqual([c["params"]["refreshToken"] for c in calls if c["method"] == "getAuthStatus"], [False, True])
        self.assertNotIn("fixture-account-token", json.dumps(self.auth.snapshot()))
        self.assertIsNone(self.auth.client)

    async def test_account_speech_403_is_actionable_without_leaking_credentials(self):
        self.signed_in()
        with patch("decky_agent.auth.ChatGPTSpeechClient") as factory:
            factory.return_value.transcribe = AsyncMock(side_effect=SpeechHTTPError(403))
            with self.assertRaisesRegex(ValueError, "独立语音 API") as error:
                await self.auth.transcribe(b"audio")
        self.assertNotIn("fixture-account-token", str(error.exception))
        self.assertFalse(self.auth.busy)

    async def test_plugin_close_cancels_account_upload_before_closing_auth(self):
        service = self.service()
        service.save_settings({"speech_enabled": True})
        service.auth.home.mkdir(parents=True)
        (service.auth.home / "fixture-account.json").write_text('{"type":"chatgpt","email":"test@example.com"}')
        connected = asyncio.Event()
        async def upload(*_):
            connected.set()
            await asyncio.Event().wait()
        fixture = Path(__file__).parent / "fixtures/fake_recorder.py"
        with patch("decky_agent.auth.ChatGPTSpeechClient") as factory:
            factory.return_value.transcribe = AsyncMock(side_effect=upload)
            with patch("decky_agent.speech.recorder_command", return_value=[sys.executable, str(fixture)]):
                recording = await service.start_recording(service.create_session()["id"])
            await self.wait_for(lambda: service.speech.job.path.stat().st_size > 6400)
            finish = asyncio.create_task(service.speech.finish(recording["id"]))
            await asyncio.wait_for(connected.wait(), 2)
            await asyncio.wait_for(service.close(), 2)
            with self.assertRaisesRegex(ValueError, "取消"):
                await finish
        self.assertIsNone(service.auth.client)
        self.assertFalse(service.speech.busy)

    async def test_bundled_chatgpt_turn_uses_verified_local_metadata_and_progress(self):
        catalog = Path(__file__).resolve().parents[1] / "resources/codex-models.json"
        data = catalog.read_bytes()
        digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        self.assertEqual(digest, "72a78e0eacf94103f4babda2a5245aba4ce848c1")
        bundled = self.root / "bin/codex"
        bundled.parent.mkdir()
        bundled.write_bytes(self.binary.read_bytes())
        bundled.chmod(0o755)
        local_catalog = self.root / "resources/codex-models.json"
        local_catalog.parent.mkdir()
        local_catalog.write_bytes(data)
        settings = {"auth_mode": "chatgpt", "model": "", "workspace": str(self.root), "instructions": "", "network_access": False}
        phases = []
        with patch("decky_agent.codex.PLUGIN_ROOT", self.root):
            engine = CodexEngine(settings, {"thread_id": None}, self.home, str(bundled), lambda *a, **kw: None, None, phases.append)
            await engine.run("test")
        startup = json.loads((self.home / "fixture-start.json").read_text())
        self.assertEqual(startup["catalog"], str(local_catalog))
        self.assertEqual(phases[:3], ["正在连接 Codex", "正在准备会话", "等待模型回复"])

    async def test_external_codex_does_not_receive_version_specific_catalog(self):
        settings = {"auth_mode": "chatgpt", "model": "", "workspace": str(self.root), "instructions": "", "network_access": False}
        engine = CodexEngine(settings, {"thread_id": None}, self.home, str(self.binary), lambda *a, **kw: None, None)
        await engine.run("test")
        startup = json.loads((self.home / "fixture-start.json").read_text())
        self.assertNotIn("catalog", startup)
