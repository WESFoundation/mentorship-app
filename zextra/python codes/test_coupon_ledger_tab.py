"""Tests: My Coupons > Coupon Ledger tab (Total spent / value available / money saved + period menu).

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

import app as application  # noqa: E402
from app import app, db, User, MentorCoupon, CouponRedemption  # noqa: E402

D = decimal.Decimal
stamp = dt.datetime.now().strftime("%H%M%S%f")
failures = []
application.send_email_reminder = lambda *a, **k: None


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + str(extra)) if extra and not cond else ""))
    if not cond:
        failures.append(label)


def client(email, uid, utype):
    c = app.test_client()
    with c.session_transaction() as s:
        s["email"], s["user_id"], s["user_type"] = email, uid, utype
    return c


with app.app_context():
    mk = lambda n, t, ut: User(name=f"{n} {stamp}", email=f"lg_{t}_{stamp}@t.com", user_type=ut, created_at=dt.datetime.utcnow())
    mentor, mentee, other, sup = mk("L Mentor", "m", "1"), mk("L Mentee", "e", "2"), mk("L Other", "o", "2"), mk("L Sup", "u", "0")
    db.session.add_all([mentor, mentee, other, sup])
    db.session.commit()
    I = {k: (v.email, v.id) for k, v in dict(m=mentor, e=mentee, o=other, u=sup).items()}

sup_c = client(*I["u"], "0")
mentee_c = client(*I["e"], "2")
mentor_c = client(*I["m"], "1")


def issue(label, holder="e", **extra):
    body = {"title": "Ledger test", "description": "d", "quantity": 1, "assignee_ids": [I[holder][1]], "discount_label": label}
    body.update(extra)
    r = sup_c.post("/supervisor/coupons/create", json=body)
    assert r.status_code == 200, r.get_json()
    return list(r.get_json()["urls"])[0]


def add_redemption(code, holder, days_ago, goods, applied, cur="EUR", voided=False, after=None):
    with app.app_context():
        c = MentorCoupon.query.filter_by(code=code).first()
        db.session.add(CouponRedemption(
            coupon_id=c.id, redeemed_by_user_id=I[holder][1], created_at=dt.datetime.utcnow() - dt.timedelta(days=days_ago),
            goods_total=D(goods), goods_currency=cur, discount_amount=D(applied), amount_applied=D(applied),
            balance_after=D(after) if after is not None else None, voided_at=dt.datetime.utcnow() if voided else None))
        db.session.commit()


def ledger(c, **q):
    r = c.get("/mentor/coupons/ledger", query_string=q)
    return r.status_code, (r.get_json() or {})


# ---- empty state
code, j = ledger(mentee_c)
check("empty ledger loads (200)", code == 200 and j["success"] and j["spent"] == {} and j["saved"] == {} and j["entries"] == [], j)

# ---- data: mentee has a 20€ coupon (balance-tracked) used for 5 + 3, plus other-period / other-user / voided rows
k20 = issue("Voucher", face_value="20", face_currency="EUR")
add_redemption(k20, "e", 10, "30.00", "5.00", after="15.00")     # in the last month
add_redemption(k20, "e", 3, "12.50", "3.00", after="12.00")      # in the last month
add_redemption(k20, "e", 100, "40.00", "4.00")                   # year only
add_redemption(k20, "e", 400, "99.00", "9.00")                   # neither
add_redemption(k20, "e", 5, "77.00", "7.00", voided=True)        # voided: must not count
add_redemption(k20, "o", 5, "88.00", "8.00")                     # someone else's: must not count
add_redemption(k20, "e", 2, "50.00", "2.50", cur="USD")          # second currency
with app.app_context():                                          # make the live balance what the rows imply
    c = MentorCoupon.query.filter_by(code=k20).first()
    c.remaining_balance = D("12.00")
    db.session.commit()

code, j = ledger(mentee_c, period="month")
check("month: spent = 30 + 12.50 (EUR) and 50 (USD)", j["spent"] == {"EUR": "42.50", "USD": "50.00"}, j["spent"])
check("month: saved = 5 + 3 (EUR) and 2.50 (USD)", j["saved"] == {"EUR": "8.00", "USD": "2.50"}, j["saved"])
check("month: 3 rows, newest first", len(j["entries"]) == 3 and j["entries"][0]["currency"] == "USD", [e["date"] for e in j["entries"]])
check("EUR listed before other currencies", list(j["spent"])[0] == "EUR")
check("voided and other users' rows excluded", all(e["bill"] not in ("77.00", "88.00") for e in j["entries"]))

code, j = ledger(mentee_c, period="year")
check("year adds the 100-day-old purchase, not the 400-day-old one",
      j["spent"]["EUR"] == "82.50" and j["saved"]["EUR"] == "12.00", (j["spent"], j["saved"]))

today = dt.datetime.utcnow().date()   # rows are stamped in UTC, so ranges are built from the UTC calendar
code, j = ledger(mentee_c, period="custom", **{"from": (today - dt.timedelta(days=120)).isoformat(), "to": (today - dt.timedelta(days=60)).isoformat()})
check("custom range picks only the 100-day-old purchase", j["spent"] == {"EUR": "40.00"} and len(j["entries"]) == 1, j)
code, j = ledger(mentee_c, period="custom", **{"from": today.isoformat(), "to": today.isoformat()})
check("custom 'today only' includes nothing older", j["success"] and j["entries"] == [], j)
code, j = ledger(mentee_c, period="custom", **{"from": (today - dt.timedelta(days=3)).isoformat(), "to": today.isoformat()})
check("custom range end day is inclusive (3-day-old and 2-day-old rows)", len(j["entries"]) == 2, j)

# A user east of UTC can already be on "tomorrow": picking their own today must not be rejected,
# and it must not pull in anything beyond now.
code, j = ledger(mentee_c, period="custom", **{"from": (today - dt.timedelta(days=3)).isoformat(), "to": (today + dt.timedelta(days=1)).isoformat()})
check("end date one day ahead of UTC (user's local 'today') is accepted", code == 200 and j["success"] and len(j["entries"]) == 2, (code, j.get("message")))

# ---- available value is "now", independent of period
k5 = issue("5€ off")                                        # untouched flat coupon: 5 available even before first view
kpct = issue("10% off up to 10€")                           # no cash value
kused = issue("Voucher", face_value="9", face_currency="EUR")
krev = issue("Voucher", face_value="9", face_currency="EUR")
kexp = issue("Voucher", face_value="9", face_currency="EUR")
with app.app_context():
    MentorCoupon.query.filter_by(code=kused).first().status = "used"
    MentorCoupon.query.filter_by(code=krev).first().status = "revoked"
    MentorCoupon.query.filter_by(code=kexp).first().expires_at = dt.datetime.utcnow() - dt.timedelta(days=1)
    db.session.commit()
for p in ("month", "year"):
    code, j = ledger(mentee_c, period=p)
    check(f"available ({p}) = 12 (partly used 20) + 5 flat, excludes used/revoked/expired",
          j["available"] == {"EUR": "17.00"}, j["available"])
check("percent coupon is counted but has no cash value", j["other_available_coupons"] == 1, j["other_available_coupons"])
code, j = ledger(mentor_c)
check("a different holder sees none of it", j["spent"] == {} and j["available"] == {} and j["entries"] == [], j)

# ---- validation + auth
for label, q in (("unknown period", dict(period="decade")),
                 ("custom without dates", dict(period="custom")),
                 ("custom bad date", dict(period="custom", **{"from": "nope", "to": "2026-01-01"})),
                 ("custom from after to", dict(period="custom", **{"from": "2026-05-02", "to": "2026-05-01"})),
                 ("custom end in the future", dict(period="custom", **{"from": today.isoformat(), "to": (today + dt.timedelta(days=2)).isoformat()}))):
    code, j = ledger(mentee_c, **q)
    check(f"{label} -> 400 with a message", code == 400 and not j["success"] and j.get("message"), (code, j))
check("signed-out -> 401", app.test_client().get("/mentor/coupons/ledger").status_code == 401)
check("supervisor -> 401", sup_c.get("/mentor/coupons/ledger").status_code == 401)

# ---- page
for who, c in (("mentee", mentee_c), ("mentor", mentor_c)):
    r = c.get("/mentor/coupons")
    b = r.get_data(as_text=True)
    check(f"{who} page has both tabs", r.status_code == 200 and "tabBtnCoupons" in b and "tabBtnLedger" in b and "Coupon Ledger" in b, r.status_code)
    check(f"{who} page has the 3 cards", all(t in b for t in ("Total spent", "Coupon value available", "Total money saved")))
    check(f"{who} page has the three-dot menu + custom dates", "ledMenuBtn" in b and "Last year" in b and "ledFrom" in b and "ledTo" in b)
    check(f"{who} page still has existing coupons content", "Request coupons" in b and "Active coupons" in b)

print()
if failures:
    print(f"{len(failures)} FAILED:", *failures, sep="\n  - ")
    sys.exit(1)
print("ALL PASSED")
