"""add structured country/state/city columns to mentor_profile

Revision ID: add_mentor_location_columns
Revises: None
Create Date: 2026-10-14

Mentor locations used to live in a single free-text `location` string, which
produced duplicate and contradictory entries (for example "Luxembourg,
Luxembourg" next to "Luxembourg, Pakistan"). These columns mirror the
Country / State / City cascade used by the profile form so that filtering and
matching agree with it.

This migration only adds the columns. Backfilling them is a deliberate,
reviewed operation: run zextra/python codes/fix_mentor_locations.py against a
disposable copy first, review the report, then apply.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_mentor_location_columns'
down_revision = None
branch_labels = None
depends_on = None

_COLUMNS = [
    ('country', sa.String(length=100)),
    ('state', sa.String(length=100)),
    ('city', sa.String(length=100)),
]


def upgrade():
    for name, col_type in _COLUMNS:
        try:
            with op.batch_alter_table('mentor_profile', schema=None) as batch_op:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))
        except Exception as e:
            print(f"Notice: mentor_profile.{name} might already exist: {e}")

    for idx, col in (
        ('idx_mentor_country', 'country'),
        ('idx_mentor_state', 'state'),
        ('idx_mentor_city', 'city'),
    ):
        try:
            op.create_index(idx, 'mentor_profile', [col], unique=False)
        except Exception as e:
            print(f"Notice: {idx} might already exist: {e}")


def downgrade():
    for idx in ('idx_mentor_city', 'idx_mentor_state', 'idx_mentor_country'):
        try:
            op.drop_index(idx, table_name='mentor_profile')
        except Exception as e:
            print(f"Notice: {e}")

    for name, _col_type in reversed(_COLUMNS):
        try:
            with op.batch_alter_table('mentor_profile', schema=None) as batch_op:
                batch_op.drop_column(name)
        except Exception as e:
            print(f"Notice: mentor_profile.{name} could not be dropped: {e}")