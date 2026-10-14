"""add sgm task category columns to personal_tasks

Revision ID: add_sgm_task_category
Revises: None
Create Date: 2026-10-14

Marks SGM (Group Mentoring & Fireside chat) group tasks, stores the
participating mentor/mentee roster for them, and links each back to the SGM
session that created it.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_sgm_task_category'
down_revision = None
branch_labels = None
depends_on = None

_COLUMNS = [
    ('category', sa.String(length=30)),
    ('sgm_mentor_ids', sa.Text()),
    ('sgm_mentee_ids', sa.Text()),
    ('sgm_meeting_id', sa.Integer()),
]


def upgrade():
    for name, col_type in _COLUMNS:
        try:
            with op.batch_alter_table('personal_tasks', schema=None) as batch_op:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))
        except Exception as e:
            print(f"Notice: personal_tasks.{name} might already exist: {e}")

    # Every pre-existing task is a regular personal task.
    try:
        op.execute("UPDATE personal_tasks SET category = 'personal' "
                   "WHERE category IS NULL OR category = ''")
    except Exception as e:
        print(f"Notice: personal_tasks.category backfill skipped: {e}")

    # Per-mentor mentor_reflections so every mentor's feedback on a shared SGM
    # task is kept instead of overwriting the previous mentor's.
    for idx, table, cols in (
        ('idx_mentor_reflections_task', 'mentor_reflections',
         ['task_type', 'task_id', 'mentor_id']),
        ('idx_task_ratings_task_mentor', 'task_ratings',
         ['task_type', 'task_id', 'mentor_id']),
    ):
        try:
            op.create_index(idx, table, cols, unique=False)
        except Exception as e:
            print(f"Notice: {idx} might already exist: {e}")


def downgrade():
    for idx, table in (
        ('idx_task_ratings_task_mentor', 'task_ratings'),
        ('idx_mentor_reflections_task', 'mentor_reflections'),
    ):
        try:
            op.drop_index(idx, table_name=table)
        except Exception as e:
            print(f"Notice: {e}")

    for name, _col_type in reversed(_COLUMNS):
        try:
            with op.batch_alter_table('personal_tasks', schema=None) as batch_op:
                batch_op.drop_column(name)
        except Exception as e:
            print(f"Notice: personal_tasks.{name} could not be dropped: {e}")