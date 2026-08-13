"""Prometheus metrics for the extraction pipeline.

- Job throughput (counter per job_type and status)
- Processing duration (histogram per job_type)
- Failure rate (derivable from counters)

In production, expose these via a sidecar metrics HTTP server on each
worker or a shared Pushgateway. For local dev, the API /metrics endpoint
serves API-side metrics plus these custom metrics in the same process.

Sprint 6 live-fire verification found this docstring's own caveat was real:
Prometheus only scrapes the API process (prometheus.yml has one target,
api:8000) — counters incremented inside Celery worker processes were
provably never reaching Prometheus (confirmed via a genuine SSRF rejection
that never showed up as a nonzero rate()). SSRF_REJECTED_COUNTER,
GENERATION_SCHEMA_VALIDATION_FAILED_COUNTER, and COST_USD_COUNTER only
increment in worker code, so those three are also pushed to a Pushgateway
(app/core/metrics_push.py) right after the local .inc() — see PUSH_REGISTRY
below. QUEUE_DEPTH_GAUGE avoids the problem entirely by living in and being
updated from the API process itself (app/main.py's lifespan), since queue
depth is a property of the database, not of any one worker.
"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

JOB_THROUGHPUT = Counter(
    "processing_jobs_total",
    "Total processing jobs completed, by type and status",
    ["job_type", "status"],
)

JOB_DURATION_SECONDS = Histogram(
    "processing_job_duration_seconds",
    "Processing job duration in seconds, by job_type",
    ["job_type"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0),
)

EXTRACTION_CHARS = Histogram(
    "extraction_characters",
    "Number of characters extracted, by pass_type",
    ["pass_type"],
    buckets=(100, 500, 1000, 2000, 5000, 10000, 20000, 50000),
)

MERGE_STRATEGY_COUNTER = Counter(
    "merge_strategy_used_total",
    "Which merge strategy was selected",
    ["strategy"],
)

STRUCTURAL_ANOMALY_COUNTER = Counter(
    "structural_anomalies_total",
    "Structural anomalies detected during merge validation",
    ["anomaly_detected"],
)

LLM_TOKENS_COUNTER = Counter(
    "llm_tokens_total",
    "LLM tokens used, by generation task and token type",
    ["generation_task", "token_type"],
)

LLM_GENERATION_COUNTER = Counter(
    "llm_generations_total",
    "LLM generation calls, by generation task and outcome",
    ["generation_task", "outcome"],
)

# ── Security / attack-pattern counters (Sprint 6, Workstream H) ─────────────
# These back the 5 alert patterns in prometheus/alert_rules.yml — §10 names
# them explicitly. They are intentionally counters (monotonic) so PromQL
# rate()/increase() can window them, not gauges.

AUTH_FAILURE_COUNTER = Counter(
    "auth_failures_total",
    "Authentication failures, by reason",
    ["reason"],  # wrong_password | unknown_email | expired_token | revoked_token
)

AUTHZ_DENIED_COUNTER = Counter(
    "authz_denied_total",
    "Cross-user resource access denials (IDOR probing / ownership 404s)",
)

SSRF_REJECTED_COUNTER = Counter(
    "ssrf_rejected_total",
    "SSRF-safe-fetch validation rejections",
)

GENERATION_SCHEMA_VALIDATION_FAILED_COUNTER = Counter(
    "generation_schema_validation_failed_total",
    "Generation schema-validation failures (possible prompt-injection attempts)",
)

# ── Queue depth (fixes QueueDepthSpike, which referenced a label value —
# status="queued" — that processing_jobs_total never actually emits; the
# counter is only ever incremented with status="completed"/"failed", and
# only from within worker processes). This gauge is updated periodically
# from the database by app/main.py's lifespan, in the API process, so it
# needs no Pushgateway.
QUEUE_DEPTH_GAUGE = Gauge(
    "processing_queue_depth",
    "Current count of not-yet-completed processing jobs, by job_type",
    ["job_type"],
)

# ── HTTP request latency (API process only — matches every other route
# handler's request/response cycle, not worker task duration, which
# JOB_DURATION_SECONDS already covers). Route template (e.g. "/cvs/{cv_id}"),
# not the raw path, to keep cardinality bounded across id-scoped routes.
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds, by method, route, and status code",
    ["method", "route", "status_code"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ── Real spend on paid external APIs (Textract, OpenAI), by call type.
# Token-based for LLM calls (real prompt_tokens/completion_tokens against
# documented gpt-4o-mini per-token pricing), per-page for Textract (real
# AWS DetectDocumentText per-page pricing) — see the increment sites in
# worker_jobs.py for the actual rates used.
COST_USD_COUNTER = Counter(
    "cost_usd_total",
    "Estimated real USD spend on paid external APIs, by call_type",
    ["call_type"],  # textract | cv_generate | cover_letter_generate
)

# ── Pushgateway registry: only the worker-side counters that Prometheus
# can't otherwise see. Deliberately NOT the whole default REGISTRY —
# JOB_THROUGHPUT etc. stay local-only-and-unscraped for now (a known,
# separate, lower-priority gap; not one of the 5 §10 alert patterns) so a
# partial per-worker snapshot of it doesn't leak into Pushgateway and look
# like a complete picture on a future dashboard.
PUSH_REGISTRY = CollectorRegistry()
PUSH_REGISTRY.register(SSRF_REJECTED_COUNTER)
PUSH_REGISTRY.register(GENERATION_SCHEMA_VALIDATION_FAILED_COUNTER)
PUSH_REGISTRY.register(COST_USD_COUNTER)