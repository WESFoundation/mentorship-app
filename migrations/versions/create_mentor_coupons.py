"""create mentor_coupons table

Revision ID: create_mentor_coupons
Revises: None
Create Date: 2026-10-14

Coupon keys are what the mentor's QR code encodes. A seller scans the QR, lands
on /coupon/verify/<code> and presses a button, which flips the row to `used`.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_mentor_coupons'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'mentor_coupons',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('mentor_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('discount_label', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('used_by', sa.String(length=200), nullable=True),
        sa.Column('verification_count', sa.Integer(), nullable=True, server_default='0'),
        sa.ForeignKeyConstraint(['mentor_id'], ['signup_details.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    try:
        op.create_index('ix_mentor_coupons_code', 'mentor_coupons', ['code'], unique=True)
    except Exception as e:
        print(f"Notice: ix_mentor_coupons_code might already exist: {e}")
    try:
        op.create_index('ix_mentor_coupons_mentor_id', 'mentor_coupons', ['mentor_id'], unique=False)
    except Exception as e:
        print(f"Notice: ix_mentor_coupons_mentor_id might already exist: {e}")


def downgrade():
    for idx in ('ix_mentor_coupons_mentor_id', 'ix_mentor_coupons_code'):
        try:
            op.drop_index(idx, table_name='mentor_coupons')
        except Exception as e:
            print(f"Notice: {e}")
    op.drop_table('mentor_coupons')