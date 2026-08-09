"""In-memory rate limiting for auth endpoints.

Per security plan §1: slow down brute-force attempts on login/register
without reintroducing user data into the token path (no PII in JWT,
no persistent rate-limit storage that could itself become a timing
side-channel).

Uses a simple sliding-window counter in process memory. This is
intentionally per-process (not shared across API instances) — the
purpose is to make automated brute-force attacks impractical, not to
be a perfect distributed rate limiter. A Redis-backed implementation
can be swapped in behind the same interface later.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Tuple, Set
from app.core.config import settings


# ── Configuration ────────────────────────────────────────────────────

MAX_ATTEMPTS_PER_WINDOW = settings.rate_limit_auth_requests
WINDOW_SECONDS = settings.rate_limit_auth_window
BLOCKLIST_CLEANUP_INTERVAL = 300  # clean stale entries every 5 min


# ── State ────────────────────────────────────────────────────────────

# key → list of attempt timestamps (epoch seconds)
_attempts: dict[str, list[float]] = defaultdict(list)
# permanently blocked IPs after repeated window violations
_blocked: dict[str, float] = {}  # ip → blocked_until epoch
_last_cleanup = time.time()


def _cleanup_stale_entries(now: float) -> None:
    """Periodic cleanup of expired entries to prevent memory growth."""
    global _last_cleanup
    if now - _last_cleanup < BLOCKLIST_CLEANUP_INTERVAL:
        return
    _last_cleanup = now

    window_start = now - WINDOW_SECONDS
    expired_keys: list[str] = []

    for key, timestamps in _attempts.items():
        # Filter out timestamps outside the window
        active = [t for t in timestamps if t > window_start]
        if active:
            _attempts[key] = active
        else:
            expired_keys.append(key)

    for key in expired_keys:
        del _attempts[key]

    # Clean up expired blocklist entries
    expired_blocked = [ip for ip, until in _blocked.items() if until <= now]
    for ip in expired_blocked:
        del _blocked[ip]


def check_rate_limit(key: str) -> bool:
    """Return True if the request is within limits, False if rate-limited.

    Args:
        key: A unique identifier for the client, typically the client IP.

    Returns:
        True if the request should proceed, False if it should be blocked.
    """
    now = time.time()
    _cleanup_stale_entries(now)

    # Check persistent blocklist (repeated violations)
    if key in _blocked and _blocked[key] > now:
        return False

    # Sliding window: count attempts in the last WINDOW_SECONDS
    window_start = now - WINDOW_SECONDS
    active = [t for t in _attempts[key] if t > window_start]

    if len(active) >= MAX_ATTEMPTS_PER_WINDOW:
        # Violation: block for 5 minutes
        _blocked[key] = now + 300
        _attempts[key] = []
        return False

    active.append(now)
    _attempts[key] = active
    return True


def get_client_key(request) -> str:
    """Extract a rate-limiting key from the incoming request.

    Model A -- trusted client identity (Phase 2, Task 2.1): the key is the
    TCP peer address (request.client.host) only. Forwarded headers such as
    X-Forwarded-For are intentionally IGNORED: without a verified
    trusted-proxy configuration that blocks direct API access and is the
    sole allowed source of forwarded headers, a caller-supplied header is
    attacker-controlled and would let a caller spoof the key and bypass
    the limiter.

    A verified-proxy path (Model B) may be added later ONLY behind an
    explicit opt-in that documents the network guarantee making the
    header trustworthy (per 10-security-plan.md section 6). Do not add a
    fallback that trusts arbitrary forwarded headers.

    Falls back to "unknown" if the peer address is unavailable.
    """
    client_addr = getattr(request, "client", None)
    client_host = getattr(client_addr, "host", None)
    return client_host or "unknown"