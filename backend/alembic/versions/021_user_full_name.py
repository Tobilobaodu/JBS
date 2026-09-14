"""Optional full name on users.

Captured at sign-up from the trial flow, where it is pre-filled from the
uploaded CV and confirmed/edited by the user before submitting. Nullable:
every account created before this migration has none, and /register still
accepts a request without it.

Revision ID: 021
Revises: 020
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "full_name")
