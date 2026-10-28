"""Regress frozen runtimes with missing OpenSSL default trust paths."""
import shutil
import asyncio
import ssl
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from decky_agent.http import APIClient, ChatGPTSpeechClient

try:
    from aiohttp import web
except ImportError:
    web = None


@unittest.skipIf(web is None or not shutil.which("openssl"), "Requires aiohttp and openssl")
class SystemTrustTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()

        def expected_rejected_handshake(loop, context):
            if (context.get("message") == "Error on transport creation for incoming connection"
                    and isinstance(context.get("exception"), (ConnectionResetError, ssl.SSLError))):
                return
            if previous_handler:
                previous_handler(loop, context)
            else:
                loop.default_exception_handler(context)

        loop.set_exception_handler(expected_rejected_handshake)
        self.addCleanup(loop.set_exception_handler, previous_handler)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.cert, key = root / "ca.pem", root / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-keyout", str(key), "-out", str(self.cert), "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost", "-addext", "basicConstraints=critical,CA:TRUE"],
                       check=True, capture_output=True)
        app = web.Application()

        async def reply(request):
            if request.method == "POST":
                await request.read()
            return web.json_response({"data": [{"id": "trusted-model"}], "text": "trusted speech"})

        app.router.add_route("*", "/{tail:.*}", reply)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.addAsyncCleanup(self.runner.cleanup)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(self.cert, key)
        site = web.TCPSite(self.runner, "127.0.0.1", 0, ssl_context=server_context)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        self.base = f"https://localhost:{self.port}"

    async def test_all_http_clients_use_system_trust_when_default_paths_are_missing(self):
        # Empty defaults reproduce Decky's frozen OpenSSL environment. The local
        # CA stands in for Bazzite's /etc/ssl/certs/ca-certificates.crt.
        empty_defaults = lambda: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with patch("decky_agent.http.SYSTEM_CA_FILES", (self.cert,), create=True), \
                patch("ssl.create_default_context", side_effect=empty_defaults), \
                patch("decky_agent.http.CHATGPT_TRANSCRIBE_URL", self.base + "/transcribe"):
            client = APIClient(self.base, "test-key")
            self.assertEqual(await client.models(), ["trusted-model"])
            self.assertEqual(await client.transcribe(b"test-audio", "test-model"), "trusted speech")
            self.assertEqual(await ChatGPTSpeechClient("test-token", None, "test-agent").transcribe(b"test-audio"), "trusted speech")

    async def test_system_trust_still_rejects_wrong_hostname_and_untrusted_certificates(self):
        with patch("decky_agent.http.SYSTEM_CA_FILES", (self.cert,), create=True):
            # The certificate is trusted, but only for localhost.
            with self.assertRaisesRegex(RuntimeError, "证书"):
                await APIClient(f"https://127.0.0.1:{self.port}", "").models()
        with patch("decky_agent.http.SYSTEM_CA_FILES", (), create=True):
            with self.assertRaisesRegex(RuntimeError, "证书"):
                await APIClient(self.base, "").models()
