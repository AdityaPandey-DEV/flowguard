"""
Tests for the Sliding Window Rate Limiter

8 test cases covering:
- Basic allow/reject behavior
- Exact boundary conditions
- Retry-after calculation
- Window expiry (time mocking)
- Client isolation
- Thread safety under concurrency
"""

import time
import threading
from unittest.mock import patch

import pytest

# We need to patch config before importing rate_limiter
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rate_limiter import SlidingWindowRateLimiter


@pytest.fixture
def limiter():
    """Create a fresh rate limiter for each test.

    Uses a very long sync interval to prevent background thread
    from interfering with tests.
    """
    return SlidingWindowRateLimiter(sync_interval=9999)


class TestSlidingWindowRateLimiter:
    """Test suite for the sliding window rate limiter."""

    def test_first_request_allowed(self, limiter):
        """The very first request from any client should always be allowed."""
        allowed, retry_after = limiter.is_allowed("client-1", limit=10, window_seconds=60)
        assert allowed is True
        assert retry_after == 0.0

    def test_within_limit_allowed(self, limiter):
        """Multiple requests within the limit should all be allowed."""
        for i in range(5):
            allowed, retry_after = limiter.is_allowed(
                "client-2", limit=10, window_seconds=60
            )
            assert allowed is True, f"Request {i+1} should be allowed"
            assert retry_after == 0.0

    def test_exactly_at_limit_allowed(self, limiter):
        """The request that hits exactly the limit should still be allowed."""
        limit = 5
        for i in range(limit):
            allowed, _ = limiter.is_allowed("client-3", limit=limit, window_seconds=60)
            assert allowed is True, f"Request {i+1} of {limit} should be allowed"

    def test_over_limit_rejected(self, limiter):
        """Requests beyond the limit should be rejected with 429-equivalent."""
        limit = 3
        # Fill the window
        for _ in range(limit):
            limiter.is_allowed("client-4", limit=limit, window_seconds=60)

        # Next request should be rejected
        allowed, retry_after = limiter.is_allowed(
            "client-4", limit=limit, window_seconds=60
        )
        assert allowed is False
        assert retry_after > 0

    def test_retry_after_positive_when_rejected(self, limiter):
        """When rejected, retry_after should indicate when the window opens up."""
        limit = 2
        # Fill the window
        for _ in range(limit):
            limiter.is_allowed("client-5", limit=limit, window_seconds=10)

        # Reject — retry_after should be <= window_seconds
        allowed, retry_after = limiter.is_allowed(
            "client-5", limit=limit, window_seconds=10
        )
        assert allowed is False
        assert 0 < retry_after <= 10

    def test_window_resets_after_expiry(self, limiter):
        """After the window expires, requests should be allowed again."""
        limit = 2
        window = 1  # 1-second window for fast testing

        # Fill the window
        for _ in range(limit):
            limiter.is_allowed("client-6", limit=limit, window_seconds=window)

        # Should be rejected now
        allowed, _ = limiter.is_allowed("client-6", limit=limit, window_seconds=window)
        assert allowed is False

        # Wait for window to expire
        time.sleep(window + 0.1)

        # Should be allowed again
        allowed, retry_after = limiter.is_allowed(
            "client-6", limit=limit, window_seconds=window
        )
        assert allowed is True
        assert retry_after == 0.0

    def test_different_clients_independent(self, limiter):
        """Rate limits for different clients should be completely independent."""
        limit = 2

        # Exhaust client-A's limit
        for _ in range(limit):
            limiter.is_allowed("client-A", limit=limit, window_seconds=60)
        allowed_a, _ = limiter.is_allowed("client-A", limit=limit, window_seconds=60)
        assert allowed_a is False  # A is blocked

        # Client-B should still be allowed
        allowed_b, _ = limiter.is_allowed("client-B", limit=limit, window_seconds=60)
        assert allowed_b is True  # B is independent

    def test_concurrent_requests_thread_safe(self, limiter):
        """Rate limiter should be thread-safe under concurrent access.

        We fire 20 concurrent requests with a limit of 10.
        Exactly 10 should be allowed, 10 should be rejected.
        No crashes, no data corruption.
        """
        limit = 10
        results = {"allowed": 0, "rejected": 0}
        results_lock = threading.Lock()

        def fire_request():
            allowed, _ = limiter.is_allowed(
                "concurrent-client", limit=limit, window_seconds=60
            )
            with results_lock:
                if allowed:
                    results["allowed"] += 1
                else:
                    results["rejected"] += 1

        threads = [threading.Thread(target=fire_request) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results["allowed"] == limit
        assert results["rejected"] == 10
        assert results["allowed"] + results["rejected"] == 20
