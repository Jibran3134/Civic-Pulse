"""Create complaints table

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '001'
down_revision = None
branch_labels = None
depends_on = None

complaint_category = postgresql.ENUM(
    'water', 'electricity', 'sanitation', 'roads', 'streetlights', 'other',
    name='complaint_category', create_type=True
)
complaint_priority = postgresql.ENUM(
    'high', 'normal', 'low',
    name='complaint_priority', create_type=True
)
complaint_status = postgresql.ENUM(
    'open', 'in_progress', 'resolved', 'rejected',
    name='complaint_status', create_type=True
)


def upgrade() -> None:
    complaint_category.create(op.get_bind(), checkfirst=True)
    complaint_priority.create(op.get_bind(), checkfirst=True)
    complaint_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'complaints',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('text', sa.String(length=2000), nullable=False),
        sa.Column('location', sa.String(length=200), nullable=False),
        sa.Column('reporter_contact', sa.String(length=200), nullable=True),
        sa.Column('category', complaint_category, nullable=False),
        sa.Column('priority', complaint_priority, nullable=False),
        sa.Column('status', complaint_status, nullable=False, server_default='open'),
        sa.Column('ai_summary', sa.String(length=140), nullable=True),
        sa.Column('triaged_by', sa.String(length=50), nullable=False),
        sa.Column('triage_latency_ms', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('char_length(text) BETWEEN 10 AND 2000', name='check_text_length'),
        sa.CheckConstraint('char_length(location) BETWEEN 3 AND 200', name='check_location_length'),
    )

    op.create_index('ix_complaints_status_priority', 'complaints', ['status', 'priority'])
    op.create_index('ix_complaints_created_at', 'complaints', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_complaints_created_at', table_name='complaints')
    op.drop_index('ix_complaints_status_priority', table_name='complaints')
    op.drop_table('complaints')
    complaint_status.drop(op.get_bind(), checkfirst=True)
    complaint_priority.drop(op.get_bind(), checkfirst=True)
    complaint_category.drop(op.get_bind(), checkfirst=True)
