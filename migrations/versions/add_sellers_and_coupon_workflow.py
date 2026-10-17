"""add seller accounts, coupon assignment and coupon requests

Revision ID: add_sellers_and_coupon_workflow
Revises: None
Create Date: 2026-10-17

Brings in the partner/seller redemption workflow:

* seller_profiles      - a partner/seller account (shop / market) plus supervisor verification
* coupon_assignments   - one coupon -> many mentors/mentees (replaces the single mentor_id owner)
* coupon_requests      - a mentor/mentee asking a supervisor to issue coupons
* mentor_coupons extra columns:
    issued_by_user_id    - supervisor/admin who created the coupon
    seller_id            - verified partner who redeemed it
    redeemed_by_user_id  - which mentor/mentee presented the coupon

`mentor_coupons.mentor_id` is deliberately left in place (NOT NULL) so existing rows
and the legacy dashboard keep working; it is deprecated and new coupons only set it
to satisfy the constraint. Ownership lives in `coupon_assignments`.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_sellers_and_coupon_workflow'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ---- seller_profiles -------------------------------------------------
    op.create_table(
        'seller_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('partner_label', sa.String(length=60), nullable=True, server_default='Partner'),
        sa.Column('shop_name', sa.String(length=200), nullable=True),
        sa.Column('market_name', sa.String(length=200), nullable=True),
        sa.Column('contact_phone', sa.String(length=40), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('verified_by', sa.Integer(), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['signup_details.id']),
        sa.ForeignKeyConstraint(['verified_by'], ['signup_details.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    try:
        op.create_index('ix_seller_profiles_user_id', 'seller_profiles', ['user_id'], unique=True)
    except Exception as e:
        print(f"Notice: ix_seller_profiles_user_id might already exist: {e}")

    # ---- coupon_assignments ---------------------------------------------
    op.create_table(
        'coupon_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('coupon_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('assigned_by', sa.Integer(), nullable=True),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['coupon_id'], ['mentor_coupons.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['signup_details.id']),
        sa.ForeignKeyConstraint(['assigned_by'], ['signup_details.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('coupon_id', 'user_id', name='uq_coupon_assignment'),
    )
    for name, cols, uniq in (
        ('ix_coupon_assignments_coupon_id', ['coupon_id'], False),
        ('ix_coupon_assignments_user_id', ['user_id'], False),
    ):
        try:
            op.create_index(name, 'coupon_assignments', cols, unique=uniq)
        except Exception as e:
            print(f"Notice: {name} might already exist: {e}")

    # ---- coupon_requests --------------------------------------------------
    op.create_table(
        'coupon_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('discount_label', sa.String(length=120), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('handled_by', sa.Integer(), nullable=True),
        sa.Column('handled_at', sa.DateTime(), nullable=True),
        sa.Column('admin_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['signup_details.id']),
        sa.ForeignKeyConstraint(['handled_by'], ['signup_details.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    try:
        op.create_index('ix_coupon_requests_user_id', 'coupon_requests', ['user_id'], unique=False)
    except Exception as e:
        print(f"Notice: ix_coupon_requests_user_id might already exist: {e}")

    # ---- extra mentor_coupons columns -------------------------------------
    # Additive only: mentor_id stays NOT NULL so nothing existing is disturbed.
    inspector = sa.inspect(op.get_bind())
    have = {c['name'] for c in inspector.get_columns('mentor_coupons')}
    for col_name, col_type in (
        ('issued_by_user_id', sa.Integer()),
        ('seller_id', sa.Integer()),
        ('redeemed_by_user_id', sa.Integer()),
    ):
        if col_name in have:
            continue
        op.add_column('mentor_coupons', sa.Column(col_name, col_type, nullable=True))

    for name in ('ix_mentor_coupons_issued_by_user_id',
                 'ix_mentor_coupons_seller_id',
                 'ix_mentor_coupons_redeemed_by_user_id'):
        try:
            op.create_index(name, 'mentor_coupons', [name.replace('ix_mentor_coupons_', '')], unique=False)
        except Exception as e:
            print(f"Notice: {name} might already exist: {e}")


def downgrade():
    for name in ('ix_mentor_coupons_redeemed_by_user_id',
                 'ix_mentor_coupons_seller_id',
                 'ix_mentor_coupons_issued_by_user_id'):
        try:
            op.drop_index(name, table_name='mentor_coupons')
        except Exception as e:
            print(f"Notice: {e}")
    for col_name in ('redeemed_by_user_id', 'seller_id', 'issued_by_user_id'):
        try:
            op.drop_column('mentor_coupons', col_name)
        except Exception as e:
            print(f"Notice: {e}")

    try:
        op.drop_index('ix_coupon_requests_user_id', table_name='coupon_requests')
    except Exception as e:
        print(f"Notice: {e}")
    op.drop_table('coupon_requests')

    for name in ('ix_coupon_assignments_user_id', 'ix_coupon_assignments_coupon_id'):
        try:
            op.drop_index(name, table_name='coupon_assignments')
        except Exception as e:
            print(f"Notice: {e}")
    op.drop_table('coupon_assignments')

    try:
        op.drop_index('ix_seller_profiles_user_id', table_name='seller_profiles')
    except Exception as e:
        print(f"Notice: {e}")
    op.drop_table('seller_profiles')