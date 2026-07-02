"""
FlowGuard — Flask API Server

Production-grade rate limiter and async job queue API.
All routes are prefixed with /api for clean separation.

Architecture:
    Client → Flask API → Rate Limiter (sliding window)
                       → Job Queue (priority heap + workers)
                       → MongoDB Atlas (persistence, best-effort)
"""

import os
import time
import uuid
import secrets
from datetime import datetime, timezone
from collections import deque
from threading import Lock

from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

# Load .env file before importing config
load_dotenv()

from config import config
from rate_limiter import SlidingWindowRateLimiter
from job_queue import PriorityJobQueue
from database import db_manager

# ─── App Initialization ───────────────────────────────────────────────
app = Flask(__name__)
CORS(app)  # Allow frontend (Vercel) to call backend (Render)

# ─── Core Components ──────────────────────────────────────────────────
rate_limiter = SlidingWindowRateLimiter(sync_interval=30)
job_queue = PriorityJobQueue(
    max_queue_size=config.MAX_QUEUE_SIZE,
    num_workers=config.WORKER_THREADS,
)

# ─── Client Registry ─────────────────────────────────────────────────
# In-memory store for registered clients: {client_id: {api_key, limit_per_minute}}
registered_clients: dict = {}
clients_lock = Lock()

# ─── Request Stats Tracking ──────────────────────────────────────────
# Track timestamps of recent requests for requests-per-second calculation
request_timestamps: deque = deque()
stats_lock = Lock()
RPS_WINDOW = 60  # Track requests over the last 60 seconds


def record_request() -> None:
    """Record a request timestamp for RPS calculation."""
    now = time.time()
    with stats_lock:
        request_timestamps.append(now)
        # Clean up timestamps older than RPS_WINDOW
        cutoff = now - RPS_WINDOW
        while request_timestamps and request_timestamps[0] < cutoff:
            request_timestamps.popleft()


def get_rps() -> float:
    """Calculate current requests per second (averaged over last 60s)."""
    now = time.time()
    with stats_lock:
        cutoff = now - RPS_WINDOW
        while request_timestamps and request_timestamps[0] < cutoff:
            request_timestamps.popleft()
        count = len(request_timestamps)
    return round(count / RPS_WINDOW, 2) if RPS_WINDOW > 0 else 0.0


def get_rps_history() -> list:
    """Get per-second request counts for the last 60 seconds.

    Returns a list of 60 integers, each representing the number of
    requests in that second. Index 0 = 60 seconds ago, index 59 = now.
    """
    now = time.time()
    buckets = [0] * 60
    with stats_lock:
        for ts in request_timestamps:
            age = int(now - ts)
            if 0 <= age < 60:
                buckets[59 - age] += 1
    return buckets


# ─── API Routes ────────────────────────────────────────────────────────


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint.

    Returns:
        200: {status: "ok", mongo: bool, uptime: str}
    """
    return jsonify(
        {
            "status": "ok",
            "mongo_connected": db_manager.is_connected(),
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.route("/api/clients/register", methods=["POST"])
def register_client():
    """Register a new API client with a rate limit.

    Request Body:
        {
            "client_id": "my-service" (optional, auto-generated if omitted),
            "limit_per_minute": 100 (optional, uses default from config)
        }

    Returns:
        201: {client_id, api_key, limit_per_minute}
    """
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id", f"client-{uuid.uuid4().hex[:8]}")
    limit = data.get("limit_per_minute", config.RATE_LIMIT_DEFAULT)

    # Generate a secure API key
    api_key = secrets.token_urlsafe(32)

    with clients_lock:
        registered_clients[client_id] = {
            "api_key": api_key,
            "limit_per_minute": limit,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }

    # Persist to MongoDB (best-effort)
    try:
        db = db_manager.get_db()
        if db:
            db["clients"].update_one(
                {"client_id": client_id},
                {
                    "$set": {
                        "client_id": client_id,
                        "api_key": api_key,
                        "limit_per_minute": limit,
                        "registered_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
                upsert=True,
            )
    except Exception:
        pass  # Non-critical — client is still registered in-memory

    return (
        jsonify(
            {
                "client_id": client_id,
                "api_key": api_key,
                "limit_per_minute": limit,
                "message": "Client registered successfully. Include api_key in X-API-Key header.",
            }
        ),
        201,
    )


@app.route("/api/request", methods=["POST"])
def handle_request():
    """Process a rate-limited request.

    Headers:
        X-Client-ID: The client identifier
        X-API-Key: The client's API key (optional in dev mode)

    Request Body:
        Any JSON payload to process.

    Returns:
        200: {allowed: true, remaining: int, payload_received: ...}
        429: {allowed: false, retry_after: float, message: str}
    """
    record_request()

    client_id = request.headers.get("X-Client-ID", "anonymous")

    # Look up client's rate limit (or use default)
    with clients_lock:
        client_info = registered_clients.get(client_id, {})
    limit = client_info.get("limit_per_minute", config.RATE_LIMIT_DEFAULT)
    window = config.RATE_LIMIT_WINDOW

    # Check rate limit
    allowed, retry_after = rate_limiter.is_allowed(
        client_id=client_id,
        limit=limit,
        window_seconds=window,
    )

    if not allowed:
        return (
            jsonify(
                {
                    "allowed": False,
                    "retry_after": round(retry_after, 2),
                    "message": f"Rate limit exceeded. Try again in {retry_after:.1f} seconds.",
                }
            ),
            429,
        )

    # Request is allowed
    payload = request.get_json(silent=True) or {}
    remaining = limit - rate_limiter.get_client_usage(client_id, window)

    return jsonify(
        {
            "allowed": True,
            "remaining_requests": max(0, remaining),
            "payload_received": payload,
            "client_id": client_id,
        }
    )


@app.route("/api/jobs", methods=["POST"])
def submit_job():
    """Submit a job to the priority queue.

    Request Body:
        {
            "payload": { ... any data ... },
            "priority": "high" | "medium" | "low"  (default: "medium")
        }

    Returns:
        201: {job_id, status: "queued", priority}
        400: {error: "..."} if invalid priority
        503: {error: "Queue is full"} if queue capacity reached
    """
    record_request()

    data = request.get_json(silent=True) or {}
    payload = data.get("payload", data)
    priority = data.get("priority", "medium")

    try:
        job_id = job_queue.submit(payload=payload, priority=priority)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if job_id is None:
        return jsonify({"error": "Queue is full. Try again later."}), 503

    return (
        jsonify(
            {
                "job_id": job_id,
                "status": "queued",
                "priority": priority,
                "message": f"Job submitted. Track status at /api/jobs/{job_id}",
            }
        ),
        201,
    )


@app.route("/api/jobs/<job_id>", methods=["GET"])
def get_job_status(job_id: str):
    """Get the status and result of a job.

    Path Parameters:
        job_id: The unique job identifier.

    Returns:
        200: Full job object including status, result, error, retries.
        404: {error: "Job not found"}
    """
    job = job_queue.get_job(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    """List recent jobs.

    Query Parameters:
        limit: Number of jobs to return (default: 50, max: 200)

    Returns:
        200: {jobs: [...], total: int}
    """
    limit = min(int(request.args.get("limit", 50)), 200)
    jobs = job_queue.get_recent_jobs(limit=limit)
    return jsonify({"jobs": jobs, "total": len(jobs)})


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Get combined statistics from rate limiter and job queue.

    Returns:
        200: {
            requests_per_second: float,
            rps_history: [int * 60],  (per-second counts for the last 60s)
            rate_limiter: { ... },
            job_queue: { ... },
            top_clients: [...]
        }
    """
    rl_stats = rate_limiter.get_stats()
    jq_stats = job_queue.get_stats()

    # Get top clients by usage
    top_clients = []
    with clients_lock:
        for cid in list(registered_clients.keys())[:10]:
            usage = rate_limiter.get_client_usage(cid, config.RATE_LIMIT_WINDOW)
            top_clients.append({"client_id": cid, "requests_in_window": usage})

    top_clients.sort(key=lambda c: c["requests_in_window"], reverse=True)

    return jsonify(
        {
            "requests_per_second": get_rps(),
            "rps_history": get_rps_history(),
            "rate_limiter": rl_stats,
            "job_queue": jq_stats,
            "top_clients": top_clients[:5],
        }
    )


# ─── Error Handlers ───────────────────────────────────────────────────


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error"}), 500


# ─── Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"🚀 FlowGuard starting on port {config.PORT}")
    print(f"   Rate limit: {config.RATE_LIMIT_DEFAULT} req/{config.RATE_LIMIT_WINDOW}s")
    print(f"   Queue size: {config.MAX_QUEUE_SIZE}")
    print(f"   Workers: {config.WORKER_THREADS}")
    app.run(
        host="0.0.0.0",
        port=config.PORT,
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
    )
