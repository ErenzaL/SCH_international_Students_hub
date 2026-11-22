import ssl

import httpx
import pytest

from app.core.errors import UrlNotAllowed
from app.services.ingestion.errors import FetchError
from app.services.ingestion.fetcher import GuardedFetcher
from tests.conftest import ARTICLE_HTML, ARTICLE_URL, PUBLIC_IP, make_settings

OK = lambda host: [PUBLIC_IP]  # noqa: E731


def fetcher(handler, **kw):
    return GuardedFetcher(make_settings(**kw), transport=httpx.MockTransport(handler), resolver=OK)


def html_ok(request):
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    return httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"})


def test_fetch_ok():
    res = fetcher(html_ok).fetch(ARTICLE_URL)
    assert res.status_code == 200 and b"Alien registration" in res.content


def test_redirect_to_disallowed_host_is_blocked():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "https://evil.example.com/steal"})

    with pytest.raises(FetchError) as exc:
        fetcher(handler).fetch(ARTICLE_URL)
    assert exc.value.code == "url_not_allowed"


def test_redirect_to_metadata_ip_is_blocked():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    with pytest.raises(FetchError) as exc:
        fetcher(handler).fetch(ARTICLE_URL)
    assert "blocked" in exc.value.message.lower()


def test_redirect_within_allowlist_is_followed_and_recorded():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path.endswith("visaAndStay.do"):
            return httpx.Response(301, headers={"location": "/en_US/new/place.do"})
        return httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"})

    res = fetcher(handler).fetch(ARTICLE_URL)
    assert res.url.endswith("/en_US/new/place.do") and len(res.redirects) == 1


def test_redirect_loop_is_capped():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": str(req.url) + "x"})

    with pytest.raises(FetchError) as exc:
        fetcher(handler, max_redirects=3).fetch(ARTICLE_URL)
    assert exc.value.code == "too_many_redirects"


def test_response_size_limit_enforced_while_streaming():
    big = b"<html><body>" + b"a" * (2 * 1024 * 1024) + b"</body></html>"

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=big, headers={"content-type": "text/html"})

    with pytest.raises(FetchError) as exc:
        fetcher(handler, max_response_mb=1).fetch(ARTICLE_URL)
    assert exc.value.code == "response_too_large"


def test_robots_disallow_is_respected():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /en_US/plan/")
        return httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"})

    with pytest.raises(FetchError) as exc:
        fetcher(handler).fetch(ARTICLE_URL)
    assert exc.value.code == "robots_disallowed"
    assert "manual" in exc.value.message.lower()


def test_robots_403_means_disallowed():
    def handler(req):
        return httpx.Response(403) if req.url.path == "/robots.txt" else httpx.Response(200, text=ARTICLE_HTML)

    with pytest.raises(FetchError) as exc:
        fetcher(handler).fetch(ARTICLE_URL)
    assert exc.value.code == "robots_disallowed"


def test_http_403_gives_meaningful_error_and_does_not_bypass():
    def handler(req):
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(403, text="Forbidden")

    with pytest.raises(FetchError) as exc:
        fetcher(handler).fetch(ARTICLE_URL)
    assert exc.value.code == "http_403" and "does not bypass" in exc.value.message


def test_unsupported_content_type():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"\x00\x01", headers={"content-type": "application/zip"})

    with pytest.raises(FetchError) as exc:
        fetcher(handler).fetch(ARTICLE_URL)
    assert exc.value.code == "unsupported_content_type"


def test_timeout_is_reported():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(FetchError) as exc:
        fetcher(handler).fetch(ARTICLE_URL)
    assert exc.value.code == "timeout"


def test_invalid_certificate_reported_not_bypassed():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        err = httpx.ConnectError("tls", request=req)
        err.__cause__ = ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
        raise err

    with pytest.raises(FetchError) as exc:
        fetcher(handler).fetch(ARTICLE_URL)
    assert exc.value.code == "ssl_error" and "never disabled" in exc.value.message


def test_non_allowlisted_start_url_never_hits_network():
    calls = []
    f = fetcher(lambda req: calls.append(1) or httpx.Response(200, text="x"))
    with pytest.raises(UrlNotAllowed):
        f.fetch("https://evil.example.com/")
    assert calls == []
