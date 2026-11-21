"""partial coupon redemption: carry-over balance + per-redemption ledger

Revision ID: add_partial_coupon_redemption
Revises: add_sellers_and_coupon_workflow
Create Date: 2026-11-21

* mentor_coupons.face_value / remaining_balance / balance_currency
    A fixed-amount coupon ("5 EUR off") is balance-tracked: each redemption draws from
    remaining_balance and the coupon only becomes `used` at zero. NULL face_value keeps
    the old single-use behaviour (percent and free-text coupons).
* coupon_redemptions
    One row per redemption - the unit of the money ledger (bill, value owed, refund).
    Rows are voided, never deleted, when an admin resets a coupon.

Data: coupons redeemed before this revision need one coupon_redemptions row each so the
ledger (which now reads that table) still lists them. That backfill is NOT done here:
the ledger columns it copies from were added to mentor_coupons at runtime by
auto_migrate_schema, not by Alembic, so they may not exist on a schema built only from
migrations. The app runs _backfill_coupon_redemptions() on start-up instead - it is
idempotent and skips coupons that already have a row.

Additive only; nothing existing is altered or dropped.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_partial_coupon_redemption'
down_revision = 'add_sellers_and_coupon_workflow'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())

    # ---- mentor_coupons: balance columns ---------------------------------
    have = {c['name'] for c in inspector.get_columns('mentor_coupons')}
    for col_name, col_type in (
        ('face_value', sa.Numeric(12, 2)),
        ('remaining_balance', sa.Numeric(12, 2)),
        ('balance_currency', sa.String(length=8)),
    ):
        if col_name not in have:
            op.add_column('mentor_coupons', sa.Column(col_name, col_type, nullable=True))

    # No CHECK (balance >= 0) on purpose: runtime-created databases (auto_migrate_schema)
    # would not have it, so environments would differ. The redemption UPDATE enforces it
    # atomically instead (`... WHERE remaining_balance >= :amount`).

    # ---- coupon_redemptions ----------------------------------------------
    if 'coupon_redemptions' in inspector.get_table_names():
        return

    columns = [
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('coupon_id', sa.Integer(), nullable=False),
        sa.Column('seller_id', sa.Integer(), nullable=True),
        sa.Column('redeemed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('used_shop_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('goods_total', sa.Numeric(12, 2), nullable=True),
        sa.Column('goods_currency', sa.String(length=8), nullable=True),
        sa.Column('amount_applied', sa.Numeric(12, 2), nullable=True),
        sa.Column('balance_before', sa.Numeric(12, 2), nullable=True),
        sa.Column('balance_after', sa.Numeric(12, 2), nullable=True),
        sa.Column('discount_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('discount_manual', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('refunded', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('refunded_at', sa.DateTime(), nullable=True),
        sa.Column('refunded_by', sa.Integer(), nullable=True),
        sa.Column('recovered_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('refund_note', sa.String(length=300), nullable=True),
        sa.Column('ledger_edited_by', sa.Integer(), nullable=True),
        sa.Column('ledger_edited_at', sa.DateTime(), nullable=True),
        sa.Column('ledger_edit_role', sa.String(length=10), nullable=True),
        sa.Column('voided_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['coupon_id'], ['mentor_coupons.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['seller_id'], ['signup_details.id']),
        sa.ForeignKeyConstraint(['redeemed_by_user_id'], ['signup_details.id']),
        sa.ForeignKeyConstraint(['refunded_by'], ['signup_details.id']),
    ]
    # seller_shops was created at runtime on some installs; only reference it if present.
    if 'seller_shops' in inspector.get_table_names():
        columns.append(sa.ForeignKeyConstraint(['used_shop_id'], ['seller_shops.id']))
    columns.append(sa.PrimaryKeyConstraint('id'))
    op.create_table('coupon_redemptions', *columns)

    for name, cols in (
        ('ix_coupon_redemptions_coupon_id', ['coupon_id']),
        ('ix_coupon_redemptions_seller_id', ['seller_id']),
        ('ix_coupon_redemptions_redeemed_by_user_id', ['redeemed_by_user_id']),
        ('ix_coupon_redemptions_created_at', ['created_at']),
        ('ix_coupon_redemptions_live', ['seller_id', 'voided_at']),
    ):
        try:
            op.create_index(name, 'coupon_redemptions', cols, unique=False)
        except Exception as e:
            print(f"Notice: {name} might already exist: {e}")


def downgrade():
    # WARNING: dropping coupon_redemptions discards the per-use money trail (what each
    # partner is owed / has been refunded). Export the ledger first.
    for name in ('ix_coupon_redemptions_live', 'ix_coupon_redemptions_created_at',
                 'ix_coupon_redemptions_redeemed_by_user_id', 'ix_coupon_redemptions_seller_id',
                 'ix_coupon_redemptions_coupon_id'):
        try:
            op.drop_index(name, table_name='coupon_redemptions')
        except Exception as e:
            print(f"Notice: {e}")
    try:
        op.drop_table('coupon_redemptions')
    except Exception as e:
        print(f"Notice: {e}")

    for col_name in ('balance_currency', 'remaining_balance', 'face_value'):
        try:
            op.drop_column('mentor_coupons', col_name)
        except Exception as e:
            print(f"Notice: {e}")
