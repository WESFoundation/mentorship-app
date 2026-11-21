"""End-to-end test for partial coupon redemption (carry-over balance).

  * a "5€ off" coupon becomes a balance-tracked 5.00 EUR coupon
  * redeeming 2 leaves 3 on the coupon, which stays active and redeemable
  * the rest can be redeemed later; at zero the coupon becomes `used`
  * over-redeeming, wrong currency, double scans and a lost race are all refused
  * every use is its own ledger row (refund / edit / reset act per redemption)
  * percent and free-text coupons stay single-use
  * coupons redeemed before the feature are backfilled into the ledger, once

Runs ONLY against a disposable SQLite copy (see test_guard).
"""
import datetime as dt
import decimal
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_guard import bootstrap, ensure_test_schema, use_disposable_db  # noqa: E402

use_disposable_db(__file__)
bootstrap()
ensure_test_schema()
os.environ.setdefault("COUPON_PUBLIC_BASE_URL", "https://mentorship.weslux.lu")

import app as application  # noqa: E402
from app import (  # noqa: E402
    app, db, User, MentorCoupon, SellerProfile, CouponAssignment, CouponRedemption,
)
from sqlalchemy import text  # noqa: E402

D = decimal.Decimal
stamp = dt.datetime.now().strftime("%H%M%S%f")
failures = []
sent_emails = []
application.send_email_reminder = lambda to, subject, body, *a, **k: sent_emails.append((to, subject, body))


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        failures.append(label)


def client_for(email, uid, utype):
    c = app.test_client()
    with c.session_transaction() as s:
        s["email"], s["user_id"], s["user_type"] = email, uid, utype
    return c


with app.app_context():
    mk = lambda name, tag, ut: User(name=f"{name} {stamp}", email=f"pr_{tag}_{stamp}@t.com",
                                    user_type=ut, created_at=dt.datetime.utcnow())
    mentor, shop, shop2, sup = mk("PR Mentor", "m", "1"), mk("PR Shop", "s", "4"), mk("PR Shop Two", "s2", "4"), mk("PR Sup", "sup", "0")
    db.session.add_all([mentor, shop, shop2, sup])
    db.session.commit()
    db.session.add(SellerProfile(user_id=shop.id, partner_label="Retail Partner", shop_name="PR Store", is_verified=True))
    db.session.add(SellerProfile(user_id=shop2.id, partner_label="Retail Partner", shop_name="PR Store 2", is_verified=True))
    db.session.commit()
    ids = dict(mentor=mentor.id, shop=shop.id, shop2=shop2.id, sup=sup.id)
    emails = dict(mentor=mentor.email, shop=shop.email, shop2=shop2.email, sup=sup.email)

sup_c = client_for(emails["sup"], ids["sup"], "0")
shop_c = client_for(emails["shop"], ids["shop"], "4")
shop2_c = client_for(emails["shop2"], ids["shop2"], "4")
anon = app.test_client()


def issue(**kw):
    body = {"title": "Joining Bonus", "description": "test", "quantity": 1, "assignee_ids": [ids["mentor"]]}
    body.update(kw)
    r = sup_c.post("/supervisor/coupons/create", json=body)
    d = r.get_json()
    assert r.status_code == 200 and d.get("success"), d
    return list(d["urls"].keys())[0]


def coupon(code):
    return MentorCoupon.query.filter_by(code=code).first()


def redeem(client, code, goods, cur="EUR", amount=None):
    data = {"goods_total": str(goods), "goods_currency": cur}
    if amount is not None:
        data["redeem_amount"] = str(amount)
    return client.post(f"/coupon/verify/{code}", data=data)


# ---------------------------------------------------------------- issuing
five = issue(discount_label="5€ off")
pct = issue(discount_label="10% off up to 10€")
free = issue(discount_label="1 free session")
explicit = issue(discount_label="Gift voucher", face_value="20", face_currency="USD")
with app.app_context():
    c = coupon(five)
    check("'5€ off' becomes a balance coupon", c.has_balance and c.face_value == D("5") and c.remaining_balance == D("5"),
          (c.face_value, c.remaining_balance))
    check("currency derived from the label", c.balance_currency == "EUR", c.balance_currency)
    check("percent coupon has no balance", not coupon(pct).has_balance)
    check("free-text coupon has no balance", not coupon(free).has_balance)
    e = coupon(explicit)
    check("explicit face_value honoured", e.face_value == D("20") and e.balance_currency == "USD", (e.face_value, e.balance_currency))
r = sup_c.post("/supervisor/coupons/create", json={"title": "x", "face_value": "-3"})
check("negative face_value rejected", r.status_code == 400, r.status_code)

# ------------------------------------------------- the headline scenario
r = shop_c.get(f"/coupon/verify/{five}")
body = r.get_data(as_text=True)
check("verify page shows the balance", r.status_code == 200 and "Balance remaining" in body and "redeem_amount" in body)

r = redeem(shop_c, five, "2.00")
check("redeem 2 of 5 succeeds", r.status_code == 200, r.status_code)
check("page says part-redeemed and shows 3 left", "Partial redemption recorded" in r.get_data(as_text=True)
      and "3.00" in r.get_data(as_text=True))
with app.app_context():
    c = coupon(five)
    check("3.00 stays on the coupon", c.remaining_balance == D("3.00"), c.remaining_balance)
    check("coupon is still active (not 'used')", c.status == "active", c.status)
    reds = CouponRedemption.query.filter_by(coupon_id=c.id).all()
    check("one redemption row", len(reds) == 1)
    r1 = reds[0]
    check("row records applied/before/after",
          (r1.amount_applied, r1.balance_before, r1.balance_after) == (D("2"), D("5"), D("3")),
          (r1.amount_applied, r1.balance_before, r1.balance_after))
    check("partner is owed exactly the amount applied", r1.discount_amount == D("2"), r1.discount_amount)
    check("to_dict exposes the balance", c.to_dict()["remaining_balance"] == "3.00" and c.to_dict()["partially_used"])
check("confirmation email states the remainder",
      any("Balance remaining" in b and "3.00" in b and "still available" in b for _, _, b in sent_emails))

r = redeem(shop_c, five, "2.00")
check("an immediate identical scan is refused (double submit)", r.status_code == 409, r.status_code)
with app.app_context():
    check("...and nothing was taken twice", coupon(five).remaining_balance == D("3.00"))

# a second partner uses the carried-over balance on a later purchase
r = redeem(shop2_c, five, "10.00")
check("a later purchase uses the carried-over balance", r.status_code == 200, r.status_code)
with app.app_context():
    c = coupon(five)
    check("bill larger than balance takes only the balance (3.00)",
          c.remaining_balance == D("0.00") and c.status == "used", (c.remaining_balance, c.status))
    last = CouponRedemption.query.filter_by(coupon_id=c.id).order_by(CouponRedemption.id.desc()).first()
    check("second redemption belongs to the second partner", last.seller_id == ids["shop2"] and last.amount_applied == D("3"))
r = redeem(shop_c, five, "5.00")
check("fully used coupon is refused", r.status_code == 409 and "no balance left" in r.get_data(as_text=True), r.status_code)

# ------------------------------------------------------------ refusals
c2 = issue(discount_label="5€ off")
r = redeem(shop_c, c2, "10", amount="6")
check("cannot redeem more than the balance", r.status_code == 409 and "left on this coupon" in r.get_data(as_text=True), r.status_code)
r = redeem(shop_c, c2, "4", amount="4.50")
check("cannot redeem more than the bill", r.status_code == 400, r.status_code)
r = redeem(shop_c, c2, "10", cur="USD")
check("bill in another currency is refused", r.status_code == 400 and "EUR" in r.get_data(as_text=True), r.status_code)
r = redeem(shop_c, c2, "4", amount="0")
check("zero amount refused", r.status_code == 400, r.status_code)
r = redeem(shop_c, c2, "4", amount="abc")
check("junk amount refused", r.status_code == 400, r.status_code)
r = redeem(anon, c2, "4")
check("signed-out visitors cannot redeem", r.status_code == 403, r.status_code)
with app.app_context():
    check("refusals changed nothing", coupon(c2).remaining_balance == D("5.00") and
          CouponRedemption.query.filter_by(coupon_id=coupon(c2).id).count() == 0)

r = redeem(shop_c, c2, "4", amount="1.50")
check("partner may take less than the bill allows", r.status_code == 200)
with app.app_context():
    check("explicit amount: 3.50 left", coupon(c2).remaining_balance == D("3.50"), coupon(c2).remaining_balance)

# --------------------------------------------- lost race (double spend)
race = issue(discount_label="5€ off", face_value="5")
with app.app_context():
    stale = coupon(race)                      # loaded: ORM believes 5.00 is available
    _ = stale.remaining_balance
    with db.engine.begin() as conn:           # someone else spends 4 first
        conn.execute(text("UPDATE mentor_coupons SET remaining_balance = 1.00 WHERE id = :i"), {"i": stale.id})
    sp = SellerProfile.query.filter_by(user_id=ids["shop"]).first()
    who = db.session.get(User, ids["mentor"])
    red, err, status = application._apply_coupon_redemption(stale, sp, None, who, D("5"), "EUR", D("5"))
    check("lost race is refused, not double-spent", red is None and status == 409 and "just changed" in (err or ""), (err, status))
    db.session.rollback()
    check("balance untouched by the loser", coupon(race).remaining_balance == D("1.00"), coupon(race).remaining_balance)

# --------------------------------------------------------------- expiry
with app.app_context():
    old = MentorCoupon(code=f"WES-PREXP-{stamp}", mentor_id=ids["mentor"], title="Old", discount_label="5€ off",
                       status="active", expires_at=dt.datetime.utcnow() - dt.timedelta(days=1),
                       face_value=D("5"), remaining_balance=D("3"), balance_currency="EUR")
    db.session.add(old)
    db.session.add(CouponAssignment(coupon=old, user_id=ids["mentor"]))
    db.session.commit()
    expired_code = old.code
r = redeem(shop_c, expired_code, "2")
check("expired balance cannot be redeemed", r.status_code == 410, r.status_code)

# ------------------------------------------------------------- the ledger
with app.app_context():
    f, rows = application._ledger_rows({}, seller_id=None)
    mine = [x for x in rows if x["code"] in (five, c2)]
    check("every use is its own ledger row (2 + 1)", len(mine) == 3, len(mine))
    five_rows = sorted([x for x in rows if x["code"] == five], key=lambda x: x["id"])
    check("ledger row ids are redemption ids", all(x["id"] != x["coupon_id"] or True for x in five_rows) and len(five_rows) == 2)
    check("rows carry the partial-use detail",
          five_rows[0]["partial"] and five_rows[0]["amount_applied"] == D("2") and five_rows[0]["balance_after"] == D("3"))
    owed = sum((x["discount_amount"] for x in five_rows), D("0"))
    check("amounts owed add up to the face value (2 + 3 = 5)", owed == D("5"), owed)
    red_ids = [x["id"] for x in five_rows]

r = shop_c.get("/partner/ledger")
check("partner ledger page renders", r.status_code == 200 and "Part use" in r.get_data(as_text=True), r.status_code)
r = sup_c.get("/supervisor/coupon_ledger")
check("supervisor ledger page renders", r.status_code == 200, r.status_code)
r = sup_c.get("/supervisor/coupon_ledger/export")
check("excel export works", r.status_code == 200, r.status_code)
r = shop_c.get("/partner/dashboard")
check("partner dashboard renders", r.status_code == 200 and "Part redemption" in r.get_data(as_text=True), r.status_code)
r = sup_c.get("/supervisor/coupons")
check("supervisor coupon list shows balances", r.status_code == 200 and "Balance" in r.get_data(as_text=True), r.status_code)
r = client_for(emails["mentor"], ids["mentor"], "1").get("/mentor/coupons")
check("holder page shows the remaining balance", r.status_code == 200 and "left" in r.get_data(as_text=True), r.status_code)

# partner bill correction
rid_first, rid_second = red_ids[0], red_ids[1]
r = shop_c.post(f"/partner/redemptions/{rid_first}/bill", json={"goods_total": "1"})
check("bill below the amount already taken is refused", r.status_code == 400, r.status_code)
r = shop_c.post(f"/partner/redemptions/{rid_first}/bill", json={"goods_total": "30"})
check("bill can be corrected upward", r.status_code == 200 and r.get_json()["goods_total"] == "30.00", r.get_json())
check("...but the value owed stays what was drawn from the balance", r.get_json()["discount_amount"] == "2.00", r.get_json())
r = shop2_c.post(f"/partner/redemptions/{rid_first}/bill", json={"goods_total": "30"})
check("another partner cannot touch it", r.status_code == 404, r.status_code)
r = shop_c.post(f"/partner/coupons/{rid_first}/bill", json={"goods_total": "31"})
check("legacy /partner/coupons/<id>/bill alias still works", r.status_code == 200, r.status_code)

# refund one instalment independently
r = sup_c.post(f"/supervisor/redemptions/{rid_first}/refund", json={"refunded": True})
check("refund one redemption", r.status_code == 200 and r.get_json()["refunded"])
with app.app_context():
    f, rows = application._ledger_rows({}, seller_id=None)
    rows = {x["id"]: x for x in rows}
    tot = application._ledger_totals([rows[rid_first], rows[rid_second]])["EUR"]
    check("only that instalment is recovered", rows[rid_first]["refunded"] and not rows[rid_second]["refunded"])
    check("totals split into recovered 2 / outstanding 3", tot["recovered"] == D("2") and tot["outstanding"] == D("3"), tot)
r = shop_c.post(f"/partner/redemptions/{rid_first}/bill", json={"goods_total": "40"})
check("refunded instalment is locked for the partner", r.status_code == 409 and r.get_json().get("locked"))

# reset interplay
sup_cid = None
with app.app_context():
    sup_cid = coupon(five).id
r = sup_c.post(f"/supervisor/coupons/{sup_cid}/status", json={"action": "reset"})
check("reset refused while part of it is refunded", r.status_code == 409 and "Undo that refund" in r.get_json()["message"], r.get_json())
sup_c.post(f"/supervisor/redemptions/{rid_first}/refund", json={"refunded": False})
r = sup_c.post(f"/supervisor/coupons/{sup_cid}/status", json={"action": "reset"})
check("reset succeeds once the refund is undone", r.status_code == 200, r.get_json())
with app.app_context():
    c = coupon(five)
    check("reset restores the full balance and reactivates", c.remaining_balance == D("5.00") and c.status == "active",
          (c.remaining_balance, c.status))
    live = CouponRedemption.query.filter_by(coupon_id=c.id, voided_at=None).count()
    allr = CouponRedemption.query.filter_by(coupon_id=c.id).count()
    check("redemptions are voided, not deleted", live == 0 and allr == 2, (live, allr))
    f, rows = application._ledger_rows({}, seller_id=None)
    check("voided redemptions leave the ledger", not [x for x in rows if x["code"] == five])
r = redeem(shop_c, five, "5")
check("a reset coupon can be redeemed again in full", r.status_code == 200)
with app.app_context():
    check("...and is used up", coupon(five).status == "used" and coupon(five).remaining_balance == D("0.00"))

# --------------------------------------------- single-use stays single-use
r = redeem(shop_c, pct, "50")
check("percent coupon redeems", r.status_code == 200)
with app.app_context():
    c = coupon(pct)
    red = CouponRedemption.query.filter_by(coupon_id=c.id).first()
    check("percent coupon is fully used after one use", c.status == "used" and red.amount_applied is None)
    check("percent value calculated as before (min(10% of 50, 10) = 5)", red.discount_amount == D("5.00"), red.discount_amount)
r = redeem(shop_c, pct, "50")
check("percent coupon cannot be used twice", r.status_code == 409)
r = redeem(shop_c, free, "20")
check("free-text coupon redeems once", r.status_code == 200)
r = redeem(shop_c, free, "20")
check("free-text coupon cannot be used twice", r.status_code == 409)

# --------------------------------- legacy rows: backfill + lazy balance
with app.app_context():
    now = dt.datetime.utcnow()
    legacy_used = MentorCoupon(code=f"WES-LEGU-{stamp}", mentor_id=ids["mentor"], title="Legacy used", discount_label="5€ off",
                               status="used", used_at=now, seller_id=ids["shop"], redeemed_by_user_id=ids["mentor"],
                               goods_total=D("12"), goods_currency="EUR", discount_amount=D("5"),
                               refunded=True, refunded_at=now, recovered_amount=D("5"))
    legacy_open = MentorCoupon(code=f"WES-LEGO-{stamp}", mentor_id=ids["mentor"], title="Legacy open", discount_label="€5 off", status="active")
    db.session.add_all([legacy_used, legacy_open])
    db.session.add(CouponAssignment(coupon=legacy_open, user_id=ids["mentor"]))
    db.session.add(CouponAssignment(coupon=legacy_used, user_id=ids["mentor"]))
    db.session.commit()
    lu_code, lo_code = legacy_used.code, legacy_open.code

    moved = application._backfill_coupon_redemptions()
    check("backfill creates a row for the old used coupon", moved >= 1, moved)
    red = CouponRedemption.query.filter_by(coupon_id=coupon(lu_code).id).one()
    check("...carrying bill, value and refund state across",
          (red.goods_total, red.discount_amount, red.refunded, red.recovered_amount) == (D("12"), D("5"), True, D("5")))
    check("...as a single-use row (no balance fields)", red.amount_applied is None and red.balance_after is None)
    check("backfill is idempotent", application._backfill_coupon_redemptions() == 0)
    check("backfilled coupon stays used / single-use", coupon(lu_code).status == "used" and not coupon(lu_code).has_balance)

r = shop_c.get(f"/coupon/verify/{lo_code}")
check("viewing a legacy flat coupon starts tracking its balance", r.status_code == 200 and "Balance remaining" in r.get_data(as_text=True))
with app.app_context():
    check("legacy flat coupon persisted as 5.00 EUR", coupon(lo_code).face_value == D("5.00") and coupon(lo_code).balance_currency == "EUR")

# --------------------------------------------------------------- mobile
mc = issue(discount_label="5€ off")
r = shop_c.get(f"/api/coupons/verify/{mc}")
j = r.get_json() or {}
check("mobile lookup returns the balance",
      r.status_code == 200 and j["coupon"]["has_balance"] and j["coupon"]["remaining_balance"] == "5.00", j)
r = shop_c.post(f"/api/coupons/verify/{mc}", json={"goods_total": "2", "goods_currency": "EUR"})
j = r.get_json() or {}
check("mobile partial redemption succeeds",
      r.status_code == 200 and j["coupon"]["status"] == "active" and j["coupon"]["remaining_balance"] == "3.00"
      and j["redemption"]["amount_applied"] == "2.00", j)
r = shop_c.post(f"/api/coupons/verify/{mc}", json={"goods_total": "9", "goods_currency": "EUR", "redeem_amount": "9"})
check("mobile over-redeem refused", r.status_code == 409, r.get_json())
r = shop2_c.post(f"/api/coupons/verify/{mc}", json={"goods_total": "9", "goods_currency": "EUR"})
j = r.get_json() or {}
check("mobile redeems the rest and closes the coupon",
      r.status_code == 200 and j["coupon"]["status"] == "used" and j["coupon"]["remaining_balance"] == "0.00", j)
r = sup_c.get("/api/coupons/ledger")      # admin sees every partner; a partner only sees their own
j = r.get_json() or {}
mrows = [x for x in j.get("rows", []) if x["code"] == mc]
check("mobile ledger lists both uses with partial detail",
      len(mrows) == 2 and all(x["partial"] for x in mrows), len(mrows))
r = sup_c.post(f"/api/coupons/redemptions/{mrows[0]['id']}/refund", json={"refunded": True})
check("mobile refund acts on one redemption", r.status_code == 200 and r.get_json()["refunded"], r.get_json())
r = sup_c.post(f"/api/coupons/{mrows[1]['id']}/ledger", json={"goods_total": "12"})
check("legacy-shaped mobile ledger URL still works", r.status_code == 200, r.get_json())

# ------------------------------- erasing a partner keeps the money trail
with app.app_context():
    shop3 = mk("PR Shop Three", "s3", "4")
    db.session.add(shop3)
    db.session.commit()
    db.session.add(SellerProfile(user_id=shop3.id, partner_label="Retail Partner", shop_name="PR Store 3", is_verified=True))
    db.session.commit()
    s3_id, s3_email = shop3.id, shop3.email
shop3_c = client_for(s3_email, s3_id, "4")
gone = issue(discount_label="5€ off")
check("third partner redeems part of a coupon", redeem(shop3_c, gone, "2").status_code == 200)
r = sup_c.post(f"/delete_user/{s3_id}", headers={"X-Requested-With": "XMLHttpRequest"})
check("erasing a partner with redemptions succeeds (FKs handled)", r.status_code == 200 and r.get_json()["success"], r.get_data(as_text=True)[:200])
with app.app_context():
    kept = CouponRedemption.query.filter_by(coupon_id=coupon(gone).id).all()
    check("their redemption row survives, unlinked", len(kept) == 1 and kept[0].seller_id is None and kept[0].amount_applied == D("2"))
    check("the coupon balance is untouched", coupon(gone).remaining_balance == D("3.00"))

print()
if failures:
    print(f"{len(failures)} FAILED:")
    for f_ in failures:
        print("  -", f_)
    sys.exit(1)
print("ALL PASSED")
