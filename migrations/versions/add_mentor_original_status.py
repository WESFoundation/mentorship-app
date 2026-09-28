"""add_mentor_original_status

Revision ID: add_mentor_original_status
Revises: 
Create Date: 2026-09-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_mentor_original_status'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('mentorship_requests', sa.Column('mentor_original_status', sa.String(20), nullable=True))


def downgrade():
    op.drop_column('mentorship_requests', 'mentor_original_status')