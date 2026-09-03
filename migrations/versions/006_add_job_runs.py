"""Add job_runs table for cross-worker scheduled-job claims.

Gunicorn runs 2 workers, each with its own APScheduler, so every cron job
fired twice -- annotators received duplicate weekly digests. The unique
(job_name, run_key) constraint lets exactly one worker claim each time slot.

Revision ID: 006
Revises: 005
Create Date: 2026-09-03 23:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'job_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_name', sa.String(length=100), nullable=False),
        sa.Column('run_key', sa.String(length=50), nullable=False),
        sa.Column('claimed_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='running'),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_name', 'run_key', name='uq_job_run_name_key'),
    )
    op.create_index('ix_job_runs_job_name', 'job_runs', ['job_name'])


def downgrade():
    op.drop_index('ix_job_runs_job_name', table_name='job_runs')
    op.drop_table('job_runs')
