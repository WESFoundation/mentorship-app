"""add linkedin_profile to mentorship_requests and mentor_sourcing_requests

Revision ID: add_linkedin_profile_req
Revises: add_created_at_user
Create Date: 2026-09-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_linkedin_profile_req'
down_revision = 'add_created_at_user'
branch_labels = None
depends_on = None


def upgrade():
    try:
        with op.batch_alter_table('mentorship_requests', schema=None) as batch_op:
            batch_op.add_column(sa.Column('linkedin_profile', sa.String(length=500), nullable=True))
    except Exception as e:
        print(f"Notice: mentorship_requests.linkedin_profile might already exist: {e}")

    try:
        with op.batch_alter_table('mentor_sourcing_requests', schema=None) as batch_op:
            batch_op.add_column(sa.Column('linkedin_profile', sa.String(length=500), nullable=True))
    except Exception as e:
        print(f"Notice: mentor_sourcing_requests.linkedin_profile might already exist: {e}")


def downgrade():
    try:
        with op.batch_alter_table('mentorship_requests', schema=None) as batch_op:
            batch_op.drop_column('linkedin_profile')
    except Exception as e:
        print(f"Notice: {e}")

    try:
        with op.batch_alter_table('mentor_sourcing_requests', schema=None) as batch_op:
            batch_op.drop_column('linkedin_profile')
    except Exception as e:
        print(f"Notice: {e}")
