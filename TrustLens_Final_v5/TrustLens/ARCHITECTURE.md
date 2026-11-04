# TrustLens - System Design

## Request flow
Browser (static UI) -> POST /analyze -> FastAPI -> [input handler: text | URL fetch | PDF/image/video]
-> [rule engine: tone, sourcing, domain reputation] + [AI engine: Gemini or Claude, switchable]
-> score blender (70% AI, 30% rules; rules only if AI is off or fails) -> SQLite history -> JSON result.

## Design decisions
- Stateless API, config via environment variables (12-factor); AI provider is a plug-in (`AI_PROVIDER`).
- Graceful degradation: any AI failure falls back to the rule engine, so the app never hard-fails.
- Security: SSRF guard on URLs, 5 MB upload cap, output escaped in the UI, keys only in `.env`.

## Scaling path (what to change for real traffic)
1. SQLite -> PostgreSQL (history per user), add user accounts (JWT) and per-user rate limiting.
2. Run several Uvicorn/Gunicorn workers behind a load balancer; put the static UI on a CDN.
3. Move slow work (URL fetch, AI calls, video frames) to a job queue (Celery/RQ + Redis); poll or stream results.
4. Cache results by content hash in Redis to avoid repeat AI cost.
5. Add fact-check API + trusted-source search as extra scoring signals; log feedback to improve weights.
6. Add logging, metrics (Prometheus), and CI tests with Docker deployment.
