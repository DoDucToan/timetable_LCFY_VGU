"""
Add timetable_id to CourseForGroupTag and StudyProgramCourse

Revision ID: 20240414_add_timetable_id_to_requirements
Revises: 
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20240414_add_timetable_id_to_requirements'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Add timetable_id to course_for_group_tag
    op.add_column('course_for_group_tag', sa.Column('timetable_id', sa.Integer(), nullable=True))
    op.add_column('study_program_has_course', sa.Column('timetable_id', sa.Integer(), nullable=True))
    # If you have existing data, you must backfill timetable_id. We'll set it to the timetable of the first group using the group_tag or study_program.
    op.execute('''
        UPDATE course_for_group_tag
        SET timetable_id = (
            SELECT timetable_id FROM "group_tbl" WHERE group_tag_id = course_for_group_tag.group_tag_id LIMIT 1
        )
        WHERE timetable_id IS NULL
    ''')
    op.execute('''
        UPDATE study_program_has_course
        SET timetable_id = (
            SELECT timetable_id FROM group_has_study_program WHERE study_program_id = study_program_has_course.study_program_id LIMIT 1
        )
        WHERE timetable_id IS NULL
    ''')
    # Set NOT NULL
    op.alter_column('course_for_group_tag', 'timetable_id', nullable=False)
    op.alter_column('study_program_has_course', 'timetable_id', nullable=False)
    # Add foreign keys
    op.create_foreign_key('fk_course_for_group_tag_timetable', 'course_for_group_tag', 'timetable', ['timetable_id'], ['id'])
    op.create_foreign_key('fk_study_program_has_course_timetable', 'study_program_has_course', 'timetable', ['timetable_id'], ['id'])

def downgrade():
    op.drop_constraint('fk_course_for_group_tag_timetable', 'course_for_group_tag', type_='foreignkey')
    op.drop_constraint('fk_study_program_has_course_timetable', 'study_program_has_course', type_='foreignkey')
    op.drop_column('course_for_group_tag', 'timetable_id')
    op.drop_column('study_program_has_course', 'timetable_id')
