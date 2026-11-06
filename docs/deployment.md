# Deployment operations

The production demonstration uses two Vercel projects: `claimguard-api` (repository root) and `claimguard-ai` (`frontend/`). Keep `.vercel/` files untracked. Set backend JWT_SECRET using the Vercel secret environment UI/CLI, never source control. Set frontend BACKEND_URL at build time, then rebuild when it changes.

Vercel Python functions can execute the included FastAPI handler and dependencies. They have finite execution limits and do not provide shared durable filesystem storage. Default `/tmp/claimguard.db` is deliberately labeled ephemeral in `/api/health` and the UI. It can reset or diverge between instances. This is suitable for a synthetic demonstration, not real claims.

For durable deployment, configure a pooled PostgreSQL connection (including required TLS parameters) through DATABASE_URL, migrate with `python -m alembic upgrade head`, and redeploy. Set DEMO_MODE=false and create authorized accounts through an administrator-controlled provisioning process before serving real workloads; public registration defaults to reviewer role and must be replaced with organization approval for a real system. Seed creation is disabled outside demo mode.

For long-running extraction or investigation, deploy the Docker backend to a persistent service (the included Render blueprint is a starting point) and add a durable task queue. Docker includes OCR; Vercel requires an external OCR provider for scanned documents. The current hosted deployment fails clearly when Tesseract is missing.

Run `docker compose up --build` locally for persistent PostgreSQL and OCR. Docker configuration has not been certified for a regulated production environment.

Manual deployment is independent of Vercel's GitHub integration. If automatic linking fails, configure the Vercel GitHub application with repository write access, set each project's correct root directory, and connect the repository after reviewing CI.
