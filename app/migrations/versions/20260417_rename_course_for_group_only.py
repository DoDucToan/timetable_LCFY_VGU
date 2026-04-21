"""
Rename course_for_group to course_for_group_only

Revision ID: 20260417_rename_course_for_group_only
Revises: 20240414_add_timetable_id_to_requirements
Create Date: 2026-04-17
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = '20260417_rename_course_for_group_only'
down_revision = '20240414_add_timetable_id_to_requirements'
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table('course_for_group', 'course_for_group_only')


def downgrade():
    op.rename_table('course_for_group_only', 'course_for_group')
