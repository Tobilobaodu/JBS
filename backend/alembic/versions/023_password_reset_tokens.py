"""Password reset tokens.

One row per "forgot password" email sent. Only the SHA-256 of the token is
stored (same scheme as user_sessions' token hashes), so a database read
does not yield a usable reset link. A token is single-use (used_at) and
short-lived (expires_at); issuing a new one marks the user's older unused
tokens used, so only the latest emailed link works.

New table only — no existing rows are touched. app_runtime gets access via
017's ALTER DEFAULT PRIVILEGES. No RLS policy, matching user_sessions: this
is auth plumbing read before a user identity exists, not an owned resource
(see 018's table list).

Revision ID: 023
Revises: 022
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_ip", sa.String(45), nullable=True),
    )
    # Serves the per-account throttle ("reset emails in the last hour") and
    # the "supersede older tokens" update — both filter on user_id.
    op.create_index(
        "ix_password_reset_tokens_user_id_created_at",
        "password_reset_tokens",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_password_reset_tokens_user_id_created_at",
        table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")
