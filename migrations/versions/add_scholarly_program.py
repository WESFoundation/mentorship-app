"""add scholarly field to signup_details and create scholarly_applications table

Revision ID: add_scholarly_program
Revises: add_linkedin_profile_req
Create Date: 2026-09-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_scholarly_program'
down_revision = 'add_linkedin_profile_req'
branch_labels = None
depends_on = None


def upgrade():
    try:
        with op.batch_alter_table('signup_details', schema=None) as batch_op:
            batch_op.add_column(sa.Column('scholarly', sa.Boolean(), nullable=True, server_default='0'))
    except Exception as e:
        print(f"Notice: signup_details.scholarly might already exist: {e}")

    try:
        op.create_table(
            'scholarly_applications',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('mentee_id', sa.Integer(), nullable=False),
            sa.Column('reason', sa.Text(), nullable=False),
            sa.Column('status', sa.String(length=50), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('reviewed_at', sa.DateTime(), nullable=True),
            sa.Column('reviewed_by', sa.String(length=50), nullable=True),
            sa.ForeignKeyConstraint(['mentee_id'], ['signup_details.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
    except Exception as e:
        print(f"Notice: scholarly_applications table might already exist: {e}")


def downgrade():
    try:
        op.drop_table('scholarly_applications')
    except Exception as e:
        print(f"Notice: {e}")

    try:
        with op.batch_alter_table('signup_details', schema=None) as batch_op:
            batch_op.drop_column('scholarly')
    except Exception as e:
        print(f"Notice: {e}")
