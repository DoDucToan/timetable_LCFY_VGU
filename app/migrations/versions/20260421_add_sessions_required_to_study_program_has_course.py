"""Add sessions_required to study_program_has_course

Revision ID: 20260421_add_sessions_required_to_study_program_has_course
Revises: 20260417_rename_course_for_group_only
Create Date: 2026-04-21 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260421_add_sessions_required_to_study_program_has_course'
down_revision = '20260417_rename_course_for_group_only'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'study_program_has_course',
        sa.Column('sessions_required', sa.Integer(), nullable=False, server_default='1'),
    )
    op.alter_column('study_program_has_course', 'sessions_required', server_default=None)


def downgrade() -> None:
    op.drop_column('study_program_has_course', 'sessions_required')
