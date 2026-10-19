"""Initial schema: experiments and sweeps.

Matches what earlier versions created with Base.metadata.create_all, so an
existing database is stamped at this revision instead of re-created (see
db.init_db).

Revision ID: 0001
Revises:
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('sweeps',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('parameter', sa.String(length=64), nullable=False),
    sa.Column('values', sa.JSON(), nullable=False),
    sa.Column('repeats', sa.Integer(), nullable=False),
    sa.Column('base_request', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('experiments',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('sweep_id', sa.String(length=32), nullable=True),
    sa.Column('sweep_value', sa.Float(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('request', sa.JSON(), nullable=False),
    sa.Column('store_spikes', sa.Boolean(), nullable=False),
    sa.Column('progress_done', sa.Integer(), nullable=True),
    sa.Column('progress_total', sa.Integer(), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['sweep_id'], ['sweeps.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_experiments_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_experiments_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_experiments_sweep_id'), ['sweep_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('experiments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_experiments_sweep_id'))
        batch_op.drop_index(batch_op.f('ix_experiments_status'))
        batch_op.drop_index(batch_op.f('ix_experiments_created_at'))

    op.drop_table('experiments')
    op.drop_table('sweeps')