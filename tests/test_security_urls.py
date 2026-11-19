import pytest
from app.security.urls import UnsafeURLError, host_in, host_of, normalise_url, validate_fetch_url


def test_normalise_url():
    assert normalise_url("https://tgpsc.gov.in/path/to/page") == "https://tgpsc.gov.in/path/to/page"
    assert normalise_url("/relative/link", base="https://tgpsc.gov.in/home") == "https://tgpsc.gov.in/relative/link"


def test_reject_credentials_in_url():
    with pytest.raises(UnsafeURLError):
        normalise_url("https://user:pass@tgpsc.gov.in/")


def test_reject_non_http_schemes():
    with pytest.raises(UnsafeURLError):
        normalise_url("javascript:alert(1)")
    with pytest.raises(UnsafeURLError):
        normalise_url("file:///etc/passwd")


def test_ssrf_protection_localhost():
    with pytest.raises(UnsafeURLError):
        validate_fetch_url("http://localhost:8000/test", allowed_domains=["localhost"], check_dns=False)


def test_domain_allowlist_enforcement():
    allowed = ["tgpsc.gov.in", "websitenew.tgpsc.gov.in"]
    assert host_in("websitenew.tgpsc.gov.in", allowed) is True
    assert host_in("malicious-site.com", allowed) is False

    with pytest.raises(UnsafeURLError):
        validate_fetch_url("https://evil.com/hack", allowed_domains=allowed, check_dns=False)
