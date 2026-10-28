import asyncio
import json
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

from decky_agent.http import APIClient, ChatGPTSpeechClient, SpeechHTTPError
from decky_agent.service import AgentService
from decky_agent.storage import SessionStore

try:
    from aiohttp import web
except ImportError:
    web = None


@unittest.skipIf(web is None, "安装 requirements-dev.txt 后运行 HTTP 集成测试")
class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        self.auth = None
        self.payload = None
        self.connected = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.speech_fields = {}
        self.account_headers = {}
        self.account_status = 200

        async def models(request):
            self.auth = request.headers.get("Authorization")
            return web.json_response({"data": [{"id": "local-model"}]})

        async def stream(request):
            self.payload = await request.json()
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            if (self.payload.get("messages") or [{}])[-1].get("content") == "write a file":
                event = {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "write-1", "type": "function", "function": {
                    "name": "write_file", "arguments": '{"path":"created.txt","content":"created"}',
                }}]}, "finish_reason": "tool_calls"}]}
                chunks = [("data: " + json.dumps(event) + "\n\n").encode(), b'data: [DONE]\n\n']
            else:
                chunks = [b': ping\r\n', b'data: {"choices":', b'[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\r\n\r\n', b'data: [DONE]\n\n']
            for chunk in chunks:
                await response.write(chunk)
            await response.write_eof()
            return response

        async def fail(request):
            return web.Response(status=401, text="echo secret-key")

        async def redirect(request):
            raise web.HTTPTemporaryRedirect(location="/models")

        async def broken(request):
            return web.Response(body='data: {"choices": []}\n\n', content_type="text/event-stream")

        async def slow(request):
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            await response.write(b'data: {"choices": []}\n\n')
            self.connected.set()
            for _ in range(200):
                if request.transport is None or request.transport.is_closing():
                    self.disconnected.set()
                    break
                await asyncio.sleep(.01)
            return response

        async def transcribe(request):
            self.auth = request.headers.get("Authorization")
            reader = await request.multipart()
            while part := await reader.next():
                if part.name == "file":
                    self.speech_fields["file"] = bytes(await part.read())
                    self.speech_fields["filename"] = part.filename
                    self.speech_fields["content_type"] = part.headers.get("Content-Type")
                else:
                    self.speech_fields[part.name] = await part.text()
            if self.speech_fields["model"] == "redirect":
                raise web.HTTPTemporaryRedirect(location="https://untrusted.invalid/upload")
            if self.speech_fields["model"] == "denied":
                return web.Response(status=401, text="echo secret-key")
            return web.json_response({"text": "" if self.speech_fields["model"] == "empty" else "你好，Steam Deck"})

        async def account_transcribe(request):
            self.account_headers = {key: request.headers.get(key) for key in ("Authorization", "ChatGPT-Account-Id", "User-Agent")}
            reader = await request.multipart()
            self.speech_fields = {}
            while part := await reader.next():
                self.speech_fields[part.name] = bytes(await part.read())
            if self.account_status != 200:
                return web.Response(status=self.account_status, text="echo account-secret")
            return web.json_response({"text": "账号语音"})

        app.router.add_get("/v1/models", models)
        app.router.add_post("/v1/chat/completions", stream)
        app.router.add_get("/v1/fail", fail)
        app.router.add_get("/v1/redirect", redirect)
        app.router.add_post("/v1/broken", broken)
        app.router.add_post("/v1/slow", slow)
        app.router.add_post("/v1/audio/transcriptions", transcribe)
        app.router.add_post("/chatgpt/transcribe", account_transcribe)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.client = APIClient(f"http://127.0.0.1:{port}/v1", "secret-key")
        self.account_endpoint = f"http://127.0.0.1:{port}/chatgpt/transcribe"

    async def asyncTearDown(self):
        await self.runner.cleanup()

    async def test_models_with_authorization(self):
        self.assertEqual(await self.client.models(), ["local-model"])
        self.assertEqual(self.auth, "Bearer secret-key")

    async def test_sse_handles_split_network_chunks_and_crlf(self):
        chunks = [chunk async for chunk in self.client.request("/chat/completions", {"stream": True, "model": "custom"})]
        self.assertEqual(chunks[0]["choices"][0]["delta"]["content"], "ok")
        self.assertEqual(self.payload["model"], "custom")

    async def test_errors_do_not_echo_response_secrets(self):
        with self.assertRaisesRegex(RuntimeError, "HTTP 401") as context:
            async for _ in self.client.request("/fail"):
                pass
        self.assertNotIn("secret-key", str(context.exception))

    async def test_redirect_does_not_forward_key(self):
        with self.assertRaisesRegex(RuntimeError, "HTTP 307"):
            async for _ in self.client.request("/redirect"):
                pass

    async def test_broken_stream_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, "提前断开"):
            async for _ in self.client.request("/broken", {"stream": True}):
                pass

    async def test_cancel_closes_stream_connection(self):
        async def read():
            async for _ in self.client.request("/slow", {"stream": True}):
                pass

        task = asyncio.create_task(read())
        await asyncio.wait_for(self.connected.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(self.disconnected.wait(), 2)

    async def test_full_configuration_task_approval_and_persisted_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = AgentService(root / "settings", root / "data", root, root)
            service.save_settings({**service.settings.public(), "engine": "compatible",
                                   "base_url": self.client.base_url, "api_key": "local-test-key", "model": "local-test-model"})
            session = service.create_session()
            await service.start(session["id"], "write a file")
            try:
                async def wait_for_approval():
                    while not service.snapshot(session["id"])["pending"]:
                        if service.task.done():
                            self.fail(str(service.snapshot(session["id"])))
                        await asyncio.sleep(.01)
                await asyncio.wait_for(wait_for_approval(), 2)
                pending = service.snapshot(session["id"])["pending"][0]
                service.respond(session["id"], pending["id"], True)
                await asyncio.wait_for(service.task, 2)
                final = service.snapshot(session["id"])
                self.assertEqual(final["status"], "completed")
                self.assertIsNone(service.bootstrap()["active_id"])
                self.assertEqual((Path(final["workspace"]) / "created.txt").read_text(), "created")
                restored = SessionStore(root / "data" / "sessions").get(session["id"])
                self.assertEqual(restored["messages"][-1]["content"], "ok")
                self.assertTrue(any(message.get("tool_call_id") == "write-1" for message in restored["messages"]))
            finally:
                await service.close()

    async def test_audio_transcription_uploads_multipart_with_filename_and_model(self):
        text = await self.client.transcribe(b"RIFF-test-audio", "custom-transcribe")
        self.assertEqual(text, "你好，Steam Deck")
        self.assertEqual(self.speech_fields["file"], b"RIFF-test-audio")
        self.assertEqual(self.speech_fields["filename"], "speech.wav")
        self.assertEqual(self.speech_fields["content_type"], "audio/wav")
        self.assertEqual(self.speech_fields["model"], "custom-transcribe")
        self.assertEqual(self.auth, "Bearer secret-key")

    async def test_audio_errors_empty_results_and_redirects_are_rejected(self):
        for model, error in [("denied", "HTTP 401"), ("redirect", "HTTP 307"), ("empty", "没有识别到")]:
            with self.subTest(model=model), self.assertRaisesRegex((RuntimeError, ValueError), error) as result:
                await self.client.transcribe(b"RIFF-test", model)
            self.assertNotIn("secret-key", str(result.exception))

    async def test_chatgpt_audio_uses_fixed_account_endpoint_without_api_model(self):
        with patch("decky_agent.http.CHATGPT_TRANSCRIBE_URL", self.account_endpoint):
            result = await ChatGPTSpeechClient("account-secret", "account-id", "codex-test").transcribe(b"RIFF-audio")
        self.assertEqual(result, "账号语音")
        self.assertEqual(self.speech_fields, {"file": b"RIFF-audio"})
        self.assertEqual(self.account_headers, {"Authorization": "Bearer account-secret", "ChatGPT-Account-Id": "account-id", "User-Agent": "codex-test"})

    async def test_chatgpt_audio_errors_and_redirects_do_not_echo_or_forward_tokens(self):
        for status in (401, 403, 307):
            self.account_status = status
            with patch("decky_agent.http.CHATGPT_TRANSCRIBE_URL", self.account_endpoint):
                with self.assertRaises(SpeechHTTPError) as result:
                    await ChatGPTSpeechClient("account-secret", None, "codex-test").transcribe(b"audio")
            self.assertEqual(result.exception.status, status)
            self.assertNotIn("account-secret", str(result.exception))

    async def test_native_recording_to_real_multipart_api_without_microphone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = AgentService(root / "settings", root / "data", root, root)
            service.save_settings({"speech_enabled": True, "speech_base_url": self.client.base_url,
                                   "speech_api_key": "speech-token", "speech_model": "test-transcribe"})
            fixture = Path(__file__).parent / "fixtures" / "fake_recorder.py"
            try:
                session = service.create_session()
                with patch("decky_agent.speech.recorder_command", return_value=[sys.executable, str(fixture)]):
                    recording = await service.start_recording(session["id"])
                async def wait_for_audio():
                    while service.speech.job.path.stat().st_size < 6400:
                        await asyncio.sleep(.01)
                await asyncio.wait_for(wait_for_audio(), 2)
                text = await service.speech.finish(recording["id"])
                self.assertEqual(text, "你好，Steam Deck")
                self.assertEqual(self.speech_fields["file"][:4], b"RIFF")
                self.assertEqual(self.auth, "Bearer speech-token")
                self.assertFalse(service.speech.busy)
                self.assertEqual(list((root / "data" / "speech").glob("*.wav")), [])
            finally:
                await service.close()
