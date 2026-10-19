"""Add experiments.sweep_label for sweeps whose values aren't numbers.

A lesion scan sweeps over which neurons are silenced ("none", "MBON01", ...);
those labels go here, numeric sweep values stay in sweep_value.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sweep_label', sa.String(length=64), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.drop_column('sweep_label')