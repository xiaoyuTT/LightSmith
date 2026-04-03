"""Initial migration: create runs table

Revision ID: cdb5bf900e44
Revises:
Create Date: 2026-04-03 10:29:32.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cdb5bf900e44'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create runs table with indexes"""
    # Create runs table
    op.create_table(
        'runs',
        sa.Column('id', sa.String(length=36), nullable=False, comment='Run unique ID (UUID4)'),
        sa.Column('trace_id', sa.String(length=36), nullable=False, comment='Top-level trace ID'),
        sa.Column('parent_run_id', sa.String(length=36), nullable=True, comment='Parent Run ID, NULL for root'),
        sa.Column('name', sa.String(length=255), nullable=False, comment='Function name or display name'),
        sa.Column('run_type', sa.String(length=20), nullable=False, comment='Run type: chain/llm/tool/agent/custom'),
        sa.Column('inputs', sa.JSON(), nullable=False, comment='Function inputs JSON snapshot'),
        sa.Column('outputs', sa.JSON(), nullable=True, comment='Function outputs JSON snapshot'),
        sa.Column('error', sa.Text(), nullable=True, comment='Exception info: ExcType + message + traceback'),
        sa.Column('start_time', sa.String(length=32), nullable=False, comment='Start time (UTC ISO 8601)'),
        sa.Column('end_time', sa.String(length=32), nullable=True, comment='End time (UTC ISO 8601)'),
        sa.Column('metadata', sa.JSON(), nullable=False, comment='User-defined key-value pairs'),
        sa.Column('tags', sa.JSON(), nullable=False, comment='String tag list'),
        sa.Column('exec_order', sa.Integer(), nullable=False, comment='Creation order under same parent'),
        sa.PrimaryKeyConstraint('id'),
        comment='Run records table - stores traced function calls'
    )

    # Create indexes
    op.create_index('idx_runs_trace_id', 'runs', ['trace_id'], unique=False)
    op.create_index('idx_runs_parent_run_id', 'runs', ['parent_run_id'], unique=False)
    op.create_index('idx_runs_start_time', 'runs', ['start_time'], unique=False)


def downgrade() -> None:
    """Drop runs table and indexes"""
    op.drop_index('idx_runs_start_time', table_name='runs')
    op.drop_index('idx_runs_parent_run_id', table_name='runs')
    op.drop_index('idx_runs_trace_id', table_name='runs')
    op.drop_table('runs')
