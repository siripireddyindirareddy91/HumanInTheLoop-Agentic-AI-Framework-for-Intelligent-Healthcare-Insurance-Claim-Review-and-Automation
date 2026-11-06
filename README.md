# ClaimGuard AI

Evidence-led healthcare insurance claim investigation with human-controlled decisions.

**Live demonstration:** https://claimguard-ai-rosy.vercel.app  
**Backend:** https://claimguard-api-psi.vercel.app/api/health

## Run locally

Requires Python 3.12+, Node.js 22+, and optionally Docker. No paid service or LLM key is needed.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
$env:JWT_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"
python -m alembic upgrade head
python -m uvicorn backend.main:app --reload --port 8000
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. FastAPI interactive documentation: http://localhost:8000/docs.
The application reads process environment variables; `.env` is used automatically by Docker Compose, not by the bare Python process. Export desired values before starting Python, or use `uvicorn --env-file .env` after installing `python-dotenv`.

## Demonstration accounts

All seeded accounts use **ClaimGuard!2026** unless `DEMO_PASSWORD` is configured before the initial seed.

| Email | Role |
| --- | --- |
| admin@claimguard.demo | Administrator |
| claim_reviewer@claimguard.demo | Claim reviewer |
| senior_reviewer@claimguard.demo | Senior reviewer |
| medical_reviewer@claimguard.demo | Medical reviewer |
| fraud_investigator@claimguard.demo | Investigator |
| policy_specialist@claimguard.demo | Policy specialist |
| auditor@claimguard.demo | Read-only auditor |

Registration grants only the claim reviewer role; administrator roles cannot be self-selected.

## End-to-end walkthrough

1. Sign in and submit a new claim using synthetic references and a past service date.
2. Upload a PDF, DOCX, TXT, JPG or PNG clinical document (10 MB maximum).
3. Start investigation. Eleven actual LangGraph nodes run and persist execution logs and findings.
4. Review findings, extracted document text, policy quotations, page/version references and additive risk contributions.
5. Select a policy passage using “Cite in human decision”. Enter a human-authored reason of at least 15 characters.
6. Record an approval, denial, request for information, escalation or correction. Final decisions resume the interrupted graph and are audited. Denials require administrator/senior role and cited policy evidence. No payment is executed.
7. Use Analytics to export database-derived CSV reports. Use Audit Trail to inspect events and verify the SHA-256 chain.

## Architecture and stack

```text
Next.js / React / TypeScript / Recharts / Lucide
    -> same-origin /api proxy
FastAPI / Pydantic / JWT / Argon2 / SQLAlchemy
    -> document extraction (PyMuPDF, python-docx, Tesseract)
    -> lexical hybrid retrieval (BM25 + character TF-IDF)
    -> LangGraph typed state machine / SQL checkpoints
    -> Isolation Forest and transparent rule indicators
    -> authorized human checkpoint and append-only audit
SQLite locally, PostgreSQL via DATABASE_URL in durable deployments
```

Repository layout:

```text
frontend/app/           landing, authentication and operational workspace
backend/main.py         REST API, RBAC, validation, analytics and seed data
backend/database.py     SQLAlchemy relational models and sessions
backend/security.py     Argon2, JWT, token revocation and hash-linked audit
backend/workflow.py     eleven LangGraph agents, interrupt and cold-start resume
backend/documents.py    validated upload extraction and structured patterns
backend/retrieval.py    source-preserving chunk indexing and retrieval
backend/provider.py     optional grounded server-side LLM summary adapter
backend/migrations/    initial Alembic migration
backend/tests/         end-to-end API and authorization integration tests
api/index.py           Vercel ASGI entrypoint
docs/                  architecture, API, deployment and limitations
.github/workflows/     frontend build and backend integration CI
Dockerfile             backend with Tesseract
frontend/Dockerfile    frontend production image
docker-compose.yml     frontend, backend, persistent PostgreSQL
```

## Agents and workflow

Intake → document intelligence → policy verification → coding validation → medical necessity evidence → duplicate detection → anomaly detection → risk assessment → evidence verification → decision support → human routing → conditional information queue or human review → interrupt → authorized decision → completion.

Each node uses typed state, records its actual duration and findings, and persists state to `agent_runs`. Transient connection/time-out errors retry twice; execution has a recursion limit of 30. The LangGraph memory checkpointer handles active workers; SQL state rehydrates the graph at the human checkpoint after a worker cold start. Starting an already queued/running investigation returns the existing run. A later investigation intentionally creates a new run.

Intake normalizes validated inputs; document intelligence extracts available evidence without inventing fields; policy retrieval supplies version/page citations; coding checks code syntax; medical necessity flags the need for qualified assessment; duplicates compare patient/date/procedure and explain provider/amount similarity; Isolation Forest identifies unusual profiles when at least eight records exist; risk sums exposed rule contributions; verification checks source traceability; decision support recommends an administrative next step; routing assigns medical or senior reviewers by workload.

## Database

`users` stores hashed credentials, roles and activation. `claims` links creator and assigned reviewer. `documents` stores page text and versions, optionally linked to claims. `knowledge_chunks` links searchable passages to source documents. `agent_runs` stores execution steps and durable typed workflow state. `human_reviews` links reviewer, claim, action, reason and evidence. `audit_logs` contains append-only application events and previous/current hashes. `password_reset_tokens` stores one-use expiring token hashes. `revoked_tokens` supports refresh revocation. `system_settings` is reserved for persisted configuration.

Roles are a validated user attribute; this implementation intentionally uses fewer tables than the expansive proposed schema. Document binary originals are not retained: extracted source text is stored in the database. The initial migration creates constraints, keys and indexes from model metadata.

## Environment

| Variable | Purpose |
| --- | --- |
| DATABASE_URL | SQLite or PostgreSQL SQLAlchemy URL; defaults to local SQLite |
| JWT_SECRET | Stable random server-only signing secret; required when DEMO_MODE=false |
| DEMO_MODE | Defaults true; enables fictional seed records and demo password-reset token delivery |
| DEMO_PASSWORD | Initial seeded-account password |
| CORS_ORIGINS | Comma-separated allowed frontend origins |
| BACKEND_URL | Frontend build-time backend origin used by Next.js rewrites |
| OPENAI_API_KEY | Optional server-only key for grounded draft summaries |
| LLM_MODEL | Optional model identifier; default gpt-4.1-mini |

## Tests and build

```powershell
python -m pytest backend/tests -q
cd frontend
npm run typecheck
npm run build
npm audit
```

Integration tests cover authentication, claim creation, uploads, the full eleven-agent graph, mandatory evidence, cold-start checkpoint recovery, human approval, immutability of finalized claims, audit integrity, role boundaries, retrieval, invalid files and one-use password reset. Metrics are calculated from actual database records; no clinical validation metrics are fabricated.

## Docker

Set `JWT_SECRET` in `.env`, then:

```powershell
docker compose up --build
```

Frontend: http://localhost:3000. Backend: http://localhost:8000. PostgreSQL uses the named `postgres_data` volume. The backend image installs Tesseract. Change the development database password before using any shared environment.

## Deployment

Two Vercel projects are used: root Python API and `frontend/` Next.js. Root `vercel.json` deploys the Python ASGI handler. The frontend `BACKEND_URL` must be configured at build time.

```powershell
vercel deploy --prod
cd frontend
vercel deploy --prod --build-env BACKEND_URL=https://your-api.vercel.app
```

For durable hosted records, set a PostgreSQL/Supabase pooled `DATABASE_URL` on the backend, set a stable `JWT_SECRET`, run `alembic upgrade head` against that database, then redeploy. The hosted demonstration currently uses **ephemeral SQLite under /tmp**, which may reset across cold starts and is not shared between server instances. This is a demonstration deployment, not production storage. A free Render-compatible Docker configuration is also included in `render.yaml`; point it at an existing PostgreSQL database and update frontend `BACKEND_URL`.

GitHub Actions runs checks on pushes and pull requests. Vercel Git integration requires write/admin repository access in the connected Vercel GitHub account; CLI deployment works independently.

## Material limitations

- This is a working demonstration foundation, not a clinically validated or compliance-certified enterprise deployment. Use synthetic data only.
- Hosted SQLite is ephemeral; durable SQL checkpoints require a persistent PostgreSQL database. Long investigations should use a durable task worker rather than serverless background tasks.
- Coding is format validation only: no licensed current CPT/ICD/HCPCS catalog or diagnosis/procedure compatibility data is configured.
- Medical necessity, policy applicability and effective-date interpretation remain unresolved human assessments. Retrieval does not establish coverage.
- Retrieval is lexical BM25 + character TF-IDF, not neural semantic RAG, FAISS or pgvector. Neural embeddings, reranking and Redis are not implemented.
- Isolation Forest is an unsupervised demonstration fitted to current records; no validated fraud classifier or calibrated probability exists. Labeled evaluation metrics and SHAP are not claimed.
- OCR requires the Tesseract executable; the Docker image includes it, Vercel does not. Scanned uploads fail clearly if OCR is unavailable. DOCX page numbers are logical, not original pagination.
- The optional LLM only drafts summaries, validates citation identifiers and requires human verification; no external LLM is enabled without a key.
- Password reset has no email transport. Demo mode exposes one-use reset tokens for demonstration; disable it for real environments and integrate email before deployment.
- Access is role-based within one organization; per-tenant isolation, stronger row-level controls, MFA, rate limiting, security monitoring, key rotation and independent compliance review are future work.
- Audit hashes detect changes through the application; concurrent writers need database serialization, and a privileged database administrator can rewrite the chain. External immutable anchoring is not implemented.
- PDF originals/object storage, external notifications, payments, live insurer systems, formal appeals administration and configurable policy rule execution are not integrated.

See [API reference](docs/api.md), [security](docs/security.md), and [deployment](docs/deployment.md).
