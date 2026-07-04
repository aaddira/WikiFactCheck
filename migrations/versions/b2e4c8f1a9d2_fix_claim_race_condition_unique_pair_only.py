"""fix claim race condition - unique pair only

Revision ID: b2e4c8f1a9d2
Revises: daaa8d00a6a3
Create Date: 2026-07-04 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2e4c8f1a9d2'
down_revision = 'daaa8d00a6a3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.drop_constraint('uq_claim_pair_user', type_='unique')
        batch_op.create_unique_constraint('uq_claim_pair_id', ['pair_id'])


def downgrade():
    with op.batch_alter_table('claims', schema=None) as batch_op:
        batch_op.drop_constraint('uq_claim_pair_id', type_='unique')
        batch_op.create_unique_constraint('uq_claim_pair_user', ['pair_id', 'user_id'])
