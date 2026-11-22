import pytest

from app.core.errors import UrlNotAllowed
from app.security.url_guard import (
    canonicalize_url,
    host_in_allowlist,
    is_public_ip,
    validate_fetch_url,
    validate_url_syntax,
)

ALLOWED = ["sch.ac.kr", "studyinkorea.go.kr", "hikorea.go.kr"]


@pytest.mark.parametrize("url", [
    "https://sgee.sch.ac.kr/notice/notice01.php?page=1&make=&search=&type=&table_name=noti_fore&loc_mnu=3",
    "https://www.studyinkorea.go.kr/en_US/plan/visaAndStay.do",
    "http://www.hikorea.go.kr",
    "https://SCH.AC.KR/",
])
def test_allowed_urls(url):
    assert validate_url_syntax(url, ALLOWED) == url


@pytest.mark.parametrize("url,fragment", [
    ("ftp://www.hikorea.go.kr/file", "protocol"),
    ("file:///etc/passwd", "protocol"),
    ("javascript:alert(1)", "protocol"),
    ("https://evil.example.com/", "allowlist"),
    ("https://hikorea.go.kr.evil.com/", "allowlist"),
    ("https://evilhikorea.go.kr/", "allowlist"),
    ("https://user:pw@www.hikorea.go.kr/", "credentials"),
    ("https://www.hikorea.go.kr:8443/", "Port"),
    ("http://127.0.0.1/", "IP-address"),
    ("http://169.254.169.254/latest/meta-data/", "IP-address"),
    ("http://[::1]/", "IP-address"),
    ("https:///nohost", "no host"),
    ("", "empty"),
])
def test_rejected_urls(url, fragment):
    with pytest.raises(UrlNotAllowed) as exc:
        validate_url_syntax(url, ALLOWED)
    assert fragment.lower() in exc.value.message.lower()


def test_allowlist_matches_exact_or_subdomain_only():
    assert host_in_allowlist("sgee.sch.ac.kr", ALLOWED)
    assert host_in_allowlist("sch.ac.kr", ALLOWED)
    assert not host_in_allowlist("notsch.ac.kr", ALLOWED)
    assert not host_in_allowlist("sch.ac.kr.attacker.io", ALLOWED)


@pytest.mark.parametrize("ip,public", [
    ("93.184.216.34", True), ("8.8.8.8", True),
    ("127.0.0.1", False), ("10.0.0.5", False), ("172.16.3.4", False), ("192.168.1.1", False),
    ("169.254.169.254", False), ("0.0.0.0", False), ("100.64.1.1", False), ("224.0.0.1", False),
    ("::1", False), ("fe80::1", False), ("fd00::1", False), ("::ffff:127.0.0.1", False), ("::ffff:10.0.0.1", False),
])
def test_ip_classification(ip, public):
    assert is_public_ip(ip) is public


def test_resolution_to_private_address_is_blocked():
    with pytest.raises(UrlNotAllowed) as exc:
        validate_fetch_url("https://www.hikorea.go.kr/", ALLOWED, resolver=lambda h: ["10.1.2.3"])
    assert exc.value.code == "blocked_address"


def test_any_private_answer_blocks_even_with_public_ones():
    with pytest.raises(UrlNotAllowed):
        validate_fetch_url("https://www.hikorea.go.kr/", ALLOWED, resolver=lambda h: ["93.184.216.34", "127.0.0.1"])


def test_public_resolution_ok():
    url = "https://www.hikorea.go.kr/x"
    assert validate_fetch_url(url, ALLOWED, resolver=lambda h: ["93.184.216.34"]) == url


def test_canonicalize_preserves_query_and_drops_fragment():
    assert canonicalize_url("HTTPS://WWW.Example.GO.KR:443/a/b?x=1&y=2#frag") == "https://www.example.go.kr/a/b?x=1&y=2"
    assert canonicalize_url("https://www.hikorea.go.kr") == "https://www.hikorea.go.kr/"
