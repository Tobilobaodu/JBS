"""Scope the processing_jobs task_key uniqueness to ACTIVE jobs only.

Migration 013 made task_key unique across every row with a task_key,
whatever its status. But task_key is deliberately deterministic per
(job_type, entity, owner) — see compute_task_key — so the first job for a
CV permanently consumed that key: once it reached `completed` or `failed`,
every later request for the same operation hit the index and 500'd with a
UniqueViolationError.

Seen live: the dashboard's "Scoring…" never finished, because
POST /cvs/{id}/analysis raised on INSERT for a CV that had already been
analysed once during the trial.

create_processing_job's own dedup (find_active_job_by_task_key) only ever
looked at the active statuses, and its IntegrityError branch re-raises
when it can't find an active row — i.e. the code always meant "one ACTIVE
job per key", and only the index disagreed. This aligns the index with
that intent: concurrent duplicates are still refused, a re-run after the
job finishes is allowed.

CONCURRENTLY is not used: it cannot run inside Alembic's transaction, and
processing_jobs is small enough that the brief lock is not worth the
complexity of an out-of-transaction migration.

Revision ID: 022
Revises: 021
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors _ACTIVE_JOB_STATUSES in app/services/orchestration.py — keep in
# sync: a status that is active there but missing here lets two live jobs
# share a key, and the reverse resurrects the bug above.
_ACTIVE_PREDICATE = (
    "task_key IS NOT NULL AND "
    "status IN ('pending', 'queued', 'processing', 'retrying')"
)


def upgrade() -> None:
    op.drop_index("idx_processing_jobs_task_key_unique", table_name="processing_jobs")
    op.create_index(
        "idx_processing_jobs_task_key_unique",
        "processing_jobs",
        ["task_key"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_PREDICATE),
    )


def downgrade() -> None:
    # Reverting can fail where terminal rows already share a key — exactly
    # the duplicates this migration exists to permit.
    op.drop_index("idx_processing_jobs_task_key_unique", table_name="processing_jobs")
    op.create_index(
        "idx_processing_jobs_task_key_unique",
        "processing_jobs",
        ["task_key"],
        unique=True,
        postgresql_where=sa.text("task_key IS NOT NULL"),
    )
