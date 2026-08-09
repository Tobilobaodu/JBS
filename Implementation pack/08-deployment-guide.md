# Deployment Guide

## 1. Open decisions before this guide can be finalised

A few values below are written as concrete config because a developer needs *something* to build against, not because they're settled. Confirm these before Phase 5 (or earlier, since some affect Phase 1 setup):

| Decision | Placeholder used below | Why it's open |
|---|---|---|
| LLM provider and model | `OPENAI_MODEL=gpt-4o` | The source scope only requires "structured-output-capable" — no provider was committed to. Pin this early since it affects the cost estimate in `02-architecture-overview.md` §10 and which schema-validation library fits best. |
| Export file formats | `pdf`, `docx` | Not specified in the original scope of work, which treats rendering/export as backend-adjacent but doesn't commit to specific formats or templates. Confirm before building `POST /exports/*` beyond the identifier-return stub. |
| Cost alert thresholds | `$100`/day Textract, `$200`/day LLM | Round numbers for illustration, not derived from projected usage. Recalculate once Phase 1–2 gives real per-user volume, using the per-run estimate in `02-architecture-overview.md` §10 as the starting multiplier. |
| Endpoint-tier rate limit values | `RATE_LIMIT_AUTH_REQUESTS=5`, `RATE_LIMIT_UPLOAD_REQUESTS=10`, etc. | Illustrative starting points for the tiered rate-limiting structure required in `10-security-plan.md` §6, not measured against real usage or abuse patterns. The tiering itself (separate limits per cost/risk profile) is the actual requirement; the numbers should be tuned once real traffic exists. |

Everything else in this guide is a reasonable default a developer can build against directly.

## 2. Environments

| Environment | Example base URL |
|---|---|
| Local | `http://localhost:8000` |
| Staging | `https://staging.api.example.com` |
| Production | `https://api.example.com` |

Replace `example.com` with the real domain once registered; the pattern (separate staging/production, versioned API path) is what matters.

## 3. Component summary

| Component | Technology |
|---|---|
| API service | Python + FastAPI, containerised |
| Background workers | Python, separate containers per job type — same language and dependency tooling as the API, per `01-implementation-plan.md` §2 |
| Database | PostgreSQL 15+ |
| Database access / migrations | SQLAlchemy + Alembic |
| Object storage | AWS S3 or equivalent |
| Queue | Celery (with Redis or SQS as the broker) or AWS SQS directly with a lighter dispatch layer, depending on how much workflow control the team needs |
| Cache | Redis |
| OCR | Amazon Textract (managed), via boto3 |
| Self-hosted parser | Docling, in its own worker container — see `02-architecture-overview.md` §4a for the container base, CPU/memory sizing, and swappable-interface design |
| LLM integration | Structured-output-capable provider — see open decision above |
| Authentication | JWT-based |

## 4. Local environment setup

```bash
# Clone
git clone git@github.com:your-org/cv-tailoring-backend.git
cd cv-tailoring-backend

# Virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install
pip install -r requirements.txt

# Environment config
cp .env.example .env.local
# Edit .env.local with real values

# Migrations
alembic upgrade head

# Seed (optional, for local test data)
python -m scripts.seed

# Start
uvicorn app.main:app --reload
```

`.env.example` should be committed with placeholder values and documented keys; `.env.local` never is (see `06-non-functional-requirements.md` §4 on secrets).

## 5. Environment variables

```bash
ENVIRONMENT=production
APP_NAME=cv-tailoring-backend
PORT=8000
LOG_LEVEL=info

DATABASE_URL=postgresql://user:password@host:5432/database
REDIS_URL=redis://localhost:6379

AWS_REGION=us-west-2
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
S3_BUCKET_NAME=cv-tailoring-storage

TEXTRACT_ENABLED=true

# LLM provider - see open decision in section 1 before treating this as final
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-4o

JWT_SECRET=your_secret
JWT_EXPIRY=3600

# General API rate limit (coarse layer)
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60

# Endpoint-tier rate limits (fine layer) — see 10-security-plan.md section 6.
# A single global limit is too loose for expensive/abuse-prone endpoints and
# too tight for cheap read endpoints; tune these independently.
RATE_LIMIT_AUTH_REQUESTS=5
RATE_LIMIT_AUTH_WINDOW=60
RATE_LIMIT_UPLOAD_REQUESTS=10
RATE_LIMIT_UPLOAD_WINDOW=3600
RATE_LIMIT_GENERATION_REQUESTS=20
RATE_LIMIT_GENERATION_WINDOW=3600
RATE_LIMIT_URL_FETCH_REQUESTS=20
RATE_LIMIT_URL_FETCH_WINDOW=3600

# Max concurrent in-flight processing jobs per user, independent of the
# submission rate limit above — see 10-security-plan.md section 6.
MAX_CONCURRENT_JOBS_PER_USER=5

CORS_ORIGIN=https://app.example.com
```

The auth/upload/generation/url-fetch limits above are starting points, not measured values — same caveat as the cost thresholds in §1: tune against real traffic once Phase 1–2 data exists. What matters structurally is that they're separate from the general limit, not the specific numbers.

In production, every secret-shaped value here (`AWS_SECRET_ACCESS_KEY`, `OPENAI_API_KEY`, `JWT_SECRET`, `DATABASE_URL`) comes from the managed secrets vault at deploy time, not from a committed or long-lived `.env` file — `.env.local` is a local-dev convenience only.

## 6. Worker configuration

Per-queue concurrency, retry, and timeout settings — starting points, tune against real job durations once Phase 1–3 are live:

```json
{
  "queues": {
    "docling_extract": { "concurrency": 5, "maxRetries": 3, "timeout": 60000 },
    "textract_extract": { "concurrency": 10, "maxRetries": 2, "timeout": 120000 },
    "merge_parse": { "concurrency": 5, "maxRetries": 3, "timeout": 30000 },
    "job_post_parse": { "concurrency": 5, "maxRetries": 3, "timeout": 30000 },
    "match": { "concurrency": 5, "maxRetries": 3, "timeout": 60000 },
    "cv_generate": { "concurrency": 3, "maxRetries": 2, "timeout": 90000 },
    "cover_letter_generate": { "concurrency": 3, "maxRetries": 2, "timeout": 90000 },
    "export": { "concurrency": 5, "maxRetries": 2, "timeout": 60000 }
  }
}
```

Textract gets the highest concurrency allowance since it's a managed external call (I/O-bound, not compute-bound on our infrastructure); generation queues get the lowest concurrency and highest timeout since they're the most expensive and slowest steps. The `docling_extract` concurrency of 5 is the figure the container CPU/memory sizing in `02-architecture-overview.md` §4a is built around — if concurrency changes, revisit that sizing rather than assuming it still holds, since total worker pool resource need is per-instance sizing × concurrency.

## 7. Deployment steps

**Staging:**
1. Build containers.
2. Push to registry.
3. Run migrations against the staging database.
4. Deploy the service.
5. Verify the health endpoint.
6. Run smoke tests (see checklist in section 12).

**Production:**
1. Tag the release.
2. Cut a release branch.
3. Deploy blue-green (or equivalent zero-downtime strategy).
4. Monitor error rate and queue depth closely for the first hour.
5. Keep the rollback path ready (see section 11) rather than assuming it won't be needed.

## 8. Database migrations

- Review every migration before it goes to staging, particularly anything touching `cv_profile_versions`, `match_runs`, or evidence-reference columns, given how much downstream logic depends on those shapes staying correct (see `03-data-model.md` section 4).
- Test on staging first, always.
- Apply to production during a low-traffic window.
- Verify schema post-migration before declaring the deploy complete.
- Have an explicit rollback migration ready before applying, not written after something breaks.

## 9. Monitoring

This section plus `10-security-plan.md` §10 (attack-pattern-specific detection) and §12 (incident response runbook) together form this pack's monitoring and alerting guidance. There's no separate standalone runbook document — the content is split by concern (operational health here, security detection and incident response there) rather than duplicated into a fourth file. If a dedicated on-call runbook is wanted later, it should assemble from these three sources rather than restate them.

**Key metrics:**
- API: request rate, latency (p50/p95/p99), error rate by status code.
- Workers: queue depth per job type, processing duration per job type, success/failure rate.
- Database: connection pool utilisation, slow query log, query performance on the high-write tables (`cv_profile_versions`, `match_evidence_items`, `audit_events`).
- External: Textract call volume and cost, LLM token usage and cost per generation type (CV draft vs. cover letter, track separately, since they have different cost profiles per section 10 of the architecture doc).

**Suggested alert thresholds** (tune once real traffic exists):

| Condition | Alert |
|---|---|
| API error rate > 5% for 5 min | Page |
| Queue depth > 1000 for 10 min | Page |
| Worker failure rate > 10% for 10 min | Page |
| DB connection pool > 80% | Warn |
| Textract daily cost exceeds threshold | Warn - see open decision in section 1 |
| LLM daily cost exceeds threshold | Warn - see open decision in section 1 |

Security-specific alert patterns (credential stuffing, IDOR probing, SSRF probing, injection attempts) are covered separately in `10-security-plan.md` §10, since they need different thresholds and different responders than the operational alerts above.

## 10. Performance baseline (targets, not guarantees)

Indicative targets to design against, validate against real measurements once Phase 3 is live, and revise rather than treating these as fixed SLAs from day one:

| Operation | Target |
|---|---|
| CV upload (acceptance, not processing) | < 100ms |
| Docling first-pass extraction | < 5s |
| Textract pass (2-page document) | < 10s |
| Merge + structural validation | < 5s |
| Match analysis | < 15s |
| Tailored CV generation | < 20s |
| Cover letter generation | < 20s |
| API p95 latency (excluding async job endpoints) | < 100ms |
| Worker throughput | 50 jobs/min per queue, baseline |

## 11. Rollback plan

- **Immediate:** revert to the previous container image; roll back the most recent migration if it's implicated.
- **Gradual:** shift traffic back to the prior deployment, investigate the issue in parallel, deploy a fix rather than a second rollback attempt under pressure.
- **Data recovery:** restore from the most recent backup if a migration or bad deploy corrupted data. This is why testing migrations on staging first (section 8) matters more than it might seem.

## 12. Post-deployment checklist

- [ ] Health endpoint returns 200
- [ ] Authentication flow works end to end (register/login/me)
- [ ] CV upload accepted and processing job created
- [ ] Queue is processing jobs (check queue depth is draining, not just non-zero)
- [ ] Migrations applied and schema verified
- [ ] Cache (Redis) reachable and functional
- [ ] External integrations reachable: object storage, Textract, LLM provider
- [ ] Logs flowing to the centralised log destination
- [ ] Alerts configured and firing correctly on a test condition
- [ ] Cost tracking active for Textract and LLM usage
- [ ] Smoke tests pass (upload, extraction, parsed profile, at minimum)
- [ ] Documentation updated to reflect anything that changed during this deploy
