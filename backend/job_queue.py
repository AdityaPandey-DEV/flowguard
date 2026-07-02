"""
FlowGuard Job Queue — Priority Queue with Background Worker

This module implements a priority job queue from scratch using Python's heapq.
No Celery, no RQ — pure Python threading + heap.

HOW THE PRIORITY QUEUE WORKS:
==============================
Python's heapq is a min-heap: the smallest value is always at the top.
We map priorities to integers:
    high   = 0  (processed first — smallest number)
    medium = 1
    low    = 2  (processed last — largest number)

When two jobs have the same priority, we break ties using a monotonically
increasing counter. This ensures FIFO ordering within the same priority level.

Heap entry format: (priority, counter, job_dict)
    - priority: 0/1/2 for high/medium/low
    - counter: auto-incrementing integer (prevents comparing job dicts)
    - job_dict: the actual job data

WHY heapq instead of a sorted list?
====================================
- heapq.heappush: O(log n) insertion
- heapq.heappop:  O(log n) extraction of minimum
- sorted list insert: O(n) due to shifting elements
- For a job queue with thousands of jobs, this matters!

RETRY WITH EXPONENTIAL BACKOFF:
================================
If a job fails, we retry up to 3 times with increasing delays:
    Retry 1: wait 1 second
    Retry 2: wait 2 seconds
    Retry 3: wait 4 seconds (2^(retry-1))
This prevents hammering a failing service.
"""

import heapq
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from database import db_manager


# Priority mapping
PRIORITY_MAP = {
    "high": 0,
    "medium": 1,
    "low": 2,
}

# Job status constants
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class PriorityJobQueue:
    """Thread-safe priority job queue with background worker.

    Jobs are submitted with a priority (high/medium/low) and processed
    by a background worker thread in priority order.

    Attributes:
        _heap: Min-heap storing (priority, counter, job) tuples.
        _counter: Monotonic counter for FIFO tie-breaking.
        _lock: Thread lock for safe concurrent access.
        _jobs: Dict mapping job_id → job data (for status lookups).
        _workers: List of background worker threads.
        _max_queue_size: Maximum number of jobs allowed in the queue.
        _running: Flag to control worker thread lifecycle.
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        num_workers: int = 2,
        job_handler: Optional[Callable] = None,
    ) -> None:
        """Initialize the job queue.

        Args:
            max_queue_size: Maximum jobs allowed in the queue.
            num_workers: Number of background worker threads.
            job_handler: Optional callable to process jobs. If None, a default
                        handler is used that simulates work.
        """
        self._heap: List = []
        self._counter = 0
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._jobs: Dict[str, dict] = {}
        self._max_queue_size = max_queue_size
        self._running = True
        self._job_handler = job_handler or self._default_handler

        # Stats
        self._completed_count = 0
        self._failed_count = 0

        # Start worker threads
        self._workers: List[threading.Thread] = []
        for i in range(num_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name=f"job-worker-{i}",
            )
            worker.start()
            self._workers.append(worker)

    def submit(
        self,
        payload: Any,
        priority: str = "medium",
    ) -> Optional[str]:
        """Submit a new job to the queue.

        Args:
            payload: The job data/payload to process.
            priority: One of "high", "medium", "low".

        Returns:
            The job_id string if submitted successfully, None if queue is full.

        Raises:
            ValueError: If priority is not valid.
        """
        if priority not in PRIORITY_MAP:
            raise ValueError(
                f"Invalid priority '{priority}'. Must be one of: {list(PRIORITY_MAP.keys())}"
            )

        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        job = {
            "id": job_id,
            "payload": payload,
            "priority": priority,
            "status": STATUS_QUEUED,
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
            "retries": 0,
            "max_retries": 3,
        }

        with self._not_empty:
            # Check queue size limit
            if len(self._heap) >= self._max_queue_size:
                return None

            # Store job data
            self._jobs[job_id] = job

            # Push to heap: (priority_int, counter, job_id)
            # We store job_id in the heap, not the full job dict,
            # because heapq may try to compare the third element if
            # priority and counter are equal (they won't be since
            # counter is unique, but this is safer).
            heapq.heappush(
                self._heap,
                (PRIORITY_MAP[priority], self._counter, job_id),
            )
            self._counter += 1

            # Wake up a waiting worker
            self._not_empty.notify()

        # Persist to MongoDB (best-effort)
        self._persist_job(job)

        return job_id

    def get_job(self, job_id: str) -> Optional[dict]:
        """Get the status and data of a job.

        Args:
            job_id: The unique job identifier.

        Returns:
            Job dict if found, None otherwise.
        """
        with self._lock:
            return self._jobs.get(job_id)

    def get_recent_jobs(self, limit: int = 50) -> List[dict]:
        """Get the most recent jobs, sorted by creation time (newest first).

        Args:
            limit: Maximum number of jobs to return.

        Returns:
            List of job dicts.
        """
        with self._lock:
            all_jobs = sorted(
                self._jobs.values(),
                key=lambda j: j["created_at"],
                reverse=True,
            )
            return all_jobs[:limit]

    def get_stats(self) -> dict:
        """Get queue statistics.

        Returns:
            Dict with queue_depth, completed, failed, total_processed.
        """
        with self._lock:
            queue_depth = len(self._heap)
            total = len(self._jobs)

        return {
            "queue_depth": queue_depth,
            "total_jobs": total,
            "completed": self._completed_count,
            "failed": self._failed_count,
            "success_rate": round(
                (
                    self._completed_count
                    / (self._completed_count + self._failed_count)
                    * 100
                )
                if (self._completed_count + self._failed_count) > 0
                else 100.0,
                2,
            ),
        }

    def _worker_loop(self) -> None:
        """Background worker thread that continuously processes jobs.

        Workflow:
        1. Wait for a job to appear in the heap (using Condition variable)
        2. Pop the highest priority job
        3. Execute the job handler
        4. On success: mark completed
        5. On failure: retry with exponential backoff (up to 3 times)
        """
        while self._running:
            job_id = None

            # Wait for a job
            with self._not_empty:
                while not self._heap and self._running:
                    self._not_empty.wait(timeout=1.0)

                if not self._running:
                    break

                if self._heap:
                    _, _, job_id = heapq.heappop(self._heap)

            if job_id is None:
                continue

            # Process the job
            self._process_job(job_id)

    def _process_job(self, job_id: str) -> None:
        """Process a single job with retry logic.

        Args:
            job_id: The job to process.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = STATUS_PROCESSING
            job["started_at"] = datetime.now(timezone.utc).isoformat()

        try:
            result = self._job_handler(job["payload"])

            with self._lock:
                job["status"] = STATUS_COMPLETED
                job["completed_at"] = datetime.now(timezone.utc).isoformat()
                job["result"] = result
                self._completed_count += 1

        except Exception as e:
            with self._lock:
                job["retries"] += 1

                if job["retries"] >= job["max_retries"]:
                    # Max retries exhausted — mark as failed
                    job["status"] = STATUS_FAILED
                    job["completed_at"] = datetime.now(timezone.utc).isoformat()
                    job["error"] = str(e)
                    self._failed_count += 1
                else:
                    # Retry with exponential backoff
                    # Retry 1: 1s, Retry 2: 2s, Retry 3: 4s
                    backoff = 2 ** (job["retries"] - 1)
                    job["status"] = STATUS_QUEUED

                    # Re-add to heap for retry
                    heapq.heappush(
                        self._heap,
                        (PRIORITY_MAP[job["priority"]], self._counter, job_id),
                    )
                    self._counter += 1

                    # Sleep for backoff (outside the lock)
                    time.sleep(backoff)

        # Update MongoDB (best-effort)
        with self._lock:
            self._persist_job(self._jobs.get(job_id, {}))

    def _default_handler(self, payload: Any) -> dict:
        """Default job handler — simulates processing.

        In production, you'd replace this with actual business logic.

        Args:
            payload: The job payload.

        Returns:
            Dict with processing result.
        """
        # Simulate some work
        time.sleep(0.1)
        return {
            "processed": True,
            "payload_echo": payload,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _persist_job(self, job: dict) -> None:
        """Persist job data to MongoDB (best-effort).

        Args:
            job: The job dict to persist.
        """
        try:
            db = db_manager.get_db()
            if db is None:
                return
            collection = db["jobs"]
            collection.update_one(
                {"id": job.get("id")},
                {"$set": job},
                upsert=True,
            )
        except Exception as e:
            print(f"⚠️  Job persist failed: {e}")

    def shutdown(self) -> None:
        """Gracefully shutdown all worker threads."""
        self._running = False
        with self._not_empty:
            self._not_empty.notify_all()
        for worker in self._workers:
            worker.join(timeout=5.0)
