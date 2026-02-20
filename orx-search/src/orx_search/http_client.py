"""HTTP Client ported from ddgs for bypassing anti-bot protections."""

import logging
import ssl
from random import SystemRandom
from types import TracebackType
from typing import TYPE_CHECKING, Any, cast

import h2.settings
import httpcore
import httpx

if TYPE_CHECKING:
    from collections.abc import Callable


logger = logging.getLogger(__name__)
random = SystemRandom()


class Response:
    """HTTP response wrapper."""

    __slots__ = ("content", "status_code", "text", "url")

    def __init__(self, status_code: int, content: bytes, text: str, url: str) -> None:
        self.status_code = status_code
        self.content = content
        self.text = text
        self.url = url

    def json(self) -> Any:
        import json

        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP error {self.status_code}")


class HttpClient:
    """HTTP client with HTTP/2 fingerprinting randomization."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        timeout: int | None = 10,
        verify: bool | str = True,
        http2: bool = True,
    ) -> None:
        self._headers = headers
        self._proxy = proxy
        self._timeout = timeout
        self._verify = verify
        self._http2 = http2
        self.client = httpx.Client(
            headers=headers,
            proxy=proxy,
            timeout=timeout,
            verify=_get_random_ssl_context(verify=verify)
            if verify and http2
            else verify,
            follow_redirects=True,
            http2=http2,
        )

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        try:
            with Patch():
                resp = self.client.request(method, url, **kwargs)
                return Response(
                    status_code=resp.status_code,
                    content=resp.content,
                    text=resp.text,
                    url=str(resp.url),
                )
        except Exception as ex:
            # Fallback to HTTP/1.1 if H2 fails with common protocol errors
            if self._http2 and (
                "HPACK" in str(ex)
                or "ProtocolError" in str(ex)
                or "table size" in str(ex)
            ):
                logger.warning(f"H2 protocol error for {url}, falling back to HTTP/1.1")
                self._http2 = False
                self.client.close()
                self.client = httpx.Client(
                    headers=self._headers,
                    proxy=self._proxy,
                    timeout=self._timeout,
                    verify=self._verify,
                    follow_redirects=True,
                    http2=False,
                )
                return self.request(method, url, **kwargs)
            raise RuntimeError(f"Request failed: {ex}") from ex

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def set_cookies(self, domain: str, cookies: dict[str, str]) -> None:
        """Set cookies for a specific domain on the underlying httpx client."""
        for name, value in cookies.items():
            self.client.cookies.set(name, value, domain=domain)


class AsyncHttpClient:
    """Async HTTP client with HTTP/2 fingerprinting randomization."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        timeout: int | None = 10,
        verify: bool | str = True,
        http2: bool = True,
    ) -> None:
        self._headers = headers
        self._proxy = proxy
        self._timeout = timeout
        self._verify = verify
        self._http2 = http2
        self.client = httpx.AsyncClient(
            headers=headers,
            proxy=proxy,
            timeout=timeout,
            verify=_get_random_ssl_context(verify=verify)
            if verify and http2
            else verify,
            follow_redirects=True,
            http2=http2,
        )

    async def request(self, method: str, url: str, **kwargs: Any) -> Response:
        try:
            async with AsyncPatch():
                resp = await self.client.request(method, url, **kwargs)
                return Response(
                    status_code=resp.status_code,
                    content=resp.content,
                    text=resp.text,
                    url=str(resp.url),
                )
        except Exception as ex:
            # Fallback to HTTP/1.1 if H2 fails with common protocol errors
            if self._http2 and (
                "HPACK" in str(ex)
                or "ProtocolError" in str(ex)
                or "table size" in str(ex)
            ):
                logger.warning(
                    f"Async H2 protocol error for {url}, falling back to HTTP/1.1"
                )
                self._http2 = False
                await self.client.aclose()
                self.client = httpx.AsyncClient(
                    headers=self._headers,
                    proxy=self._proxy,
                    timeout=self._timeout,
                    verify=self._verify,
                    follow_redirects=True,
                    http2=False,
                )
                return await self.request(method, url, **kwargs)
            raise RuntimeError(f"Async request failed: {ex}") from ex

    async def get(self, url: str, **kwargs: Any) -> Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Response:
        return await self.request("POST", url, **kwargs)

    def set_cookies(self, domain: str, cookies: dict[str, str]) -> None:
        """Set cookies for a specific domain on the underlying httpx client."""
        for name, value in cookies.items():
            self.client.cookies.set(name, value, domain=domain)

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self.client.aclose()


# SSL Constants from ddgs
DEFAULT_CIPHERS = [
    "TLS_AES_128_GCM_SHA256",
    "TLS_AES_256_GCM_SHA384",
    "TLS_CHACHA20_POLY1305_SHA256",
    # Modern:
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-ECDSA-CHACHA20-POLY1305",
    "ECDHE-RSA-AES128-GCM-SHA256",
    "ECDHE-RSA-CHACHA20-POLY1305",
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
    # Compatible:
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-ECDSA-CHACHA20-POLY1305",
    "ECDHE-RSA-AES128-GCM-SHA256",
    "ECDHE-RSA-CHACHA20-POLY1305",
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "ECDHE-ECDSA-AES128-SHA256",
    "ECDHE-RSA-AES128-SHA256",
    "ECDHE-ECDSA-AES256-SHA384",
    "ECDHE-RSA-AES256-SHA384",
    # Legacy:
    "ECDHE-ECDSA-AES128-SHA",
    "ECDHE-RSA-AES128-SHA",
    "AES128-GCM-SHA256",
    "AES128-SHA256",
    "AES128-SHA",
    "ECDHE-RSA-AES256-SHA",
    "AES256-GCM-SHA384",
    "AES256-SHA256",
    "AES256-SHA",
    "DES-CBC3-SHA",
]


def _get_random_ssl_context(*, verify: bool | str) -> ssl.SSLContext:
    ssl_context = ssl.create_default_context(
        cafile=verify if isinstance(verify, str) else None
    )
    try:
        shuffled_ciphers = random.sample(DEFAULT_CIPHERS[9:], len(DEFAULT_CIPHERS) - 9)
        ssl_context.set_ciphers(":".join(DEFAULT_CIPHERS[:9] + shuffled_ciphers))
    except Exception:
        # Fallback if cipher setting fails
        pass

    commands: list[None | Callable[[ssl.SSLContext], None]] = [
        None,
        lambda context: setattr(context, "maximum_version", ssl.TLSVersion.TLSv1_2),
        lambda context: setattr(context, "minimum_version", ssl.TLSVersion.TLSv1_3),
        lambda context: setattr(context, "options", context.options | ssl.OP_NO_TICKET),
    ]
    random_command = random.choice(commands)
    if random_command:
        random_command(ssl_context)
    return ssl_context


class Patch:
    """Patch the HTTP2Connection._send_connection_init method."""

    def __init__(self) -> None:
        self._connection_cls: Any | None = None
        self.original_send_connection_init: Any | None = None

    def __enter__(self) -> None:
        def _send_connection_init(self: Any, request: Any) -> None:
            self._h2_state.local_settings = h2.settings.Settings(
                client=True,
                initial_values={
                    h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: random.randint(
                        65535, 131072
                    ),
                    h2.settings.SettingCodes.HEADER_TABLE_SIZE: random.randint(
                        32768, 65536
                    ),
                    h2.settings.SettingCodes.MAX_FRAME_SIZE: random.randint(
                        16384, 16777215
                    ),
                    h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: random.randint(
                        100, 1000
                    ),
                    h2.settings.SettingCodes.MAX_HEADER_LIST_SIZE: random.randint(
                        131072, 262144
                    ),
                    h2.settings.SettingCodes.ENABLE_CONNECT_PROTOCOL: random.randint(
                        0, 1
                    ),
                    h2.settings.SettingCodes.ENABLE_PUSH: random.randint(0, 1),
                },
            )
            self._h2_state.initiate_connection()
            self._h2_state.increment_flow_control_window(2**24)
            self._write_outgoing_data(request)

        sync_mod = cast(Any, httpcore._sync)
        self._connection_cls = cast(Any, sync_mod.http2.HTTP2Connection)
        self.original_send_connection_init = self._connection_cls._send_connection_init
        self._connection_cls._send_connection_init = _send_connection_init

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: TracebackType | None = None,
    ) -> None:
        if self._connection_cls is not None and self.original_send_connection_init:
            self._connection_cls._send_connection_init = (
                self.original_send_connection_init
            )


class AsyncPatch:
    """Patch the AsyncHTTP2Connection._send_connection_init method."""

    def __init__(self) -> None:
        self._connection_cls: Any | None = None
        self.original_send_connection_init: Any | None = None

    async def __aenter__(self) -> None:
        async def _send_connection_init(self: Any, request: Any) -> None:
            self._h2_state.local_settings = h2.settings.Settings(
                client=True,
                initial_values={
                    h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: random.randint(
                        65535, 131072
                    ),
                    h2.settings.SettingCodes.HEADER_TABLE_SIZE: random.randint(
                        32768, 65536
                    ),
                    h2.settings.SettingCodes.MAX_FRAME_SIZE: random.randint(
                        16384, 16777215
                    ),
                    h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: random.randint(
                        100, 1000
                    ),
                    h2.settings.SettingCodes.MAX_HEADER_LIST_SIZE: random.randint(
                        131072, 262144
                    ),
                    h2.settings.SettingCodes.ENABLE_CONNECT_PROTOCOL: random.randint(
                        0, 1
                    ),
                    h2.settings.SettingCodes.ENABLE_PUSH: random.randint(0, 1),
                },
            )
            self._h2_state.initiate_connection()
            self._h2_state.increment_flow_control_window(2**24)
            self._write_outgoing_data(request)

        async_mod = cast(Any, httpcore._async)
        self._connection_cls = cast(Any, async_mod.http2.AsyncHTTP2Connection)
        self.original_send_connection_init = self._connection_cls._send_connection_init
        self._connection_cls._send_connection_init = _send_connection_init

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: TracebackType | None = None,
    ) -> None:
        if self._connection_cls is not None and self.original_send_connection_init:
            self._connection_cls._send_connection_init = (
                self.original_send_connection_init
            )
