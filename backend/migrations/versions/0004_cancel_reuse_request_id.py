"""Add cancellation, result reuse and request tracing to experiments.

- cancel_requested: set by POST .../cancel on a running experiment; the worker
  checks it between odour presentations and stops (status "cancelled").
- request_key: hash of the request and the model it ran on; an identical
  request returns the stored experiment instead of running it again.
- request_id: the X-Request-ID of the submitting HTTP request, so worker logs
  can be matched to the API request that queued the job.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cancel_requested", sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
        batch_op.add_column(sa.Column("request_key", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("request_id", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_experiments_request_key"), ["request_key"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_experiments_request_key"))
        batch_op.drop_column("request_id")
        batch_op.drop_column("request_key")
        batch_op.drop_column("cancel_requested")
