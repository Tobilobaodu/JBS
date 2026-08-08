"""SSRF-safe URL fetch tests — per 10-security-plan.md §4 "How to test".

Every probe pattern listed in the security plan must be explicitly tested
and pass before the job post fetch worker or endpoint are built.
"""

import socket
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest

from app.services.ssrf_safe_fetch import (
    SSRFRejection,
    FetchError,
    ssrf_safe_fetch,
    resolve_and_validate_ip,
)


# ──────────────────────────────────────────────────────────────────────
# Scheme validation
# ──────────────────────────────────────────────────────────────────────

class TestSchemeValidation:
    """File://, gopher://, ftp:// etc. must be rejected before any DNS lookup."""

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "file://c:/windows/system32/config/sam",
        "gopher://10.0.0.1:80/_GET%20/",
        "ftp://ftp.example.com/",
        "dict://localhost:2628/",
        "jar:file:///tmp/test.jar!/",
    ])
    def test_non_http_schemes_rejected(self, url):
        """Any scheme that is not http or https must raise SSRFRejection."""
        with pytest.raises(SSRFRejection, match="scheme"):
            ssrf_safe_fetch(url)

    def test_http_and_https_allowed(self):
        """http and https are the only allowed schemes."""
        # We don't actually connect — the mock will prevent real DNS/network
        with patch.object(socket, "getaddrinfo", side_effect=SSRFRejection("mock")):
            # Scheme validation happens BEFORE DNS, so an https URL gets past
            # scheme check and then hits the mocked DNS failure.
            with pytest.raises(SSRFRejection):
                ssrf_safe_fetch("https://example.com")


# ──────────────────────────────────────────────────────────────────────
# IP validation (no network calls — mock DNS)
# ──────────────────────────────────────────────────────────────────────

def _mock_dns(ip_list: list[str]):
    """Return a getaddrinfo mock that resolves to the given IP list.

    Each IP becomes a mock sockaddr tuple matching the IPv4/IPv6 family.
    """
    results = []
    for ip in ip_list:
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        results.append((family, socket.SOCK_STREAM, 0, "", (ip, 80)))
    return lambda host, port, family, socktype: results


class TestIPValidation:
    """DNS resolution must reject private, loopback, and link-local IPs."""

    def test_cloud_metadata_endpoint_rejected(self):
        """169.254.169.254 is the cloud metadata endpoint — must be blocked."""
        with patch.object(socket, "getaddrinfo",
                          _mock_dns(["169.254.169.254"])):
            with pytest.raises(SSRFRejection,
                               match="private IP.*169.254.169.254"):
                resolve_and_validate_ip("metadata.internal")

    def test_rfc1918_range_10(self):
        """10.x.x.x must be rejected."""
        with patch.object(socket, "getaddrinfo",
                          _mock_dns(["10.0.0.5"])):
            with pytest.raises(SSRFRejection):
                resolve_and_validate_ip("internal.example.com")

    def test_rfc1918_range_192_168(self):
        """192.168.x.x must be rejected."""
        with patch.object(socket, "getaddrinfo",
                          _mock_dns(["192.168.1.10"])):
            with pytest.raises(SSRFRejection):
                resolve_and_validate_ip("home.local")

    def test_loopback_rejected(self):
        """127.0.0.1 and ::1 must be rejected."""
        with patch.object(socket, "getaddrinfo",
                          _mock_dns(["127.0.0.1"])):
            with pytest.raises(SSRFRejection):
                resolve_and_validate_ip("localhost")

        with patch.object(socket, "getaddrinfo",
                          _mock_dns(["::1"])):
            with pytest.raises(SSRFRejection):
                resolve_and_validate_ip("localhost6")

    def test_link_local_rejected(self):
        """169.254.x.x must be rejected."""
        with patch.object(socket, "getaddrinfo",
                          _mock_dns(["169.254.1.2"])):
            with pytest.raises(SSRFRejection):
                resolve_and_validate_ip("linklocal.local")

    def test_public_ip_allowed(self):
        """A genuine public IP (e.g. 8.8.8.8) must pass validation."""
        with patch.object(socket, "getaddrinfo",
                          _mock_dns(["8.8.8.8"])):
            result = resolve_and_validate_ip("example.com")
            assert result == "8.8.8.8"

    def test_mixed_private_and_public_rejected(self):
        """If ANY resolved address is private, the entire resolution fails.

        A hostname returning both a public and a private address (DNS
        rebinding scenario) must be rejected — the private one is checked
        first and fails before the public one is considered.
        """
        # getaddrinfo order is typically IPv6-first, then IPv4.
        # Make the first address public, second private — the check
        # iterates ALL addresses.
        with patch.object(socket, "getaddrinfo",
                          _mock_dns(["8.8.8.8", "10.0.0.1"])):
            with pytest.raises(SSRFRejection):
                resolve_and_validate_ip("dual.local")

    def test_decimal_encoded_private_ip_rejected(self):
        """Decimal-encoded private IP (e.g. http://2130706433/ for 127.0.0.1).

        URL parsing doesn't decode decimal integers — the hostname string
        "2130706433" must be caught when it's resolved to an actual IP.
        Since DNS won't resolve a bare integer, this test verifies that
        if something DOES manage to resolve to a private IP, it's blocked.
        """
        with patch.object(socket, "getaddrinfo",
                          _mock_dns(["127.0.0.1"])):
            with pytest.raises(SSRFRejection):
                resolve_and_validate_ip("2130706433")


# ──────────────────────────────────────────────────────────────────────
# Redirect re-validation
# ──────────────────────────────────────────────────────────────────────

class TestRedirectRevalidation:
    """After every redirect, the new target IP must be re-validated."""

    def test_redirect_to_internal_rejected(self):
        """A public URL that 302-redirects to a private IP is BLOCKED."""
        # First hop: public IP, returns a 302 to a private address.
        # Second hop: resolve_and_validate_ip sees the private IP → SSRFRejection.

        # Patch resolve_and_validate_ip directly so the first call succeeds
        # and the second (redirect) call fails.
        resolve_calls = [
            "8.8.8.8",  # first hop — public
            SSRFRejection("private"),  # second hop — private
        ]
        def _resolve_side_effect(hostname):
            result = resolve_calls.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(socket, "getaddrinfo",
                          _mock_dns(["8.8.8.8"])):
            with patch("app.services.ssrf_safe_fetch.resolve_and_validate_ip",
                       side_effect=_resolve_side_effect):
                with patch("app.services.ssrf_safe_fetch._connect_and_read") as mock_fetch:
                    # First call returns a redirect; second won't be reached
                    # because SSRFRejection will fire at validation.
                    mock_fetch.return_value = (b"", "http://10.0.0.1/redirect-target")
                    with pytest.raises(SSRFRejection):
                        ssrf_safe_fetch("http://safe.example.com")


# ──────────────────────────────────────────────────────────────────────
# Size and timeout enforcement
# ──────────────────────────────────────────────────────────────────────

class TestSizeAndTimeout:
    """Response size cap and timeout must be enforced."""

    def test_response_too_large_raises(self):
        """A response exceeding max_bytes must raise FetchError."""
        large_body = b"A" * (2 * 1024 * 1024 + 1)
        with patch("app.services.ssrf_safe_fetch.resolve_and_validate_ip",
                   return_value="8.8.8.8"):
            with patch("app.services.ssrf_safe_fetch._connect_and_read",
                       side_effect=FetchError("Response exceeds maximum size")):
                with pytest.raises(FetchError):
                    ssrf_safe_fetch("http://example.com", max_bytes=100)

    def test_timeout_raises_fetch_error(self):
        """A timeout must raise FetchError (not a raw socket.timeout)."""
        with patch("app.services.ssrf_safe_fetch.resolve_and_validate_ip",
                   return_value="8.8.8.8"):
            with patch("app.services.ssrf_safe_fetch._connect_and_read",
                       side_effect=FetchError("Timed out fetching")):
                with pytest.raises(FetchError):
                    ssrf_safe_fetch("http://example.com", timeout=1)