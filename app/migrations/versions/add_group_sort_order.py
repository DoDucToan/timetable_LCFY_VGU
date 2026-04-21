"""
Revision: add_group_sort_order
Add sort_order column to group_tbl for persistent group ordering.
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('group_tbl', sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
    op.execute('UPDATE group_tbl SET sort_order = id')
    op.alter_column('group_tbl', 'sort_order', server_default=None)

def downgrade():
    op.drop_column('group_tbl', 'sort_order')
