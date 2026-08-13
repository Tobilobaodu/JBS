"""Application configuration via Pydantic Settings.

Loads from environment / .env files. Secret-shaped values (DB creds,
AWS keys, JWT secrets) must come from env — never hardcoded defaults.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    app_name: str = "cv-tailoring-backend"
    port: int = 8000
    log_level: str = "info"
    environment: str = "local"

    # Database
    database_url: str = ""
    database_url_async: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_bucket_name: str = "cv-tailoring-local"

    # MinIO (S3-compatible local)
    minio_endpoint: str = "http://localhost:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin"

    # Textract
    textract_enabled: bool = False

    # LLM (Phase 3)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_request_timeout_seconds: int = 30

    # Tailored CV generation (Sprint 3)
    tailored_cv_evidence_overlap_threshold: float = 0.35
    tailored_cv_max_generation_retries: int = 2
    tailored_cv_max_experience_items: int = 6
    tailored_cv_max_project_items: int = 4

    # Cover letter generation (Sprint 4)
    # Independently tunable from tailored_cv's threshold above — letters
    # carry more connective/boilerplate prose ("Dear Hiring Manager,",
    # "Thank you for your consideration") than CV bullets, which could
    # dilute token-overlap ratios differently. Provisional starting
    # value, not yet measured against real generated letters.
    cover_letter_llm_generation_enabled: bool = True
    cover_letter_evidence_overlap_threshold: float = 0.30
    cover_letter_max_generation_retries: int = 2
    cover_letter_fallback_max_stories: int = 2
    cover_letter_min_word_count: int = 100
    cover_letter_max_word_count: int = 350

    # Job post LLM skill-extraction enrichment (M3)
    # Only called when the rules-based+taxonomy parse (M1/M2) finds fewer
    # than this many combined required_skills+qualifications — targets
    # exactly the prose-heavy-posting gap M1/M2 can't close, rather than
    # spending an LLM call on every job post regardless of need.
    job_post_llm_enrichment_enabled: bool = True
    job_post_llm_enrichment_min_requirements: int = 3
    # Average word count above which extracted required_skills/
    # qualifications are judged to be prose sentences rather than skill
    # terms (verified against a real posting: 8 "qualifications" at
    # 11-24 words each — a healthy *count* that still needed enrichment,
    # since count alone doesn't catch this failure mode).
    job_post_llm_enrichment_prose_word_threshold: int = 9
    job_post_llm_evidence_overlap_threshold: float = 0.4

    # JWT
    jwt_secret: str = ""
    jwt_expiry: int = 3600

    # Rate limiting (tiered)
    rate_limit_requests: int = 100
    rate_limit_window: int = 60
    rate_limit_auth_requests: int = 5
    rate_limit_auth_window: int = 60
    rate_limit_upload_requests: int = 10
    rate_limit_upload_window: int = 3600
    rate_limit_generation_requests: int = 20
    rate_limit_generation_window: int = 3600
    rate_limit_url_fetch_requests: int = 20
    rate_limit_url_fetch_window: int = 3600
    max_concurrent_jobs_per_user: int = 5

    # Trial session creation (Sprint 2) — deliberately tighter than the
    # other tiers: this is the one unauthenticated way to mint a new
    # identity that can then consume upload/generation/url_fetch budget.
    rate_limit_trial_session_requests: int = 5
    rate_limit_trial_session_window: int = 3600
    trial_session_ttl_hours: int = 48
    trial_session_cleanup_interval_seconds: int = 3600

    # ClamAV
    clamd_host: str = "localhost"
    clamd_port: int = 3310

    # Exports (Sprint 5) — Gotenberg does DOCX→PDF conversion, called
    # over the internal Docker network only (no internet egress needed,
    # same isolation posture as the CV-parsing workers).
    gotenberg_url: str = "http://gotenberg:3000"
    gotenberg_request_timeout_seconds: int = 30

    # Pushgateway (Sprint 6 live-fire finding) — counters that only ever
    # increment inside Celery worker processes (SSRF rejections, generation
    # schema-validation failures, real API spend) are invisible to Prometheus
    # otherwise, since it only scrapes the api service. See
    # app/core/metrics_push.py.
    pushgateway_url: str = "http://pushgateway:9091"

    # CORS
    cors_origin: str = "http://localhost:3000"

    model_config = {"env_file": ".env.local", "env_file_encoding": "utf-8"}


settings = Settings()