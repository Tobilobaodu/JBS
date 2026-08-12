"""SQLAlchemy ORM models for all Phase 1 tables.

Matches 03-data-model.md column definitions, types, indexes, and
constraints exactly. Uses UUID primary keys throughout.

Phase 2+ tables (job_posts, match_runs, tailored_cv_drafts, etc.)
are added in later phases — see the full entity list in 03-data-model.md.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ──────────────────────────────────────────────────────────────────────
# Auth
# ──────────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="active", nullable=False
    )  # active, suspended, deleted
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    last_active: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    access_token: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="sessions")


# ──────────────────────────────────────────────────────────────────────
# Anonymous trial support (Sprint 2)
# ──────────────────────────────────────────────────────────────────────


class TrialSession(Base):
    """An anonymous 'try before you register' identity.

    Not a User and not a UserSession — no password, no email, no login.
    Created by POST /trial-sessions, presented on subsequent requests via
    the X-Trial-Session-Id header, and reconciled into a real account by
    POST /auth/claim-trial. Short-lived by design: unclaimed rows are
    deleted by the expiry cleanup task, not kept indefinitely.
    """

    __tablename__ = "trial_sessions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    claimed_by_user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)


# ──────────────────────────────────────────────────────────────────────
# CV ingestion
# ──────────────────────────────────────────────────────────────────────


class CvFile(Base):
    __tablename__ = "cv_files"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND trial_session_id IS NULL) OR "
            "(user_id IS NULL AND trial_session_id IS NOT NULL)",
            name="ck_cv_files_exactly_one_owner",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True
    )
    trial_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("trial_sessions.id"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )  # pending, extracting, merging, parsing, completed, failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    extraction_passes: Mapped[list["CvExtractionPass"]] = relationship(
        back_populates="cv_file", cascade="all, delete-orphan"
    )
    raw_text: Mapped["CvRawText | None"] = relationship(
        back_populates="cv_file", uselist=False, cascade="all, delete-orphan"
    )


class CvExtractionPass(Base):
    __tablename__ = "cv_extraction_passes"
    __table_args__ = (
        UniqueConstraint("cv_file_id", "pass_type", "attempt_number", name="uq_passes_cv_type_attempt"),
        {"info": {"reprocess_strategy": "attempt_number"}},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    cv_file_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cv_files.id"), nullable=False, index=True
    )
    pass_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # docling, textract
    attempt_number: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )  # increment on reprocess — resolves the unique-constraint issue
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    engine: Mapped[str | None] = mapped_column(String(100), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(
        nullable=True
    )  # DECIMAL(3,2)
    characters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processing_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    cv_file: Mapped["CvFile"] = relationship(back_populates="extraction_passes")


class CvRawText(Base):
    __tablename__ = "cv_raw_text"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    cv_file_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("cv_files.id"),
        unique=True,
        nullable=False,
    )
    canonical_text: Mapped[str] = mapped_column(Text, nullable=False)
    characters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    merge_strategy: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # highest_confidence, union, manual
    merge_strategy_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    structural_validation_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    cv_file: Mapped["CvFile"] = relationship(back_populates="raw_text")


# ──────────────────────────────────────────────────────────────────────
# CV profiles (pointer + versions)
# ──────────────────────────────────────────────────────────────────────


class CvProfile(Base):
    """Fast-read pointer to the current profile version. Not a source of truth."""

    __tablename__ = "cv_profiles"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    cv_file_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("cv_files.id"),
        unique=True,
        nullable=False,
    )
    current_version_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("cv_profile_versions.id"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CvProfileVersion(Base):
    """Immutable profile snapshot. Never updated after insert (per modelling rule 1)."""

    __tablename__ = "cv_profile_versions"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND trial_session_id IS NULL) OR "
            "(user_id IS NULL AND trial_session_id IS NOT NULL)",
            name="ck_cv_profile_versions_exactly_one_owner",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    cv_file_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cv_files.id"), nullable=False, index=True
    )
    # Copied from cv_files at parse time (see worker_jobs.py cv_parse) —
    # mirrors cv_files' owner exactly, including which side is populated,
    # since a profile version can't outlive or reassign from its file.
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    trial_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("trial_sessions.id"), nullable=True, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    source_pass_ids: Mapped[list[str] | None] = mapped_column(ARRAY(UUID(as_uuid=False)), nullable=True)
    structured_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # passed, partial, failed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ──────────────────────────────────────────────────────────────────────
# Async job orchestration
# ──────────────────────────────────────────────────────────────────────


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # docling_extract, textract_extract, merge_parse, etc.
    source_entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # cv_file, job_post, match_run, etc.
    source_entity_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True
    )
    trial_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("trial_sessions.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending, queued, processing, completed, failed, retrying
    progress: Mapped[float | None] = mapped_column(
        default=0, nullable=True
    )  # 0–1
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Every current code path sets exactly one of user_id/trial_session_id;
        # unlike audit_events, processing_jobs has no genuine system-initiated
        # (neither-populated) use today, so this stays symmetric with the
        # other trial-eligible tables rather than allowing a third state.
        CheckConstraint(
            "(user_id IS NOT NULL AND trial_session_id IS NULL) OR "
            "(user_id IS NULL AND trial_session_id IS NOT NULL)",
            name="ck_processing_jobs_exactly_one_owner",
        ),
        {"info": {"polymorphic_source": True}},
    )


# ──────────────────────────────────────────────────────────────────────
# Audit (append-only, per compliance requirements)
# ──────────────────────────────────────────────────────────────────────


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True
    )
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), nullable=True
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # upload, login, parse, match, generate, approve, export_generated, etc.
    actor_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # user, admin, system_worker
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )

    __table_args__ = (
        {"info": {"append_only": True, "no_update": True, "no_delete": True}},
    )


# ──────────────────────────────────────────────────────────────────────
# Phase 2: Job post ingestion
# ──────────────────────────────────────────────────────────────────────


class JobPost(Base):
    __tablename__ = "job_posts"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND trial_session_id IS NULL) OR "
            "(user_id IS NULL AND trial_session_id IS NOT NULL)",
            name="ck_job_posts_exactly_one_owner",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True
    )
    trial_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("trial_sessions.id"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # url, text
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )  # pending, fetching, structuring, completed, failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    profile: Mapped["JobPostProfile | None"] = relationship(
        back_populates="job_post", uselist=False, cascade="all, delete-orphan"
    )


class JobPostProfile(Base):
    __tablename__ = "job_post_profiles"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    job_post_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("job_posts.id"),
        unique=True,
        nullable=False,
    )
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    required_skills: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    preferred_skills: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    responsibilities: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    qualifications: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    seniority: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # Junior, Mid, Senior, Lead, Principal — nullable, never guessed
    structured_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    job_post: Mapped["JobPost"] = relationship(back_populates="profile")


# ──────────────────────────────────────────────────────────────────────
# Phase 2: CV profile child tables
# ──────────────────────────────────────────────────────────────────────


class CvExperienceItem(Base):
    """Normalised work experience rows — keyed off cv_profile_version_id, not cv_file_id."""

    __tablename__ = "cv_experience_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    cv_profile_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("cv_profile_versions.id"),
        nullable=False,
        index=True,
    )
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current: Mapped[bool] = mapped_column(Boolean, default=False)
    bullets: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    technologies: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)


class CvEducationItem(Base):
    """Normalised education rows — keyed off cv_profile_version_id."""

    __tablename__ = "cv_education_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    cv_profile_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("cv_profile_versions.id"),
        nullable=False,
        index=True,
    )
    institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    degree: Mapped[str | None] = mapped_column(String(255), nullable=True)
    field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)


class CvSkillItem(Base):
    """Skills with optional categorisation — keyed off cv_profile_version_id."""

    __tablename__ = "cv_skill_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    cv_profile_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("cv_profile_versions.id"),
        nullable=False,
        index=True,
    )
    skill_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # technical, soft, other
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)


class CvCertificationItem(Base):
    """Normalised certification/diploma rows — keyed off cv_profile_version_id.

    Evaluated together with CvEducationItem when deciding whether the
    tailored CV's education-type section has any evidence at all — a
    certification without a formal degree still counts (see
    tailored_cv_generation.py's combined education+certification gate).
    """

    __tablename__ = "cv_certification_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    cv_profile_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("cv_profile_versions.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)


class CvProjectItem(Base):
    """Normalised personal/portfolio project rows — keyed off
    cv_profile_version_id. Deliberately kept as a distinct row_type from
    EDUCATION/CERTIFICATION in evidence_binder.py — projects are general
    technical evidence, never treated as a qualifications claim.
    """

    __tablename__ = "cv_project_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    cv_profile_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("cv_profile_versions.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    technologies: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    bullets: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)


# ──────────────────────────────────────────────────────────────────────
# CvProfileVersion extension: master CV lineage (product extension #4)
# ──────────────────────────────────────────────────────────────────────

# master_profile_id added as a nullable column on cv_profile_versions.
# This is a schema-only reservation — zero behavioural effect until the
# feature is built per 11-product-extensions.md §4.


# ──────────────────────────────────────────────────────────────────────
# Phase 3: Match engine
# ──────────────────────────────────────────────────────────────────────


class MatchRun(Base):
    __tablename__ = "match_runs"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND trial_session_id IS NULL) OR "
            "(user_id IS NULL AND trial_session_id IS NOT NULL)",
            name="ck_match_runs_exactly_one_owner",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True
    )
    trial_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("trial_sessions.id"), nullable=True, index=True
    )
    cv_profile_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cv_profile_versions.id"), nullable=False, index=True
    )
    job_post_profile_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("job_post_profiles.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )
    score: Mapped[float | None] = mapped_column(nullable=True)
    supported_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    partial_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unsupported_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contradictory_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unclear_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_requirements: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MatchEvidenceItem(Base):
    __tablename__ = "match_evidence_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    match_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("match_runs.id"), nullable=False, index=True
    )
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # required, preferred
    support_level: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # supported, partially_supported, unsupported, contradictory, unclear
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    source_references: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_feedback: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ──────────────────────────────────────────────────────────────────────
# Phase 4: Guided cover letter workflow
# ──────────────────────────────────────────────────────────────────────


class CoverLetterWorkflow(Base):
    __tablename__ = "cover_letter_workflows"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True
    )
    cv_profile_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cv_profile_versions.id"), nullable=False, index=True
    )
    job_post_profile_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("job_post_profiles.id"), nullable=False, index=True
    )
    match_run_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("match_runs.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), default="awaiting_answers", nullable=False, index=True
    )  # awaiting_answers, generating, draft_ready, approved, archived, generation_failed
    # generation_failed added Sprint 4 — distinct from CoverLetterDraft's
    # "failed" (a draft-level terminal state); this is workflow-level, so
    # /regenerate has a state to recover from rather than a permanent
    # dead end when generation genuinely fails.
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    total_steps: Mapped[int] = mapped_column(Integer, default=3)
    question_set_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CoverLetterQuestion(Base):
    __tablename__ = "cover_letter_questions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    workflow_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cover_letter_workflows.id"),
        nullable=False, index=True,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_category: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # employer_interest, motivation, relevant_example, tone_preference, availability, clarification
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    help_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_evidence_item_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("match_evidence_items.id"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class CoverLetterAnswer(Base):
    __tablename__ = "cover_letter_answers"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    workflow_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cover_letter_workflows.id"),
        nullable=False, index=True,
    )
    question_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cover_letter_questions.id"),
        nullable=False,
    )
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


class CoverLetterDraft(Base):
    __tablename__ = "cover_letter_drafts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    workflow_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cover_letter_workflows.id"),
        nullable=False, index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False
    )  # pending, generated, user_edited, approved, archived, failed
    # pending/failed added Sprint 4 — the row is created before its
    # worker runs (async generation, matching TailoredCvDraft's pattern),
    # so "row exists, worker hasn't run yet" / "worker failed" both need
    # a real value; no DB CHECK constraint exists on this column
    # (confirmed against migration 005), so this is a documentation-only
    # change, not a migration.
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_references: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    tone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ──────────────────────────────────────────────────────────────────────
# Product Extension #1: ATS structural-readiness checks
# ──────────────────────────────────────────────────────────────────────


class AtsReadinessCheck(Base):
    """ATS structural-readability score per 11-product-extensions.md §1.

    One row per check run against a specific extraction result — distinct
    from cv_raw_text.structural_validation_result, which compares Docling
    against Textract; this table evaluates the *merged* result against
    known ATS-parsing-hostile patterns.
    """

    __tablename__ = "ats_readiness_checks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    cv_file_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cv_files.id"), nullable=False,
        index=True,
    )
    cv_profile_version_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cv_profile_versions.id"),
        nullable=True, index=True,
    )
    overall_score: Mapped[float] = mapped_column(
        Numeric(3, 2), nullable=False,
    )
    checks: Mapped[list] = mapped_column(JSONB, nullable=False)
    contact_info_parseable: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False,
    )


# ──────────────────────────────────────────────────────────────────────
# Sprint 3: Tailored CV generation
# ──────────────────────────────────────────────────────────────────────


class TailoredCvDraft(Base):
    """AI-generated, job-tailored CV draft per 03-data-model.md.

    user_id/trial_session_id are nullable with an exactly-one-owner CHECK,
    same treatment as cv_files/job_posts/match_runs (Sprint 2) — generation
    is trial-session-accessible, the free-tier value delivered before the
    account wall.

    status includes 'pending'/'failed' beyond the four documented in
    05-openapi.yaml (generated/user_edited/approved/archived) — this row
    is created before its worker runs (same create-entity-then-job pattern
    as MatchRun), so it needs a "not generated yet" and a "generation
    failed" state, exactly like MatchRun.status already does.
    """

    __tablename__ = "tailored_cv_drafts"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND trial_session_id IS NULL) OR "
            "(user_id IS NULL AND trial_session_id IS NOT NULL)",
            name="ck_tailored_cv_drafts_exactly_one_owner",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True
    )
    trial_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("trial_sessions.id"), nullable=True, index=True
    )
    match_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("match_runs.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending, generated, user_edited, approved, archived, failed
    content_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    render_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    improvement_checklist: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TailoredCvSection(Base):
    """One generated section of a TailoredCvDraft.

    evidence_references is ARRAY(String), not JSONB — matching the actual
    shipped convention for this shape (match_evidence_items.source_references,
    cover_letter_drafts.evidence_references), not 03-data-model.md's literal
    JSONB claim, which is wrong for both existing precedents too.

    The non-empty CHECK constraint is new, stronger than what
    03-data-model.md specifies (app-level validation only) — belt-and-
    suspenders enforcement of the non-fabrication rule at the DB layer.
    """

    __tablename__ = "tailored_cv_sections"
    __table_args__ = (
        CheckConstraint(
            "cardinality(evidence_references) > 0",
            name="ck_tailored_cv_sections_evidence_nonempty",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_new_uuid
    )
    draft_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tailored_cv_drafts.id"), nullable=False, index=True
    )
    section_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # summary, experience, education, skills, certifications, projects
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_references: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False
    )
    generation_task: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    validation_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # passed, warning, failed
    order_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

