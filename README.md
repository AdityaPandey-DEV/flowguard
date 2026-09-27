# FlowGuard

**Production-grade rate limiter and async job queue built from scratch — 1000+ req/s, no Redis, no Celery.**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=flat-square&logo=flask&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?style=flat-square&logo=react&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)

---

## What It Does

FlowGuard implements two critical backend infrastructure components using only Python standard library data structures:

| Component | Implementation | Complexity |
|---|---|---|
| **Sliding Window Rate Limiter** | `collections.deque` | O(1) amortized |
| **Priority Job Queue** | `heapq` with worker threads | O(log n) |

**Key Specs:**
- **1000+ req/s** on a single Flask instance
- **Exponential backoff** — failed jobs retry: 1s → 2s → 4s
- **Thread-safe** — `threading.Lock()` + `Condition` on all shared state
- **MongoDB persistence** — best-effort sync every 30s, works without DB (graceful degradation)
- **Real-time dashboard** — React + recharts, auto-refresh every 5s

## Architecture

```
React Dashboard (Vercel) ── fetch/5s ──→ Flask API (Render)
                                            ├── Sliding Window Rate Limiter (deque)
                                            ├── Priority Job Queue (heapq + worker threads)
                                            └── MongoDB Atlas (optional persistence)
```

## Tech Stack

| Component | Technology |
|---|---|
| Backend | Python 3.11+, Flask |
| Rate Limiter | `collections.deque` (O(1)) |
| Job Queue | `heapq` (O(log n)) + `threading` |
| Database | MongoDB Atlas (optional) |
| Dashboard | React + recharts |
| Deployment | Docker, Render + Vercel |

## My Role

I selected the sliding window algorithm over token bucket, designed the thread synchronization strategy, and planned the graceful degradation model (works with or without MongoDB). Code generation was accelerated using AI tools; algorithm selection, concurrency design, and debugging are mine.

## Quick Start

```bash
git clone https://github.com/AdityaPandey-DEV/flowguard.git && cd flowguard
cp .env.example .env   # Add MongoDB URI
docker-compose up       # Or: cd backend && python app.py
```

---

<div align="center">

*Architected & built by [Aditya Pandey](https://github.com/AdityaPandey-DEV) — AI-augmented development*

</div>
