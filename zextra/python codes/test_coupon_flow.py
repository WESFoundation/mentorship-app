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

from app import app, db, User, MentorProfile, MentorCoupon  # noqa: E402

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
    db.session.add_all([mentor, other])
    db.session.commit()
    db.session.add(MentorProfile(user_id=mentor.id, profession="Coach", organisation="Acme Coaching"))
    db.session.commit()
    mentor_email, mentor_id = mentor.email, mentor.id
    other_email, other_id = other.email, other.id

mentor_client = app.test_client()
with mentor_client.session_transaction() as s:
    s["email"] = mentor_email
    s["user_id"] = mentor_id
    s["user_type"] = "1"

r = mentor_client.get("/mentor/coupons")
check("GET /mentor/coupons renders", r.status_code == 200, r.status_code)
check("dashboard explains the flow", "Generate coupons" in r.get_data(as_text=True))

r = mentor_client.post("/mentor/coupons/create", json={
    "title": "Free 30-min mentoring call",
    "description": "One free call with a WES mentor",
    "discount_label": "1 free session",
    "quantity": 3,
})
data = r.get_json()
check("POST /mentor/coupons/create", r.status_code == 200 and data.get("success"), data)
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

r = anon.get(f"/coupon/verify/{first}")
html = r.get_data(as_text=True)
check("GET /coupon/verify/<code> is public", r.status_code == 200, r.status_code)
check("verify page shows the mentor", "Coupon Mentor" in html)
check("verify page shows the discount", "1 free session" in html)
check("verify page has the verify button", "Verify coupon" in html)
check("tells the seller to apply the discount", "Apply the discount yourself" in html)

r = anon.get("/coupon/verify/NOPE-NOT-A-KEY")
check("unknown key returns 404", r.status_code == 404, r.status_code)
check("unknown key explains itself", "not recognised" in r.get_data(as_text=True))

r = anon.post(f"/coupon/verify/{first}", data={"seller": "Weslux Store Berlin"})
html = r.get_data(as_text=True)
check("POST /coupon/verify/<code> succeeds", r.status_code == 200, r.status_code)
check("confirmation shown", "Coupon verified" in html)

with app.app_context():
    c = MentorCoupon.query.filter_by(code=first).first()
    check("key marked used in the database", c.status == "used", c.status)
    check("used_at stamped", c.used_at is not None, c.used_at)
    check("seller recorded", c.used_by == "Weslux Store Berlin", c.used_by)
    check("verification_count incremented", c.verification_count == 1, c.verification_count)
    check("is_usable now False", c.is_usable is False)

    r2 = anon.post(f"/coupon/verify/{first}", data={"seller": "Someone Else"})
    check("second use is rejected", r2.status_code == 409, r2.status_code)
    check("rejection message shown", "already been used" in r2.get_data(as_text=True))
    check("verification_count NOT bumped",
          MentorCoupon.query.filter_by(code=first).first().verification_count == 1)
    check("other keys still active",
          all(MentorCoupon.query.filter_by(code=c).first().status == "active" for c in codes[1:]))

    second = codes[1]
    second_id = MentorCoupon.query.filter_by(code=second).first().id
    r = mentor_client.post(f"/mentor/coupons/{second_id}/status", json={"action": "revoke"})
    check("revoke works", r.get_json().get("success") and
          MentorCoupon.query.filter_by(code=second).first().status == "revoked")

    r = anon.post(f"/coupon/verify/{second}")
    check("revoked key rejected by seller page", r.status_code == 409, r.status_code)
    check("revoked message shown", "withdrawn" in r.get_data(as_text=True))

    r = mentor_client.post(f"/mentor/coupons/{second_id}/status", json={"action": "reinstate"})
    check("reinstate works", r.get_json().get("success") and
          MentorCoupon.query.filter_by(code=second).first().status == "active")

    r = anon.post(f"/coupon/verify/{second}")
    check("reinstated key verifies again", r.status_code == 200, r.status_code)

    first_id = MentorCoupon.query.filter_by(code=first).first().id
    r = mentor_client.post(f"/mentor/coupons/{first_id}/status", json={"action": "revoke"})
    check("a used key cannot be revoked", r.status_code == 400, r.status_code)

    r = mentor_client.post(f"/mentor/coupons/{first_id}/status", json={"action": "reset"})
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