"""End-to-end test for the mentor coupon / QR key flow.

  1. mentor generates coupon keys
  2. the QR image is served and the key resolves to the public verify page
  3. a seller opens the verify page and presses the button
  4. the key is marked used in the database
  5. a second attempt is rejected (single use)
  6. revoke / reinstate / reset / expiry behave

Runs ONLY against a disposable SQLite copy (see test_guard).
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_guard import bootstrap, ensure_test_schema, use_disposable_db  # noqa: E402

use_disposable_db(__file__)
bootstrap()
ensure_test_schema()
os.environ.setdefault("COUPON_PUBLIC_BASE_URL", "https://mentorship.weslux.lu")

from app import (  # noqa: E402
    app, db, User, MentorProfile, MentorCoupon, SellerProfile, CouponAssignment,
)

stamp = dt.datetime.now().strftime("%H%M%S%f")
failures = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        failures.append(label)


with app.app_context():
    mentor = User(name=f"Coupon Mentor {stamp}", email=f"coupon_m_{stamp}@t.com",
                  user_type="1", created_at=dt.datetime.utcnow())
    other = User(name=f"Other Mentor {stamp}", email=f"coupon_o_{stamp}@t.com",
                 user_type="1", created_at=dt.datetime.utcnow())
    shop = User(name=f"Weslux Store {stamp}", email=f"coupon_shop_{stamp}@t.com",
                user_type="4", created_at=dt.datetime.utcnow())
    db.session.add_all([mentor, other, shop])
    db.session.commit()
    db.session.add(MentorProfile(user_id=mentor.id, profession="Coach", organisation="Acme Coaching"))
    # A supervisor-verified partner shop, which is what the verify page now offers.
    db.session.add(SellerProfile(user_id=shop.id, partner_label="Retail Partner",
                                 shop_name="Weslux Store Berlin", is_verified=True))
    db.session.commit()
    mentor_email, mentor_id = mentor.email, mentor.id
    other_email, other_id = other.email, other.id
    shop_email, shop_id = shop.email, shop.id
    mentee = User(name=f"Coupon Mentee {stamp}", email=f"coupon_me_{stamp}@t.com",
                  user_type="2", created_at=dt.datetime.utcnow())
    supervisor = User(name=f"Coupon Supervisor {stamp}", email=f"coupon_sup_{stamp}@t.com",
                      user_type="0", created_at=dt.datetime.utcnow())
    db.session.add_all([mentee, supervisor])
    db.session.commit()
    mentee_id, supervisor_id = mentee.id, supervisor.id
    mentee_email, supervisor_email = mentee.email, supervisor.email

mentor_client = app.test_client()
with mentor_client.session_transaction() as s:
    s["email"] = mentor_email
    s["user_id"] = mentor_id
    s["user_type"] = "1"

sup_client = app.test_client()
with sup_client.session_transaction() as s:
    s["email"] = supervisor_email
    s["user_id"] = supervisor_id
    s["user_type"] = "0"

# Issuance now lives with the supervisor, and one coupon can go to many people.
r = sup_client.get("/supervisor/coupons")
check("GET /supervisor/coupons renders", r.status_code == 200, r.status_code)
check("the tab is called All Coupons", "All Coupons" in r.get_data(as_text=True))

r = mentor_client.get("/mentor/coupons")
check("GET /mentor/coupons renders", r.status_code == 200, r.status_code)
check("My Coupons offers a request form",
      "Request coupons" in r.get_data(as_text=True))
check("My Coupons no longer offers generation",
      "Generate coupons" not in r.get_data(as_text=True))

r = mentor_client.post("/mentor/coupons/create", json={"title": "nope"})
check("mentors can no longer self-issue",
      r.status_code == 403 and "mentorships team" in (r.get_json() or {}).get("message", ""), r.status_code)

r = sup_client.post("/supervisor/coupons/create", json={
    "title": "Free 30-min mentoring call",
    "description": "One free call with a WES mentor",
    "discount_label": "1 free session",
    "quantity": 3,
    "assignee_ids": [mentor_id, mentee_id],
})
data = r.get_json()
check("POST /supervisor/coupons/create", r.status_code == 200 and data.get("success"), data)
check("coupons assigned to 2 people", data.get("assigned_to") == 2, data.get("assigned_to"))
codes = list((data.get("urls") or {}).keys())
check("3 unique keys generated", len(codes) == 3 and len(set(codes)) == 3, codes)
check("keys have the WES- prefix", all(c.startswith("WES-") for c in codes), codes)
alphabet = "ABCDEFGHJKLMNPQRTUVWXYZ23456789"
check("keys use an unambiguous alphabet",
      all(ch in alphabet for c in codes for ch in c.split("-", 1)[1].replace("-", "")), codes)
urls = data["urls"]
first = codes[0]
check("QR target points at the weslux page",
      urls[first] == f"https://mentorship.weslux.lu/coupon/verify/{first}", urls[first])

# Every generated coupon went to every selected holder.
with app.app_context():
    held = {c.code: sorted(u.id for u in c.assignees)
            for c in MentorCoupon.query.filter(MentorCoupon.code.in_(codes)).all()}
    check("all 3 coupons went to mentor + mentee",
          all(v == sorted([mentor_id, mentee_id]) for v in held.values()), held)
    check("each holder has their own assignment rows",
          CouponAssignment.query.filter_by(user_id=mentee_id).count() >= 3)

r = mentor_client.get(f"/coupon/qr/{first}.png")
if r.status_code != 200:
    print("   QR error body:", r.get_data(as_text=True)[:400])
check("GET /coupon/qr/<code>.png returns a PNG",
      r.status_code == 200 and r.mimetype == "image/png", f"{r.status_code} {r.mimetype}")
check("PNG has a valid signature", r.data[:8] == b"\x89PNG\r\n\x1a\n")
check("PNG is non-trivial in size", len(r.data) > 200, len(r.data))

other_client = app.test_client()
with other_client.session_transaction() as s:
    s["email"] = other_email
    s["user_id"] = other_id
    s["user_type"] = "1"
r = other_client.get(f"/coupon/qr/{first}.png")
check("another mentor cannot fetch someone else's coupon QR", r.status_code == 404, r.status_code)

anon = app.test_client()
r = anon.get(f"/coupon/qr/{first}.png")
check("anonymous cannot fetch a coupon QR", r.status_code == 401, r.status_code)

# The coupon must be assigned to somebody before it can be redeemed.
with app.app_context():
    c = MentorCoupon.query.filter_by(code=first).first()
    check("the coupon is already assigned by the supervisor",
          sorted(u.id for u in c.assignees) == sorted([mentor_id, mentee_id]),
          [u.id for u in c.assignees])

r = anon.get(f"/coupon/verify/{first}")
html = r.get_data(as_text=True)
check("GET /coupon/verify/<code> is public", r.status_code == 200, r.status_code)
check("verify page shows the mentor", "Coupon Mentor" in html)
check("verify page shows the discount", "1 free session" in html)
check("verify page offers the verified-shop dropdown", "Weslux Store Berlin" in html)
check("verify page names the redeemer", f"Coupon Mentor {stamp}" in html)
check("tells the seller to apply the discount", "Apply the discount yourself" in html)

r = anon.get("/coupon/verify/NOPE-NOT-A-KEY")
check("unknown key returns 404", r.status_code == 404, r.status_code)
check("unknown key explains itself", "not recognised" in r.get_data(as_text=True))

# An unverified shop must be refused.
r = anon.post(f"/coupon/verify/{first}", data={"seller_account": "99999999", "redeemer_id": mentor_id})
check("an unverified shop is refused", r.status_code == 400, r.status_code)

# A redeemer who does not hold the coupon must be refused.
r = anon.post(f"/coupon/verify/{first}", data={"seller_account": shop_id, "redeemer_id": other_id})
check("a non-holder cannot redeem", r.status_code == 400, r.status_code)

r = anon.post(f"/coupon/verify/{first}", data={"seller_account": shop_id, "redeemer_id": mentor_id})
html = r.get_data(as_text=True)
check("POST /coupon/verify/<code> succeeds", r.status_code == 200, r.status_code)
check("confirmation shown", "Coupon verified" in html)

with app.app_context():
    c = MentorCoupon.query.filter_by(code=first).first()
    check("key marked used in the database", c.status == "used", c.status)
    check("used_at stamped", c.used_at is not None, c.used_at)
    check("seller recorded", c.used_by == "Weslux Store Berlin", c.used_by)
    check("seller_id recorded", c.seller_id == shop_id, c.seller_id)
    check("redeemer recorded", c.redeemed_by_user_id == mentor_id, c.redeemed_by_user_id)
    check("verification_count incremented", c.verification_count == 1, c.verification_count)
    check("is_usable now False", c.is_usable is False)

    r2 = anon.post(f"/coupon/verify/{first}", data={"seller_account": shop_id, "redeemer_id": mentee_id})
    check("second use is rejected", r2.status_code == 409, r2.status_code)
    check("rejection message shown", "already been used" in r2.get_data(as_text=True))
    check("verification_count NOT bumped",
          MentorCoupon.query.filter_by(code=first).first().verification_count == 1)
    check("other keys still active",
          all(MentorCoupon.query.filter_by(code=c).first().status == "active" for c in codes[1:]))

    second = codes[1]
    second_id = MentorCoupon.query.filter_by(code=second).first().id
    r = sup_client.post(f"/supervisor/coupons/{second_id}/status", json={"action": "revoke"})
    check("revoke works", r.get_json().get("success") and
          MentorCoupon.query.filter_by(code=second).first().status == "revoked")

    r = anon.post(f"/coupon/verify/{second}", data={"seller_account": shop_id, "redeemer_id": mentor_id})
    check("revoked key rejected by seller page", r.status_code == 409, r.status_code)
    check("revoked message shown", "withdrawn" in r.get_data(as_text=True))

    r = sup_client.post(f"/supervisor/coupons/{second_id}/status", json={"action": "reinstate"})
    check("reinstate works", r.get_json().get("success") and
          MentorCoupon.query.filter_by(code=second).first().status == "active")

    r = anon.post(f"/coupon/verify/{second}", data={"seller_account": shop_id})
    check("redeeming without naming a redeemer is refused", r.status_code == 400, r.status_code)

    row = MentorCoupon.query.filter_by(code=second).first()
    check("reinstated coupon carries no stale redemption",
          row.redeemed_by_user_id is None and row.seller_id is None,
          (row.redeemed_by_user_id, row.seller_id))
    check("second coupon is already assigned to the mentor",
          mentor_id in [u.id for u in row.assignees], [u.id for u in row.assignees])
    r = anon.post(f"/coupon/verify/{second}", data={"seller_account": shop_id, "redeemer_id": mentor_id})
    check("reinstated key verifies again", r.status_code == 200, r.status_code)

    first_id = MentorCoupon.query.filter_by(code=first).first().id
    r = sup_client.post(f"/supervisor/coupons/{first_id}/status", json={"action": "revoke"})
    check("a used key cannot be revoked", r.status_code == 400, r.status_code)

    r = sup_client.post(f"/supervisor/coupons/{first_id}/status", json={"action": "reset"})
    row = MentorCoupon.query.filter_by(code=first).first()
    check("reset clears usage", r.get_json().get("success") and row.status == "active"
          and row.used_at is None)

    expired = MentorCoupon(
        code="WES-EXPIRED-TEST1", mentor_id=mentor_id, title="Old coupon",
        status="active", expires_at=dt.datetime.utcnow() - dt.timedelta(days=1),
    )
    db.session.add(expired)
    db.session.commit()
    r = anon.post("/coupon/verify/WES-EXPIRED-TEST1")
    check("expired key rejected", r.status_code == 410, r.status_code)
    check("expired message shown", "expired" in r.get_data(as_text=True))

    r = mentor_client.get("/mentor/coupons")
    check("dashboard lists all generated coupons",
          all(c in r.get_data(as_text=True) for c in codes))

    db.session.query(MentorCoupon).filter(MentorCoupon.mentor_id == mentor_id).delete(
        synchronize_session=False)
    db.session.query(MentorProfile).filter(
        MentorProfile.user_id.in_([mentor_id, other_id])).delete(synchronize_session=False)
    db.session.query(User).filter(User.id.in_([mentor_id, other_id])).delete(
        synchronize_session=False)
    db.session.commit()

print()
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)