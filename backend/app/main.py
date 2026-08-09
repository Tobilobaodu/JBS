"""FastAPI application entry point.

Mounts all API routers under /api/v1, sets up CORS, structured logging,
and Prometheus metrics. Entry point for both the API server (uvicorn)
and the Celery workers (via app.workers.tasks.celery_app).
"""

from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.core import metrics as _metrics  # noqa: F401 — register Prometheus metrics
from app.core.storage import ensure_bucket_exists
from app.api.v1.auth import router as auth_router
from app.api.v1.cvs import router as cvs_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.job_posts import router as job_posts_router
from app.api.v1.matches import router as matches_router
from app.api.v1.cover_letters import router as cover_letters_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: setup and teardown."""
    setup_logging()
    logger.info("app_starting", environment=settings.environment)
    # Ensure S3 bucket exists (local MinIO auto-creates)
    try:
        await ensure_bucket_exists()
    except Exception:
        logger.warning("bucket_setup_skipped", reason="storage may not be available yet")
    yield
    logger.info("app_shutting_down")


app = FastAPI(
    title="AI CV Tailoring and Cover Letter Platform",
    description="Backend API for CV ingestion, extraction, matching, and generation.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — in local dev, also allow null origin (file:// pages) for the test harness
_cors_origins = [settings.cors_origin]
if settings.environment == "local":
    _cors_origins.append("null")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Correlation ID middleware — inject a correlation_id into every request
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    import structlog

    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(correlation_id=corr_id)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = corr_id
    return response


# Standard error handler — returns the ErrorResponse envelope
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    from datetime import datetime, timezone

    logger.error("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "status": 500,
            "code": "INTERNAL_ERROR",
            "message": "An internal error occurred.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(request.url.path),
        },
    )


# Mount routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(cvs_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(job_posts_router, prefix="/api/v1")
app.include_router(matches_router, prefix="/api/v1")
app.include_router(cover_letters_router, prefix="/api/v1")

# Prometheus metrics at /metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health")
async def health():
    """Health check endpoint. Returns 200 if the API is running."""
    return {"status": "ok", "environment": settings.environment}