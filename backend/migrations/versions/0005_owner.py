"""Add owner to experiments and sweeps.

Who submitted it: "key:<api key id>" or, on a server that doesn't require
keys, "addr:<client address>". On such an open server only the owner (or a
request with a valid API key) may cancel or delete it.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("owner", sa.String(length=80), nullable=True))
    with op.batch_alter_table("sweeps", schema=None) as batch_op:
        batch_op.add_column(sa.Column("owner", sa.String(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sweeps", schema=None) as batch_op:
        batch_op.drop_column("owner")
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        batch_op.drop_column("owner")
