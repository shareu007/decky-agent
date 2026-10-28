import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from decky_agent.service import AgentService
from decky_agent.speech import SpeechInput
from decky_agent.storage import SettingsStore


class SpeechTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.speech = SpeechInput(self.root / "audio")
        self.addAsyncCleanup(self.speech.close)
        self.settings = SettingsStore(self.root / "settings.json", self.root).value
        self.settings["speech_enabled"] = True
        fixture = Path(__file__).parent / "fixtures" / "fake_recorder.py"
        self.command = [sys.executable, str(fixture)]
        self.recorder = patch("decky_agent.speech.recorder_command", return_value=self.command)
        self.recorder.start()
        self.addCleanup(self.recorder.stop)
        self.api = patch("decky_agent.speech.APIClient")
        self.factory = self.api.start()
        self.addCleanup(self.api.stop)
        self.client = self.factory.return_value
        self.client.transcribe = AsyncMock(return_value="你好，检查当前项目。")

    async def wait_for(self, predicate):
        async def poll():
            while not predicate():
                await asyncio.sleep(.01)
        await asyncio.wait_for(poll(), 3)

    async def start(self):
        status = await self.speech.start("session", self.settings)
        await self.wait_for(lambda: self.speech.job.path.stat().st_size > 6400)
        return status

    async def test_record_transcribe_cleanup_and_private_file(self):
        status = await self.start()
        path = self.speech.job.path
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        text = await self.speech.finish(status["id"])
        self.assertEqual(text, "你好，检查当前项目。")
        self.assertFalse(self.speech.busy)
        self.assertFalse(path.exists())
        audio, model = self.client.transcribe.call_args.args
        self.assertEqual(audio[:4], b"RIFF")
        self.assertEqual(model, "gpt-transcribe")

    async def test_chatgpt_mode_uses_account_transcriber_without_an_api_key_or_model(self):
        self.settings.update({"auth_mode": "chatgpt", "speech_model": "", "api_key": "old-api-key"})
        self.speech.account_transcribe = AsyncMock(return_value="账号语音已识别")
        status = await self.start()
        text = await self.speech.finish(status["id"])
        self.assertEqual(text, "账号语音已识别")
        self.speech.account_transcribe.assert_awaited_once()
        self.factory.assert_not_called()
        self.assertFalse(self.speech.busy)

    async def test_custom_speech_endpoint_does_not_receive_account_credentials(self):
        self.settings.update({"auth_mode": "chatgpt", "speech_base_url": "https://speech.test/v1", "speech_api_key": "speech-key"})
        self.speech.account_transcribe = AsyncMock(return_value="must not run")
        status = await self.start()
        await self.speech.finish(status["id"])
        self.speech.account_transcribe.assert_not_called()
        self.factory.assert_called_once_with("https://speech.test/v1", "speech-key")

    async def test_separate_url_never_inherits_chat_key(self):
        self.settings.update({"api_key": "chat-secret", "speech_base_url": "http://speech.local/v1", "speech_api_key": ""})
        status = await self.start()
        await self.speech.finish(status["id"])
        self.factory.assert_called_once_with("http://speech.local/v1", "")

    async def test_reused_url_uses_chat_credentials(self):
        self.settings["api_key"] = "chat-secret"
        status = await self.start()
        await self.speech.finish(status["id"])
        self.factory.assert_called_once_with(self.settings["base_url"], "chat-secret")

    async def test_cancel_stops_process_without_uploading_audio(self):
        status = await self.start()
        job = self.speech.job
        await self.speech.cancel(status["id"])
        self.assertIsNotNone(job.process.returncode)
        self.assertFalse(job.path.exists())
        self.assertFalse(self.speech.busy)
        self.client.transcribe.assert_not_called()

    async def test_cancel_during_transcription_cancels_upload(self):
        connected = asyncio.Event()

        async def pending(*_):
            connected.set()
            await asyncio.Event().wait()

        self.client.transcribe.side_effect = pending
        status = await self.start()
        finish = asyncio.create_task(self.speech.finish(status["id"]))
        await asyncio.wait_for(connected.wait(), 2)
        await self.speech.cancel(status["id"])
        with self.assertRaisesRegex(ValueError, "已取消"):
            await finish
        self.assertEqual(list((self.root / "audio").glob("*.wav")), [])
        self.assertFalse(self.speech.busy)

    async def test_duplicate_finish_does_not_cancel_original_upload(self):
        connected = asyncio.Event()
        release = asyncio.Event()

        async def pending(*_):
            connected.set()
            await release.wait()
            return "first transcript"

        self.client.transcribe.side_effect = pending
        status = await self.start()
        first = asyncio.create_task(self.speech.finish(status["id"]))
        await asyncio.wait_for(connected.wait(), 2)
        with self.assertRaisesRegex(ValueError, "正在转写"):
            await self.speech.finish(status["id"])
        self.assertFalse(first.done())
        release.set()
        self.assertEqual(await first, "first transcript")

    async def test_duration_limit_stops_capture_and_expires_without_upload(self):
        with patch("decky_agent.speech.MAX_SECONDS", .05):
            await self.speech.start("session", self.settings)
            await self.wait_for(lambda: self.speech.job.state == "ready")
        job = self.speech.job
        self.assertIsNotNone(job.process.returncode)
        self.client.transcribe.assert_not_called()
        job.expires = time.monotonic() - 1
        await self.wait_for(lambda: not self.speech.busy)
        self.assertFalse(job.path.exists())

    async def test_recorder_failure_is_visible_and_cleaned_up(self):
        with patch("decky_agent.speech.recorder_command", return_value=self.command + ["--fail"]):
            status = await self.speech.start("session", self.settings)
        await self.wait_for(lambda: self.speech.job.state == "failed")
        with self.assertRaisesRegex(ValueError, "录音失败"):
            await self.speech.finish(status["id"])
        self.assertFalse(self.speech.busy)
        self.client.transcribe.assert_not_called()

    async def test_pipewire_exit_one_after_requested_stop_accepts_complete_wav(self):
        with patch("decky_agent.speech.recorder_command", return_value=self.command + ["--exit-one"]):
            status = await self.start()
        job = self.speech.job
        self.assertEqual(await self.speech.finish(status["id"]), "你好，检查当前项目。")
        self.assertEqual(job.process.returncode, 1)
        self.assertFalse(job.path.exists())

    async def test_exit_one_with_empty_audio_is_not_uploaded(self):
        with patch("decky_agent.speech.recorder_command", return_value=self.command + ["--exit-one", "--empty"]):
            status = await self.speech.start("session", self.settings)
        await self.wait_for(lambda: self.speech.job.path.stat().st_size >= 44)
        with self.assertRaises(ValueError):
            await self.speech.finish(status["id"])
        self.client.transcribe.assert_not_called()
        self.assertFalse(self.speech.busy)

    async def test_exit_one_with_truncated_audio_is_not_uploaded(self):
        with patch("decky_agent.speech.recorder_command", return_value=self.command + ["--exit-one", "--truncate"]):
            status = await self.start()
        with self.assertRaisesRegex(ValueError, "不完整"):
            await self.speech.finish(status["id"])
        self.client.transcribe.assert_not_called()
        self.assertFalse(self.speech.busy)

    async def test_exit_one_without_requested_stop_is_failure_even_with_valid_audio(self):
        with patch("decky_agent.speech.recorder_command", return_value=self.command + ["--exit-one", "--exit-early"]):
            status = await self.speech.start("session", self.settings)
        await self.wait_for(lambda: self.speech.job.process.returncode is not None)
        with self.assertRaisesRegex(ValueError, "录音失败"):
            await self.speech.finish(status["id"])
        self.client.transcribe.assert_not_called()

    async def test_disabled_or_missing_recorder_never_starts_capture(self):
        with self.assertRaisesRegex(ValueError, "启用"):
            await self.speech.start("session", {**self.settings, "speech_enabled": False})
        with patch("decky_agent.speech.recorder_command", return_value=None):
            with self.assertRaisesRegex(ValueError, "未找到"):
                await self.speech.start("session", self.settings)
        self.assertFalse(self.speech.busy)

    async def test_wrong_ticket_cannot_finish_or_cancel_recording(self):
        status = await self.start()
        with self.assertRaises(ValueError):
            await self.speech.finish("wrong-ticket")
        await self.speech.cancel("wrong-ticket")
        self.assertTrue(self.speech.busy)
        await self.speech.cancel(status["id"])

    async def test_upload_failure_always_removes_audio(self):
        self.client.transcribe.side_effect = RuntimeError("HTTP 401")
        status = await self.start()
        path = self.speech.job.path
        with self.assertRaisesRegex(RuntimeError, "401"):
            await self.speech.finish(status["id"])
        self.assertFalse(path.exists())
        self.assertFalse(self.speech.busy)

    async def test_recording_blocks_task_settings_and_owned_session_deletion(self):
        service = AgentService(self.root / "config", self.root / "data", self.root, self.root)
        service.save_settings({"speech_enabled": True, "model": "custom"})
        session = service.create_session()
        try:
            await service.start_recording(session["id"])
            with self.assertRaisesRegex(ValueError, "语音"):
                await service.start(session["id"], "task")
            with self.assertRaisesRegex(ValueError, "录音"):
                service.save_settings({"model": "other"})
            with self.assertRaisesRegex(ValueError, "语音"):
                service.delete_session(session["id"])
        finally:
            await service.close()
