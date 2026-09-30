"""add_institution_status_to_mentorship

Revision ID: add_institution_status_to_mentorship
Revises: 
Create Date: 2026-09-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_institution_status_to_mentorship'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('mentorship_requests', sa.Column('institution_status', sa.String(20), nullable=False, server_default='pending'))


def downgrade():
    op.drop_column('mentorship_requests', 'institution_status')