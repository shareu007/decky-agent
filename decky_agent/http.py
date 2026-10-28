"""Small cancellable SSE transport using aiohttp already shipped by Decky."""
import json
import ssl
from contextlib import asynccontextmanager
from pathlib import Path

CHATGPT_TRANSCRIBE_URL = "https://chatgpt.com/backend-api/transcribe"
SYSTEM_CA_FILES = (
    Path("/etc/ssl/certs/ca-certificates.crt"),
    Path("/etc/pki/tls/certs/ca-bundle.crt"),
    Path("/etc/ssl/cert.pem"),
)


class TLSVerificationError(RuntimeError):
    pass


def system_ssl_context() -> ssl.SSLContext:
    # Frozen Decky/OpenSSL builds may point at a nonexistent build-machine CA
    # path. Extend the normal trust store with the OS-managed bundle instead.
    context = ssl.create_default_context()
    for bundle in SYSTEM_CA_FILES:
        if bundle.is_file():
            context.load_verify_locations(cafile=str(bundle))
            break
    return context


@asynccontextmanager
async def http_session(**kwargs):
    import aiohttp

    connector = aiohttp.TCPConnector(ssl=system_ssl_context())
    try:
        async with aiohttp.ClientSession(connector=connector, **kwargs) as client:
            yield client
    except aiohttp.ClientSSLError:
        raise TLSVerificationError("无法验证服务的 HTTPS 证书，请检查系统证书和设备时间后重试") from None


class SpeechHTTPError(RuntimeError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"ChatGPT 语音服务返回 HTTP {status}；请检查登录状态或稍后重试")


class APIClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    async def request(self, path: str, payload: dict | None = None):
        # Lazy import lets storage, tools, and Codex run without extra packages.
        import aiohttp

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        timeout = aiohttp.ClientTimeout(total=300, connect=20, sock_read=120)
        async with http_session(timeout=timeout, headers=headers) as client:
            async with client.request(
                "POST" if payload is not None else "GET",
                self.base_url + path, json=payload, allow_redirects=False,
            ) as response:
                if response.status >= 300:
                    # Do not forward upstream bodies: proxies can echo credentials.
                    raise RuntimeError(
                        f"API 返回 HTTP {response.status}；请检查地址、密钥、模型和协议"
                    )
                if not payload or not payload.get("stream"):
                    raw = await self._body(response)
                    yield json.loads(raw)
                    return
                if "text/event-stream" not in response.headers.get("Content-Type", ""):
                    raw = await self._body(response)
                    yield json.loads(raw)
                    return
                data = []
                total = 0
                async for raw_line in response.content:
                    total += len(raw_line)
                    if total > 4 * 1024 * 1024:
                        raise RuntimeError("API 流超过 4 MiB，请缩短任务")
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        chunk = "\n".join(data)
                        data = []
                        if chunk == "[DONE]":
                            return
                        yield json.loads(chunk)
                if data:
                    chunk = "\n".join(data)
                    if chunk == "[DONE]":
                        return
                    yield json.loads(chunk)
                raise RuntimeError("API 流提前断开，未收到 [DONE]")

    @staticmethod
    async def _body(response) -> bytes:
        raw = bytearray()
        async for chunk in response.content.iter_chunked(65536):
            raw.extend(chunk)
            if len(raw) > 4 * 1024 * 1024:
                raise RuntimeError("API 响应超过 4 MiB")
        return bytes(raw)

    async def models(self) -> list[str]:
        async for result in self.request("/models"):
            return sorted({m["id"] for m in result.get("data", []) if isinstance(m.get("id"), str)})[:300]
        return []

    async def transcribe(self, audio: bytes, model: str) -> str:
        import aiohttp

        form = aiohttp.FormData()
        form.add_field("file", audio, filename="speech.wav", content_type="audio/wav")
        form.add_field("model", model)
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        timeout = aiohttp.ClientTimeout(total=120, connect=20, sock_read=90)
        async with http_session(headers=headers, timeout=timeout) as client:
            async with client.post(self.base_url + "/audio/transcriptions", data=form, allow_redirects=False) as response:
                if response.status >= 300:
                    raise RuntimeError(f"语音服务返回 HTTP {response.status}；请检查转写地址、密钥和模型")
                result = json.loads(await self._body(response))
        return self._transcript(result)

    @staticmethod
    def _transcript(result) -> str:
        text = result.get("text") if isinstance(result, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("没有识别到文字，请检查麦克风并重试")
        if len(text) > 16000:
            raise ValueError("转写文字超过 16000 字符，请缩短录音")
        return text.strip()


class ChatGPTSpeechClient:
    """Account tokens are sent only to Codex's fixed first-party dictation URL."""
    def __init__(self, token: str, account_id: str | None, user_agent: str):
        self.token, self.account_id, self.user_agent = token, account_id, user_agent

    async def transcribe(self, audio: bytes) -> str:
        import aiohttp

        form = aiohttp.FormData()
        form.add_field("file", audio, filename="audio.wav", content_type="audio/wav")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json", "User-Agent": self.user_agent}
        if self.account_id:
            headers["ChatGPT-Account-Id"] = self.account_id
        timeout = aiohttp.ClientTimeout(total=45, connect=10, sock_read=30)
        async with http_session(headers=headers, timeout=timeout) as client:
            async with client.post(CHATGPT_TRANSCRIBE_URL, data=form, allow_redirects=False) as response:
                if response.status >= 300:
                    raise SpeechHTTPError(response.status)
                result = json.loads(await APIClient._body(response))
        return APIClient._transcript(result)
