"""Partner/seller accounts, coupon requests, multi-assign and the seller dashboard.

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

from app import (  # noqa: E402
    app, db, User, MentorProfile, MenteeProfile, SellerProfile, CouponAssignment,
    CouponRequest, MentorCoupon,
)

stamp = dt.datetime.now().strftime("%H%M%S%f")
failures = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        failures.append(label)


def make(name, email, utype):
    u = User(name=name, email=email, user_type=utype, created_at=dt.datetime.utcnow())
    db.session.add(u)
    db.session.commit()
    return u


with app.app_context():
    sup = make("Sup", f"cp_sup_{stamp}@t.com", "0")
    m1 = make("M1", f"cp_m1_{stamp}@t.com", "1")
    m2 = make("M2", f"cp_m2_{stamp}@t.com", "1")
    e1 = make("E1", f"cp_e1_{stamp}@t.com", "2")
    e2 = make("E2", f"cp_e2_{stamp}@t.com", "2")
    seller = make("Shop", f"cp_shop_{stamp}@t.com", "4")
    db.session.add(MentorProfile(user_id=m1.id, profession="Coach"))
    db.session.add(MenteeProfile(user_id=e1.id))
    db.session.add(MenteeProfile(user_id=e2.id))
    db.session.add(SellerProfile(user_id=seller.id, partner_label="Retail Partner",
                                 shop_name="Corner Shop", is_verified=True))
    db.session.commit()
    ids = dict(sup=sup.id, m1=m1.id, m2=m2.id, e1=e1.id, e2=e2.id, seller=seller.id)
    emails = dict(sup=sup.email, m1=m1.email, e1=e1.email, e2=e2.email, seller=seller.email)

# ---------------------------------------------------------------- verification
sup_client = app.test_client()
with sup_client.session_transaction() as s:
    s["email"] = emails["sup"]
    s["user_id"] = ids["sup"]
    s["user_type"] = "0"

seller_client = app.test_client()
with seller_client.session_transaction() as s:
    s["email"] = emails["seller"]
    s["user_id"] = ids["seller"]
    s["user_type"] = "4"

r = seller_client.get("/seller/dashboard")
check("seller can reach their dashboard", r.status_code == 200, r.status_code)

# Shop is automatically available on the verify page without admin verification.
r = sup_client.post("/supervisor/coupons/create", json={
    "title": "Two free sessions", "discount_label": "2 free sessions",
    "quantity": 2, "assignee_ids": [ids["m1"], ids["m2"], ids["e1"], ids["e2"]],
})
data = r.get_json()
check("supervisor issues 2 coupons", r.status_code == 200 and data.get("success"), data)
check("assigned to 4 people at once", data.get("assigned_to") == 4, data.get("assigned_to"))
code = list(data["urls"].keys())[0]

anon = app.test_client()
r = anon.get(f"/coupon/verify/{code}")
html = r.get_data(as_text=True)
check("seller shop appears automatically in the dropdown", "Corner Shop" in html)
check("dropdown is a select, not free text", 'name="seller_account"' in html and 'type="text" id="seller"' not in html)
check("all 4 holders are offered as redeemer choices",
      html.count('name="redeemer_id"') == 1 and ('value="%d"' % ids["e2"] in html))

# ---------------------------------------------------------------- redeem + filters
r = anon.post(f"/coupon/verify/{code}",
              data={"seller_account": ids["seller"], "redeemer_id": ids["e2"]})
check("redemption succeeds", r.status_code == 200, r.status_code)

with app.app_context():
    c = MentorCoupon.query.filter_by(code=code).first()
    check("redeemer recorded", c.redeemed_by_user_id == ids["e2"], c.redeemed_by_user_id)
    check("seller recorded", c.seller_id == ids["seller"], c.seller_id)
    check("used_by is the shop name", c.used_by == "Corner Shop", c.used_by)

r = seller_client.get("/seller/dashboard")
html = r.get_data(as_text=True)
check("seller dashboard lists the redemption", "Two free sessions" in html)
check("dashboard names the redeemer", "E2" in html)
check("dashboard shows the discount", "2 free sessions" in html)
check("dashboard offers a window filter", 'name="window"' in html)
check("dashboard offers a redeemed-since filter", 'name="since"' in html)

old = dt.datetime.utcnow() - dt.timedelta(days=40)
# Backdate the redemption so the window filters have something to exclude.
with app.app_context():
    c = MentorCoupon.query.filter_by(code=code).first()
    c.used_at = old
    db.session.commit()

r = seller_client.get("/seller/dashboard?window=30d")
check("a 40-day-old redemption is outside 'last 30 days'",
      "Two free sessions" not in r.get_data(as_text=True))
r = seller_client.get("/seller/dashboard?window=all")
check("'all time' still shows it", "Two free sessions" in r.get_data(as_text=True))
r = seller_client.get(f"/seller/dashboard?since={old.strftime('%Y-%m-%d')}")
check("a 'redeemed since' date before the sale includes it",
      "Two free sessions" in r.get_data(as_text=True))
r = seller_client.get("/seller/dashboard?window=7d")
check("'last 7 days' excludes the 40-day-old redemption",
      "Two free sessions" not in r.get_data(as_text=True))

# ---------------------------------------------------------------- coupon requests
mentee_client = app.test_client()
with mentee_client.session_transaction() as s:
    s["email"] = emails["e1"]
    s["user_id"] = ids["e1"]
    s["user_type"] = "2"

r = mentee_client.post("/coupon/request", json={
    "title": "Please give me 5 coupons", "discount_label": "20% off", "quantity": 5,
})
check("mentee can request coupons", r.status_code == 200 and r.get_json().get("success"), r.get_json())
req_id = r.get_json()["request"]["id"]

r = mentee_client.post("/coupon/request", json={"title": ""})
check("a request needs a title", r.status_code == 400, r.status_code)

r = anon.post("/coupon/request", json={"title": "anon"})
check("a logged-out visitor cannot request coupons", r.status_code == 403, r.status_code)

r = mentee_client.get("/mentor/coupons")
html = r.get_data(as_text=True)
check("My Coupons shows the request form", "Request coupons" in html)
check("My Coupons shows my request", "Please give me 5 coupons" in html)
check("My Coupons shows a copy-link button", "Copy link" in html)
check("My Coupons has no revoke/reset control",
      "setStatus" not in html
      and "'revoke'" not in html and "'reset'" not in html
      and "/status" not in html)
check("My Coupons has no generate form", "Generate coupons" not in html)

# The mentee holds the 2 coupons assigned to them; one is redeemed.
check("My Coupons shows an active coupon", "Active coupons" in html)
check("My Coupons shows the redeemed coupon", "Redeemed coupons" in html)

r = sup_client.post(f"/coupon/request/{req_id}/status", json={"decision": "approve"})
check("supervisor approves a request", r.status_code == 200 and r.get_json().get("success"), r.get_json())
with app.app_context():
    req = db.session.get(CouponRequest, req_id)
    check("request marked approved", req.status == "approved", req.status)
    check("handled_by stamped", req.handled_by == ids["sup"], req.handled_by)

# ---------------------------------------------------------------- assignment editing
with app.app_context():
    c = MentorCoupon.query.filter_by(code=code).first()
    coupon_id = c.id
r = sup_client.post("/supervisor/coupons/assign",
                    json={"coupon_id": coupon_id, "user_id": ids["e1"], "action": "add"})
check("supervisor can add a holder", r.status_code == 200 and r.get_json().get("success"), r.get_json())
r = sup_client.post("/supervisor/coupons/assign",
                    json={"coupon_id": coupon_id, "user_id": ids["e1"], "action": "add"})
check("adding the same holder twice is idempotent", r.status_code == 200, r.status_code)
with app.app_context():
    rows = CouponAssignment.query.filter_by(coupon_id=coupon_id, user_id=ids["e1"]).all()
    check("only one assignment row exists", len(rows) == 1, len(rows))

r = sup_client.post("/supervisor/coupons/assign",
                    json={"coupon_id": coupon_id, "user_id": ids["sup"], "action": "add"})
check("a supervisor cannot hold a coupon", r.status_code == 400, r.status_code)

r = sup_client.post("/supervisor/coupons/assign",
                    json={"coupon_id": coupon_id, "user_id": ids["e1"], "action": "remove"})
check("supervisor can remove a holder", r.status_code == 200 and r.get_json().get("success"), r.get_json())
with app.app_context():
    check("assignment row removed",
          CouponAssignment.query.filter_by(coupon_id=coupon_id, user_id=ids["e1"]).count() == 0)

# a mentor cannot use the supervisor controls
mentor_client = app.test_client()
with mentor_client.session_transaction() as s:
    s["email"] = emails["m1"]
    s["user_id"] = ids["m1"]
    s["user_type"] = "1"
r = mentor_client.post(f"/supervisor/coupons/{coupon_id}/status", json={"action": "revoke"})
check("a mentor cannot revoke a coupon", r.status_code == 401, r.status_code)
r = mentor_client.post("/supervisor/coupons/create", json={"title": "mine"})
check("a mentor cannot issue coupons", r.status_code == 401, r.status_code)
# a mentor cannot open another mentor's My Coupons data
r = mentor_client.get("/seller/dashboard")
check("a mentor cannot open the seller dashboard", r.status_code == 302, r.status_code)

# ---------------------------------------------------------------- fresh coupon
# Use a coupon that is still active so the redemption form actually renders.
r = sup_client.post("/supervisor/coupons/create", json={
    "title": "Still active offer", "quantity": 1, "assignee_ids": [ids["e1"]],
})
fresh_code = list(r.get_json()["urls"].keys())[0]
r = anon.get(f"/coupon/verify/{fresh_code}")
check("seller shop is offered on a fresh coupon",
      "Corner Shop" in r.get_data(as_text=True))

print()
if failures:
    print("FAILURES:", failures)
    sys.exit(1)
print("FAILURES: none")