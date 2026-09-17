"""add premium_applications table

Revision ID: add_premium_application
Revises: f80b6651fd97
Create Date: 2026-09-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_premium_application'
down_revision = 'f80b6651fd97'
branch_labels = None
depends_on = None


def upgrade():
    try:
        op.create_table(
            'premium_applications',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('mentor_id', sa.Integer(), nullable=False),
            sa.Column('reason', sa.Text(), nullable=False),
            sa.Column('years_experience', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(length=50), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('reviewed_at', sa.DateTime(), nullable=True),
            sa.Column('reviewed_by', sa.String(length=50), nullable=True),
            sa.ForeignKeyConstraint(['mentor_id'], ['signup_details.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
    except Exception as e:
        print(f"Notice: premium_applications table might already exist: {e}")


def downgrade():
    try:
        op.drop_table('premium_applications')
    except Exception as e:
        print(f"Notice: {e}")
