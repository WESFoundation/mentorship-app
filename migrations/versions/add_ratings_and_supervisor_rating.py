"""add ratings columns to mentorship_requests and supervisor_rating to mentor_profile

Revision ID: add_ratings_and_supervisor_rating
Revises: add_linkedin_profile_req
Create Date: 2026-09-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_ratings_and_supervisor_rating'
down_revision = 'add_linkedin_profile_req'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add rating columns to mentorship_requests
    try:
        with op.batch_alter_table('mentorship_requests', schema=None) as batch_op:
            batch_op.add_column(sa.Column('rating', sa.Float(), nullable=True))
    except Exception as e:
        print(f"Notice: mentorship_requests.rating might already exist: {e}")

    try:
        with op.batch_alter_table('mentorship_requests', schema=None) as batch_op:
            batch_op.add_column(sa.Column('rating_review', sa.Text(), nullable=True))
    except Exception as e:
        print(f"Notice: mentorship_requests.rating_review might already exist: {e}")

    try:
        with op.batch_alter_table('mentorship_requests', schema=None) as batch_op:
            batch_op.add_column(sa.Column('rated_at', sa.DateTime(), nullable=True))
    except Exception as e:
        print(f"Notice: mentorship_requests.rated_at might already exist: {e}")

    try:
        with op.batch_alter_table('mentorship_requests', schema=None) as batch_op:
            batch_op.add_column(sa.Column('rated_by', sa.Integer(), nullable=True))
    except Exception as e:
        print(f"Notice: mentorship_requests.rated_by might already exist: {e}")

    # 2. Add supervisor_rating to mentor_profile
    try:
        with op.batch_alter_table('mentor_profile', schema=None) as batch_op:
            batch_op.add_column(sa.Column('supervisor_rating', sa.Float(), nullable=True))
    except Exception as e:
        print(f"Notice: mentor_profile.supervisor_rating might already exist: {e}")


def downgrade():
    try:
        with op.batch_alter_table('mentorship_requests', schema=None) as batch_op:
            batch_op.drop_column('rated_by')
            batch_op.drop_column('rated_at')
            batch_op.drop_column('rating_review')
            batch_op.drop_column('rating')
    except Exception as e:
        print(f"Notice: {e}")

    try:
        with op.batch_alter_table('mentor_profile', schema=None) as batch_op:
            batch_op.drop_column('supervisor_rating')
    except Exception as e:
        print(f"Notice: {e}")
