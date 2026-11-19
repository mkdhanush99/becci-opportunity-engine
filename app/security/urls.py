"""URL validation, SSRF protection and outbound-domain allowlisting.

External pages are untrusted. Every URL we fetch or store is validated here.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse, urlunparse

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    pass


def normalise_url(url: str, base: str | None = None) -> str:
    url = (url or "").strip()
    if base:
        url = urljoin(base, url)
    p = urlparse(url)
    if p.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"scheme not allowed: {p.scheme!r}")
    if not p.hostname:
        raise UnsafeURLError("missing host")
    if p.username or p.password:
        raise UnsafeURLError("credentials in URL are not allowed")
    host = p.hostname.lower().rstrip(".")
    netloc = host if not p.port or p.port in (80, 443) else f"{host}:{p.port}"
    return urlunparse((p.scheme.lower(), netloc, p.path or "/", "", p.query, ""))


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def registrable_match(host: str, domain: str) -> bool:
    """True if host equals domain or is a subdomain of it."""
    host, domain = host.lower().rstrip("."), domain.lower().lstrip(".").rstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    return host == domain or host.endswith("." + domain)


def host_in(host: str, domains: list[str] | set[str]) -> bool:
    return any(registrable_match(host, d) for d in domains)


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified)


def assert_public_host(host: str, resolver=socket.getaddrinfo) -> None:
    """Reject hosts that resolve to private/loopback/link-local addresses (SSRF)."""
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal:
        if not _is_public_ip(host):
            raise UnsafeURLError(f"non-public address: {host}")
        return
    if host in {"localhost"} or host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeURLError(f"internal hostname: {host}")
    try:
        infos = resolver(host, None)
    except socket.gaierror as e:
        raise UnsafeURLError(f"DNS resolution failed for {host}: {e}") from e
    for info in infos:
        ip = info[4][0]
        if not _is_public_ip(ip):
            raise UnsafeURLError(f"{host} resolves to non-public address {ip}")


def validate_fetch_url(url: str, allowed_domains: list[str] | set[str] | None, *, check_dns: bool = True,
                       resolver=socket.getaddrinfo) -> str:
    """Validate a URL before any outbound request."""
    u = normalise_url(url)
    host = host_of(u)
    if host in {"localhost"} or host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeURLError(f"internal hostname: {host}")
    if allowed_domains is not None and not host_in(host, allowed_domains):
        raise UnsafeURLError(f"host {host} is not in the approved source domains")
    if check_dns:
        assert_public_host(host, resolver=resolver)
    return u


def safe_link(href: str | None, base: str) -> str | None:
    """Resolve a link found on an untrusted page; drop javascript:, data:, mailto:, '#'."""
    if not href:
        return None
    h = href.strip()
    if not h or h.startswith("#") or h.lower().startswith(("javascript:", "data:", "mailto:", "tel:", "vbscript:")):
        return None
    try:
        return normalise_url(h, base)
    except UnsafeURLError:
        return None
