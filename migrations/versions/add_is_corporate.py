"""add is_corporate field to signup_details

Revision ID: add_is_corporate
Revises: add_premium_application
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_is_corporate'
down_revision = 'add_premium_application'
branch_labels = None
depends_on = None


def upgrade():
    try:
        with op.batch_alter_table('signup_details', schema=None) as batch_op:
            batch_op.add_column(sa.Column('is_corporate', sa.Boolean(), nullable=True, server_default='0'))
    except Exception as e:
        print(f"Notice: signup_details.is_corporate might already exist: {e}")


def downgrade():
    try:
        with op.batch_alter_table('signup_details', schema=None) as batch_op:
            batch_op.drop_column('is_corporate')
    except Exception as e:
        print(f"Notice: {e}")
