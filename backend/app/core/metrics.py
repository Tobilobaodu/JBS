"""Prometheus metrics for the extraction pipeline.

- Job throughput (counter per job_type and status)
- Processing duration (histogram per job_type)
- Failure rate (derivable from counters)

In production, expose these via a sidecar metrics HTTP server on each
worker or a shared Pushgateway. For local dev, the API /metrics endpoint
serves API-side metrics plus these custom metrics in the same process.
"""

from prometheus_client import Counter, Histogram

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