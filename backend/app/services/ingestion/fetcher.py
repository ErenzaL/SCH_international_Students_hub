"""Guarded HTTP fetcher: SSRF checks on every hop, robots.txt, size/time limits, safe TLS."""
from __future__ import annotations

import logging
import ssl
import time
from collections.abc import Callable, Sequence
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.core.config import Settings
from app.core.errors import UrlNotAllowed
from app.models.domain import FetchResult
from app.security.url_guard import Resolver, default_resolver, validate_fetch_url
from app.services.ingestion.errors import FetchError

log = logging.getLogger("app.fetch")
REDIRECT_CODES = {301, 302, 303, 307, 308}
ROBOTS_TTL_SECONDS = 6 * 3600   # long-running monitoring re-reads robots.txt, so a new "Disallow" is respected
HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
PDF_TYPES = ("application/pdf",)
OCTET_TYPES = ("application/octet-stream", "binary/octet-stream", "application/force-download", "application/x-download")
# error codes meaning "the site refuses automated access" (source status becomes 'blocked'; never bypassed)
BLOCKED_CODES = {"robots_disallowed", "http_401", "http_403", "http_406", "http_429"}
BLOCK_HINT = (
    " The site refused automated access; the platform does not bypass access restrictions, captchas or "
    "authentication. Import the official content manually (Knowledge Sources > Submit text / Upload)."
)


class GuardedFetcher:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver = default_resolver,
        domains: Callable[[], Sequence[str]] | None = None,
    ):
        self.settings = settings
        self.resolver = resolver
        # allowlist provider: environment defaults + admin-managed domains (see services/domains.py)
        self.domains: Callable[[], Sequence[str]] = domains or (lambda: settings.allowed_domains)
        self._transport = transport
        self._robots: dict[str, tuple[float, RobotFileParser | None]] = {}

    # -- internals ---------------------------------------------------------
    def _client(self, accept_language: str = "ko,en;q=0.5") -> httpx.Client:
        s = self.settings
        return httpx.Client(
            transport=self._transport,
            follow_redirects=False,  # we follow manually so each hop is re-validated
            verify=True,  # never disabled: invalid certificates are reported, not bypassed
            timeout=httpx.Timeout(s.fetch_timeout_seconds, connect=10.0),
            headers={
                "User-Agent": s.fetch_user_agent,
                "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.8,*/*;q=0.5",
                "Accept-Language": accept_language,
            },
        )

    def _get(self, client: httpx.Client, url: str, *, max_bytes: int) -> FetchResult:
        s = self.settings
        redirects: list[str] = []
        current = url
        for _hop in range(s.max_redirects + 1):
            try:
                validate_fetch_url(current, self.domains(), self.resolver)
                with client.stream("GET", current) as resp:
                    if resp.status_code in REDIRECT_CODES:
                        loc = resp.headers.get("location")
                        if not loc:
                            raise FetchError("bad_redirect", "Redirect response without a Location header.")
                        current_next = urljoin(current, loc)
                        redirects.append(current_next)
                        current = current_next
                        continue
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise FetchError("response_too_large", f"Response is larger than {max_bytes // 1024} KB limit.")
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > max_bytes:
                            raise FetchError(
                                "response_too_large", f"Response exceeded the {max_bytes // 1024} KB limit; aborted."
                            )
                    return FetchResult(
                        url=current, requested_url=url, status_code=resp.status_code,
                        content_type=resp.headers.get("content-type", "").split(";")[0].strip().lower(),
                        content=bytes(buf), encoding=resp.charset_encoding, redirects=redirects,
                    )
            except UrlNotAllowed as exc:
                raise FetchError(exc.code, f"Blocked: {exc.message}") from exc
            except httpx.TimeoutException as exc:
                raise FetchError("timeout", f"The site did not respond within {s.fetch_timeout_seconds:.0f}s.") from exc
            except httpx.ConnectError as exc:
                if _is_ssl_error(exc):
                    raise FetchError(
                        "ssl_error",
                        "TLS certificate verification failed for this site. Certificate checks are never disabled; "
                        "use manual official-content import instead.",
                    ) from exc
                raise FetchError("network_error", f"Could not connect to the site ({type(exc).__name__}).") from exc
            except httpx.HTTPError as exc:
                raise FetchError("network_error", f"Network error while fetching ({type(exc).__name__}).") from exc
        raise FetchError("too_many_redirects", f"More than {s.max_redirects} redirects.")

    def _robots_for(self, client: httpx.Client, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots.get(origin)
        if cached is not None and time.monotonic() - cached[0] < ROBOTS_TTL_SECONDS:
            return cached[1]
        robots_url = origin + "/robots.txt"
        rp: RobotFileParser | None
        try:
            res = self._get(client, robots_url, max_bytes=512 * 1024)
        except FetchError as exc:
            if exc.code in ("timeout", "network_error", "ssl_error"):
                raise FetchError("robots_unavailable", f"Could not read robots.txt ({exc.message})") from exc
            raise
        rp = RobotFileParser()
        if res.status_code in (401, 403):
            rp.disallow_all = True  # standard: access to robots.txt denied => assume disallowed
        elif 200 <= res.status_code < 300:
            rp.parse(res.content.decode("utf-8", errors="replace").splitlines())
        elif 400 <= res.status_code < 500:
            rp = None  # no robots.txt => everything allowed
        else:
            raise FetchError("robots_unavailable", f"robots.txt returned HTTP {res.status_code}.")
        self._robots[origin] = (time.monotonic(), rp)
        return rp

    # -- public ------------------------------------------------------------
    def fetch(self, url: str, language: str | None = None) -> FetchResult:
        """Fetch one validated URL. ``language`` (the source's declared language) sets Accept-Language so
        bilingual government sites return the version the admin registered."""
        s = self.settings
        validate_fetch_url(url, self.domains(), self.resolver)
        accept = {"ko": "ko,en;q=0.5", "en": "en,ko;q=0.5"}.get(language or "", f"{language},en;q=0.5" if language else "ko,en;q=0.5")
        with self._client(accept) as client:
            if s.respect_robots_txt:
                rp = self._robots_for(client, url)
                if rp is not None and not rp.can_fetch(s.fetch_user_agent, url):
                    raise FetchError(
                        "robots_disallowed", "robots.txt disallows automated access to this URL." + BLOCK_HINT
                    )
            result = self._get(client, url, max_bytes=s.max_response_bytes)
        if result.status_code >= 400:
            hint = BLOCK_HINT if result.status_code in (401, 403, 406, 429) else ""
            raise FetchError(f"http_{result.status_code}", f"The site responded with HTTP {result.status_code}.{hint}")
        if result.status_code == 204 or not result.content:
            raise FetchError("empty_response", "The site returned an empty response body.")
        ctype = result.content_type
        if ctype in OCTET_TYPES and result.content.startswith(b"%PDF-"):
            # some boards (e.g. SCH download.php) serve PDF attachments as octet-stream: trust the magic bytes only
            result.content_type = ctype = "application/pdf"
        if ctype and not ctype.startswith(HTML_TYPES) and ctype not in PDF_TYPES:
            raise FetchError("unsupported_content_type", f"Unsupported content type '{ctype}'.")
        return result


    def check_robots(self, url: str) -> tuple[bool | None, str]:
        """(allowed, message) for the Validate-URL step. None = robots.txt could not be read."""
        if not self.settings.respect_robots_txt:
            return True, "robots.txt checks are disabled in configuration."
        try:
            with self._client() as client:
                rp = self._robots_for(client, url)
        except FetchError as exc:
            return None, exc.message
        if rp is None:
            return True, "No robots.txt on this site (automated access is not restricted)."
        if rp.can_fetch(self.settings.fetch_user_agent, url):
            return True, "robots.txt allows fetching this URL."
        return False, "robots.txt disallows automated access to this URL." + BLOCK_HINT


def _is_ssl_error(exc: BaseException) -> bool:
    cur: BaseException | None = exc
    while cur is not None:
        if isinstance(cur, ssl.SSLError | ssl.CertificateError):
            return True
        cur = cur.__cause__ or cur.__context__
    return "CERTIFICATE_VERIFY_FAILED" in str(exc)
