"""SSRF-safe URL fetch utility.

Per 10-security-plan.md §4: validates scheme, resolved IP, redirect chain,
timeout, and response size before fetching a user-supplied URL.

This is a standalone, pure-Python utility with no dependencies beyond the
standard library. It does NOT call out to any internal service, database,
or queue — it only opens TCP connections to validated public addresses.

BUILD ORDER: This must be built and tested BEFORE the job post fetch worker
or endpoint. Once a "just fetch the URL" implementation exists and works for
the happy path, retrofitting these controls is a bigger, riskier change.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from http.client import HTTPConnection, HTTPSConnection, HTTPResponse
from typing import Tuple

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

# Schemes we allow — everything else is rejected before DNS resolution.
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Private / reserved ranges.  We block these regardless of how the IP
# was encoded (dotted-decimal, decimal integer, hex, octal, URI-encoded).
_PRIVATE_NETWORKS = [
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("127.0.0.0/8"),     # loopback
    ipaddress.IPv4Network("169.254.0.0/16"),  # link-local (includes cloud metadata)
    ipaddress.IPv4Network("0.0.0.0/8"),        # "This host on this network"
    ipaddress.IPv6Network("::1/128"),           # IPv6 loopback
    ipaddress.IPv6Network("fe80::/10"),         # IPv6 link-local
]

# Default limits
_DEFAULT_TIMEOUT_SECONDS = 15
_DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


class SSRFRejection(ValueError):
    """Raised when a URL fails SSRF validation."""


class FetchError(ValueError):
    """Raised when a validated URL cannot be fetched (timeout, size, HTTP error)."""


def ssrf_safe_fetch(
    url: str,
    timeout: int = _DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> str:
    """Fetch a URL with SSRF-safe validation at every hop.

    1. Validate the scheme.
    2. Resolve the hostname and validate the IP is public.
    3. Connect with timeout.
    4. Follow redirects, re-validating the target IP at every hop.
    5. Enforce a maximum response size.

    Args:
        url: The user-supplied URL to fetch.
        timeout: Connection + read timeout in seconds.
        max_bytes: Maximum response body size in bytes.

    Returns:
        The response body as a decoded UTF-8 string.

    Raises:
        SSRFRejection: If the URL or any redirect target is unsafe.
        FetchError: If the URL cannot be fetched for non-SSRF reasons.
    """
    remaining_hops = 5  # max redirect chain depth
    current_url = url

    while remaining_hops > 0:
        remaining_hops -= 1

        parsed = _validate_and_parse_url(current_url)
        host = parsed.hostname
        if not host:
            raise SSRFRejection(f"URL '{current_url}' has no hostname.")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        scheme = parsed.scheme

        # Resolve and validate the IP
        ip_addr = resolve_and_validate_ip(host)

        try:
            body, redirect_url = _connect_and_read(
                scheme, host, port, parsed.path or "/", timeout, max_bytes
            )
        except (socket.timeout, TimeoutError):
            raise FetchError(
                f"Timed out fetching {scheme}://{host}:{port} after {timeout}s"
            )
        except (ConnectionError, OSError) as exc:
            raise FetchError(f"Cannot connect to {scheme}://{host}:{port}: {exc}")

        if redirect_url is not None:
            # Normalise relative redirects
            current_url = urllib.parse.urljoin(current_url, redirect_url)
            continue

        # No redirect — decode and return
        try:
            return body.decode("utf-8", errors="replace")
        except Exception as exc:
            raise FetchError(f"Failed to decode response body: {exc}")

    raise FetchError("Too many redirects (max 5)")


def resolve_and_validate_ip(hostname: str) -> str:
    """Resolve *hostname* and return its IP if it is a public, routable address.

    Raises SSRFRejection for any private, loopback, link-local, or
    otherwise non-public address.
    """
    try:
        # getaddrinfo returns *all* addresses; check every one.
        addrinfo = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFRejection(f"Cannot resolve hostname '{hostname}': {exc}")

    seen = set()
    last_public_ip = None

    for family, _, _, _, sockaddr in addrinfo:
        ip_str = str(sockaddr[0])
        # Strip scope ID from IPv6 addresses (e.g. "fe80::1%eth0")
        ip_str = ip_str.split("%")[0]

        if ip_str in seen:
            continue
        seen.add(ip_str)

        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            raise SSRFRejection(f"Unparseable IP address for '{hostname}': {ip_str}")

        if _is_private(addr):
            raise SSRFRejection(
                f"Hostname '{hostname}' resolves to private IP {ip_str} "
                f"(prohibited per SSRF controls)"
            )

        last_public_ip = ip_str

    if last_public_ip is None:
        raise SSRFRejection(f"No routable IP address found for '{hostname}'")

    return last_public_ip


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _validate_and_parse_url(url: str) -> urllib.parse.ParseResult:
    """Parse *url* and reject anything with a non-whitelisted scheme."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise SSRFRejection(
            f"Scheme '{parsed.scheme}' is not allowed. "
            f"Only http and https are supported."
        )
    if not parsed.hostname:
        raise SSRFRejection(f"URL '{url}' has no parseable hostname.")
    return parsed


def _is_private(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if *addr* is in any private / reserved range."""
    if addr.is_loopback or addr.is_link_local or addr.is_private:
        return True
    for net in _PRIVATE_NETWORKS:
        if addr in net:
            return True
    return False


def _connect_and_read(
    scheme: str,
    host: str,
    port: int,
    path: str,
    timeout: int,
    max_bytes: int,
) -> Tuple[bytes, str | None]:
    """Connect to *host:port*, read up to *max_bytes*, return (body, redirect_url).

    redirect_url is None if the response is not a redirect.
    """
    if scheme == "https":
        conn = HTTPSConnection(host, port, timeout=timeout)
    else:
        conn = HTTPConnection(host, port, timeout=timeout)

    try:
        conn.request("GET", path, headers={"User-Agent": "CV-Tailoring/1.0"})
        response = conn.getresponse()

        # Handle redirects (301, 302, 303, 307, 308)
        if response.status in (301, 302, 303, 307, 308):
            location = response.getheader("Location")
            conn.close()
            return b"", location  # caller re-validates

        if response.status >= 400:
            conn.close()
            raise FetchError(
                f"HTTP {response.status} fetching {scheme}://{host}{path}"
            )

        # Read body with size cap
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(min(8192, max_bytes - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total >= max_bytes:
                raise FetchError(
                    f"Response exceeds maximum size of {max_bytes} bytes "
                    f"(got {total}+ bytes)."
                )
        conn.close()
        return b"".join(chunks), None
    except Exception:
        conn.close()
        raise