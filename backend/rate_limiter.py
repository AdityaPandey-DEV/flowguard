"""
FlowGuard Rate Limiter — Sliding Window Algorithm

This module implements a sliding window rate limiter from scratch.
No Redis, no external cache — pure Python using collections.deque.

HOW THE SLIDING WINDOW ALGORITHM WORKS:
=========================================
Instead of fixed time windows (which have the "boundary burst" problem),
we use a sliding window that always looks at the last N seconds from NOW.

Example with limit=3 requests per 10-second window:

    Timeline:  |--t0--t1--t2----t3--t4--t5--t6--t7--t8--|
    Requests:       R     R            R     R
                    ↑     ↑            ↑     ↑
                    1     2            3     4 ← rejected!

At time t7, we look back 10 seconds. We see 3 requests (t1, t2, t5).
The 4th request at t7 would exceed the limit, so it's rejected.
We also tell the client: "retry after X seconds" (when the oldest request
in the window will expire).

WHY deque (double-ended queue)?
================================
- We only ever append to the right (new timestamps)
- We only ever pop from the left (expired timestamps)
- Both operations are O(1)
- This is perfect for a sliding window — we never access the middle
"""

import time
import threading
from collections import deque
from typing import Dict, Tuple, Optional

from database import db_manager


class SlidingWindowRateLimiter:
    """Sliding window rate limiter using in-memory deques.

    Each client_id gets its own deque of request timestamps.
    Expired timestamps are lazily cleaned up on each is_allowed() call.

    Attributes:
        _windows: Dict mapping client_id → deque of Unix timestamps.
        _lock: Thread lock for safe concurrent access.
        _sync_thread: Background thread that syncs data to MongoDB.
    """

    def __init__(self, sync_interval: int = 30) -> None:
        """Initialize the rate limiter.

        Args:
            sync_interval: Seconds between MongoDB sync operations.
                          Data is always in-memory; MongoDB is a backup.
        """
        self._windows: Dict[str, deque] = {}
        self._lock = threading.Lock()
        self._request_count = 0  # Total requests processed (for stats)
        self._rejected_count = 0  # Total requests rejected
        self._sync_interval = sync_interval

        # Start background sync thread
        self._sync_thread = threading.Thread(
            target=self._sync_to_mongo,
            daemon=True,  # Dies when main thread dies
            name="rate-limiter-sync",
        )
        self._sync_thread.start()

    def is_allowed(
        self,
        client_id: str,
        limit: int = 100,
        window_seconds: int = 60,
    ) -> Tuple[bool, float]:
        """Check if a request from this client is allowed.

        The sliding window algorithm:
        1. Get current time
        2. Remove all timestamps older than (now - window_seconds) from the deque
        3. If remaining timestamps < limit → allowed, add current timestamp
        4. If remaining timestamps >= limit → rejected, calculate retry_after

        Args:
            client_id: Unique identifier for the client.
            limit: Maximum requests allowed in the window.
            window_seconds: Size of the sliding window in seconds.

        Returns:
            Tuple of (is_allowed: bool, retry_after_seconds: float).
            retry_after is 0.0 if allowed, positive float if rejected.
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            # Create deque for new clients
            if client_id not in self._windows:
                self._windows[client_id] = deque()

            window = self._windows[client_id]

            # Step 1: Remove expired timestamps from the LEFT of the deque
            # Since timestamps are always appended in order, the oldest are on the left
            while window and window[0] <= cutoff:
                window.popleft()

            # Step 2: Check if within limit
            if len(window) < limit:
                # ALLOWED — add this request's timestamp
                window.append(now)
                self._request_count += 1
                return True, 0.0
            else:
                # REJECTED — calculate when the oldest request in the window expires
                # The oldest timestamp is window[0]. It will expire at:
                #   window[0] + window_seconds
                # So the client should retry after:
                #   (window[0] + window_seconds) - now
                oldest = window[0]
                retry_after = (oldest + window_seconds) - now
                self._rejected_count += 1
                self._request_count += 1
                return False, max(0.0, retry_after)

    def get_client_usage(self, client_id: str, window_seconds: int = 60) -> int:
        """Get the current request count for a client in the window.

        Args:
            client_id: The client to check.
            window_seconds: Size of the sliding window.

        Returns:
            Number of requests in the current window.
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            if client_id not in self._windows:
                return 0
            window = self._windows[client_id]
            # Count only non-expired timestamps
            return sum(1 for ts in window if ts > cutoff)

    def get_stats(self) -> dict:
        """Get rate limiter statistics.

        Returns:
            Dict with total_requests, rejected_requests, active_clients,
            and success_rate.
        """
        with self._lock:
            active_clients = len(self._windows)
            total = self._request_count
            rejected = self._rejected_count

        return {
            "total_requests": total,
            "rejected_requests": rejected,
            "active_clients": active_clients,
            "success_rate": round(
                ((total - rejected) / total * 100) if total > 0 else 100.0, 2
            ),
        }

    def _sync_to_mongo(self) -> None:
        """Background thread: sync rate limiter data to MongoDB every N seconds.

        This provides persistence — if the server restarts, we lose in-memory data,
        but we have a snapshot in MongoDB. This is a best-effort backup,
        NOT the primary data store (that's the in-memory deque).
        """
        while True:
            time.sleep(self._sync_interval)
            try:
                db = db_manager.get_db()
                if db is None:
                    continue  # MongoDB not available, skip this sync

                collection = db["rate_limiter_state"]
                with self._lock:
                    for client_id, window in self._windows.items():
                        collection.update_one(
                            {"client_id": client_id},
                            {
                                "$set": {
                                    "client_id": client_id,
                                    "timestamps": list(window),
                                    "synced_at": time.time(),
                                }
                            },
                            upsert=True,
                        )
            except Exception as e:
                # Don't crash the sync thread — just log and retry next cycle
                print(f"⚠️  Rate limiter sync failed: {e}")
