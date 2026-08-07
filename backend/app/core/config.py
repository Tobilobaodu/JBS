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
    openai_model: str = "gpt-4o"

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

    # ClamAV
    clamd_host: str = "localhost"
    clamd_port: int = 3310

    # CORS
    cors_origin: str = "http://localhost:3000"

    model_config = {"env_file": ".env.local", "env_file_encoding": "utf-8"}


settings = Settings()