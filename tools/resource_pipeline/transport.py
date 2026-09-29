"""Host-restricted, secret-safe HTTP transport for content discovery."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Callable, Mapping


SENSITIVE_HEADER_FRAGMENTS = (
    "authorization",
    "cookie",
    "token",
    "device-id",
    "deviceid",
    "signature",
    "api-key",
    "apikey",
)
SENSITIVE_QUERY_FRAGMENTS = (
    "authorization",
    "cookie",
    "token",
    "device",
    "signature",
    "password",
    "secret",
)


class TransportError(RuntimeError):
    """A sanitized transport failure safe for logs and checkpoints."""


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None

    def __post_init__(self) -> None:
        if self.method.upper() not in {"GET", "HEAD", "POST"}:
            raise ValueError("unsupported HTTP method")
        if not self.url.strip():
            raise ValueError("request URL cannot be empty")


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class DownloadReceipt:
    status: int
    headers: Mapping[str, str]
    byte_size: int


class _AllowedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]):
        super().__init__()
        self._allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        host = (urllib.parse.urlsplit(new_url).hostname or "").lower()
        scheme = urllib.parse.urlsplit(new_url).scheme.lower()
        if scheme not in {"http", "https"} or host not in self._allowed_hosts:
            raise urllib.error.URLError("redirect host is not allowed")
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


class HttpTransport:
    def __init__(
        self,
        *,
        allowed_hosts: tuple[str, ...],
        connect_timeout_seconds: int,
        read_timeout_seconds: int,
        max_response_bytes: int,
        sender: Callable[[urllib.request.Request, float], Any] | None = None,
    ):
        normalized_hosts = frozenset(host.lower().strip() for host in allowed_hosts)
        if not normalized_hosts or "" in normalized_hosts:
            raise ValueError("allowed_hosts cannot be empty")
        if connect_timeout_seconds <= 0 or read_timeout_seconds <= 0:
            raise ValueError("HTTP timeouts must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._allowed_hosts = normalized_hosts
        self._connect_timeout = connect_timeout_seconds
        self._read_timeout = read_timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._tls_context = ssl.create_default_context()
        if sender is None:
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=self._tls_context),
                _AllowedRedirectHandler(self._allowed_hosts),
            )
            self._sender = lambda request, timeout: opener.open(
                request,
                timeout=timeout,
            )
        else:
            self._sender = sender

    @property
    def tls_verification_enabled(self) -> bool:
        return (
            self._tls_context.check_hostname
            and self._tls_context.verify_mode == ssl.CERT_REQUIRED
        )

    def request(self, request: HttpRequest) -> HttpResponse:
        response = self._send(request)
        with response:
            body = response.read(self._max_response_bytes + 1)
            if len(body) > self._max_response_bytes:
                raise TransportError(
                    f"HTTP response exceeded size limit for {self._safe_url(request.url)}"
                )
            return HttpResponse(
                status=response.status,
                headers=self._response_headers(response),
                body=body,
            )

    def download(self, request: HttpRequest, output: BinaryIO) -> DownloadReceipt:
        response = self._send(request)
        byte_size = 0
        with response:
            while True:
                chunk = response.read(min(1024 * 1024, self._max_response_bytes + 1))
                if not chunk:
                    break
                byte_size += len(chunk)
                if byte_size > self._max_response_bytes:
                    raise TransportError(
                        "HTTP download exceeded size limit for "
                        f"{self._safe_url(request.url)}"
                    )
                output.write(chunk)
            return DownloadReceipt(
                status=response.status,
                headers=self._response_headers(response),
                byte_size=byte_size,
            )

    def safe_request_summary(self, request: HttpRequest) -> dict[str, Any]:
        return {
            "method": request.method.upper(),
            "url": self._safe_url(request.url),
            "headers": {
                name: (
                    "REDACTED" if self._sensitive_header(name) else value
                )
                for name, value in request.headers.items()
            },
        }

    def _send(self, request: HttpRequest) -> Any:
        parsed = urllib.parse.urlsplit(request.url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() not in {"http", "https"}:
            raise TransportError("HTTP request scheme is not allowed")
        if host not in self._allowed_hosts:
            raise TransportError(f"HTTP host is not allowed: {host or '<missing>'}")
        raw_request = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method.upper(),
        )
        try:
            timeout = float(min(self._connect_timeout, self._read_timeout))
            return self._sender(raw_request, timeout)
        except urllib.error.HTTPError as response:
            return response
        except Exception:
            raise TransportError(
                f"HTTP request failed for {self._safe_url(request.url)}"
            ) from None

    @staticmethod
    def _response_headers(response: Any) -> dict[str, str]:
        return {name.lower(): value for name, value in response.headers.items()}

    @staticmethod
    def _sensitive_header(name: str) -> bool:
        normalized = name.lower().replace("_", "-")
        return any(fragment in normalized for fragment in SENSITIVE_HEADER_FRAGMENTS)

    @staticmethod
    def _safe_url(url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        safe_query = urllib.parse.urlencode(
            [
                (
                    name,
                    "REDACTED"
                    if any(
                        fragment in name.lower()
                        for fragment in SENSITIVE_QUERY_FRAGMENTS
                    )
                    else value,
                )
                for name, value in urllib.parse.parse_qsl(
                    parsed.query,
                    keep_blank_values=True,
                )
            ]
        )
        hostname = parsed.hostname or ""
        authority = hostname
        if parsed.port is not None:
            authority = f"{authority}:{parsed.port}"
        return urllib.parse.urlunsplit(
            (parsed.scheme, authority, parsed.path, safe_query, "")
        )
