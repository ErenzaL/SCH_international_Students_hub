"""SSRF protection for outbound fetches.

Rules enforced before *every* request (including each redirect hop):
  * scheme must be http or https
  * no credentials in the URL, no unusual ports
  * host must be on the explicit trusted-domain allowlist (exact or subdomain match)
  * every resolved IP must be public: loopback, private, link-local (incl. the
    169.254.169.254 cloud-metadata endpoint), multicast, reserved and unspecified
    addresses are rejected
Note: a determined DNS-rebinding attacker who controls a *trusted domain's* DNS is
out of scope; the allowlist is what bounds that risk (see docs/ingestion.md).
"""
from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Sequence
from urllib.parse import urlsplit, urlunsplit

from app.core.errors import UrlNotAllowed

ALLOWED_PORTS = {None, 80, 443}
Resolver = Callable[[str], Sequence[str]]


def default_resolver(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UrlNotAllowed(f"Host '{host}' could not be resolved: {exc}", code="dns_error") from exc
    return sorted({info[4][0] for info in infos})


def is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or (isinstance(addr, ipaddress.IPv4Address) and addr in ipaddress.ip_network("100.64.0.0/10"))  # CGNAT
    )


def host_in_allowlist(host: str, allowed: Sequence[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in allowed)


def validate_url_syntax(url: str, allowed_domains: Sequence[str]) -> str:
    """Validate scheme/host/allowlist without touching the network. Returns the URL unchanged."""
    if not url or len(url) > 2048:
        raise UrlNotAllowed("URL is empty or too long.")
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https"):
        raise UrlNotAllowed(f"Unsupported protocol '{parts.scheme or 'none'}'. Only http and https are allowed.")
    if not parts.hostname:
        raise UrlNotAllowed("URL has no host.")
    if parts.username or parts.password:
        raise UrlNotAllowed("URLs with embedded credentials are not allowed.")
    try:
        port = parts.port
    except ValueError as exc:
        raise UrlNotAllowed("URL has an invalid port.") from exc
    if port not in ALLOWED_PORTS:
        raise UrlNotAllowed(f"Port {port} is not allowed.")
    host = parts.hostname
    # Literal IPs are never on the allowlist
    try:
        ipaddress.ip_address(host)
        raise UrlNotAllowed("IP-address hosts are not allowed; register the official domain name instead.")
    except ValueError:
        pass
    if not host_in_allowlist(host, allowed_domains):
        raise UrlNotAllowed(
            f"Domain '{host}' is not on the trusted-domain allowlist ({', '.join(allowed_domains)}).",
            details={"host": host, "allowed_domains": list(allowed_domains)},
        )
    return url.strip()


def validate_fetch_url(url: str, allowed_domains: Sequence[str], resolver: Resolver = default_resolver) -> str:
    """Full validation incl. DNS resolution; call before each network request."""
    url = validate_url_syntax(url, allowed_domains)
    host = urlsplit(url).hostname or ""
    ips = resolver(host)
    if not ips:
        raise UrlNotAllowed(f"Host '{host}' did not resolve to any address.", code="dns_error")
    for ip in ips:
        if not is_public_ip(ip):
            raise UrlNotAllowed(
                f"Host '{host}' resolves to a non-public address ({ip}); request blocked.", code="blocked_address"
            )
    return url


def canonicalize_url(url: str) -> str:
    """Stable identity for a page: lowercase scheme/host, no fragment, default port dropped.

    The query string is preserved (the exact registered URL matters on board-style sites).
    """
    p = urlsplit(url.strip())
    netloc = (p.hostname or "").lower()
    if p.port and p.port not in (80, 443):
        netloc += f":{p.port}"
    return urlunsplit((p.scheme.lower(), netloc, p.path or "/", p.query, ""))
