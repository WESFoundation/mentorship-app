"""Regression tests for three bugs that shipped broken and were only caught by hand.

1. A mentee invited to an institution-wide SGM (pending_mentee_ids) could not SEE the
   meeting on their calendar, so there was nothing to request.
2. The supervisor sidebar had no link to the All Coupons page.
3. The mentee sidebar had no link to My Coupons.

Runs ONLY against a disposable SQLite copy (see test_guard).
"""
import datetime as dt
import os
import sys

sys.path.insert(0, r"C:\Users\shrey\Downloads\wes lux\mentor connect\WES-Working\zextra\python codes")
from test_guard import bootstrap, ensure_test_schema, use_disposable_db  # noqa: E402

use_disposable_db("regress.py")
bootstrap()
ensure_test_schema()

from app import (  # noqa: E402
    app, db, User, MentorProfile, MenteeProfile, Institution, MeetingRequest,
    _save_meeting_participants, _get_meeting_participants, _sgm_invite_state,
)

stamp = dt.datetime.now().strftime("%H%M%S%f")
failures = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        failures.append(label)


def cl(email, uid, utype):
    c = app.test_client()
    with c.session_transaction() as s:
        s["email"] = email
        s["user_id"] = uid
        s["user_type"] = utype
    return c


with app.app_context():
    inst = Institution(user_id=1, email_domain="reg.example")
    db.session.add(inst)
    db.session.commit()

    coord = User(name="Reg Coord", email=f"r_coord_{stamp}@t.com", user_type="3",
                 institution_id=inst.id, institution="Reg Institute",
                 created_at=dt.datetime.utcnow())
    mentor = User(name="Reg Mentor", email=f"r_m_{stamp}@t.com", user_type="1",
                  institution_id=inst.id, created_at=dt.datetime.utcnow())
    selected = User(name="Reg Selected", email=f"r_sel_{stamp}@t.com", user_type="2",
                    institution_id=inst.id, created_at=dt.datetime.utcnow())
    pending = User(name="Reg Pending", email=f"r_pend_{stamp}@t.com", user_type="2",
                   institution_id=inst.id, created_at=dt.datetime.utcnow())
    db.session.add_all([coord, mentor, selected, pending])
    db.session.commit()
    db.session.add(MentorProfile(user_id=mentor.id, profession="T"))
    db.session.add(MenteeProfile(user_id=selected.id))
    db.session.add(MenteeProfile(user_id=pending.id))
    db.session.commit()
    I = dict(coord=coord.id, mentor=mentor.id, selected=selected.id, pending=pending.id)
    E = dict(coord=coord.email, mentor=mentor.email, pending=pending.email, selected=selected.email)

# ---------------------------------------------------------------------------
# 1. A pending-invited mentee MUST see the meeting on their calendar.
# ---------------------------------------------------------------------------
print("\n--- 1. pending invitee can see + request the SGM ---")

coord_c = cl(E["coord"], I["coord"], "3")
when = (dt.datetime.now() + dt.timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
r = coord_c.post("/institution/schedule_sgm_ajax", json={
    "title": "", "mentor_ids": [I["mentor"]], "mentee_ids": [I["selected"]],
    "invite_all_mentees": True,
    "date": when.split(" ")[0], "start_time": when.split(" ")[1],
    "duration": 60, "platform": "custom", "custom_link": "https://example.com/reg",
})
data = r.get_json()
check("SGM scheduled with invite-all", r.status_code == 200 and data.get("success"), data)
check("the unselected mentee is pending", I["pending"] in (data.get("pending_mentee_ids") or []),
      data.get("pending_mentee_ids"))
mid = data.get("meeting_id")

with app.app_context():
    p = _get_meeting_participants(mid)
    check("pending mentee is NOT in mentee_ids", I["pending"] not in (p.get("mentee_ids") or []))
    check("pending mentee IS in pending_mentee_ids", I["pending"] in (p.get("pending_mentee_ids") or []))
    check("state is 'pending'", _sgm_invite_state(p, I["pending"]) == "pending")

pending_c = cl(E["pending"], I["pending"], "2")
r = pending_c.get("/mentee_calendar")
html = r.get_data(as_text=True)
check("GET /mentee_calendar renders for the pending mentee", r.status_code == 200, r.status_code)
# NB: the title is embedded via Jinja |tojson, so "&" arrives escaped. Match a safe part.
check("BUG1: the pending invitee SEES the meeting on their calendar",
      "Fireside" in html and "SGM" in html,
      "meeting missing from calendar")
check("BUG1: the invite state is sent to the browser",
      "sgm_invite_state" in html and '"pending"' in html)
check("BUG1: the approval banner is rendered",
      "Invited - approval required" in html)
check("BUG1: the join request button is rendered", "sgm-request-btn" in html)
check("BUG1: no 500 / template error", "Traceback" not in html)

# The mentee can actually request to join it.
r = pending_c.post(f"/sgm_request_to_join/{mid}")
check("BUG1: the pending mentee can send a join request",
      r.status_code == 200 and r.get_json().get("success") is True, r.get_json())
with app.app_context():
    p = _get_meeting_participants(mid)
    check("request recorded", I["pending"] in (p.get("requested_mentee_ids") or []))
    check("state is now 'requested'", _sgm_invite_state(p, I["pending"]) == "requested")

# And the coordinator can approve.
r = coord_c.post(f"/sgm_review_invitee/{mid}/{I['pending']}", json={"decision": "approve"})
check("coordinator approves it", r.status_code == 200 and r.get_json().get("success"), r.get_json())
with app.app_context():
    p = _get_meeting_participants(mid)
    check("approved mentee became a participant", I["pending"] in (p.get("mentee_ids") or []))
    check("state is 'approved'", _sgm_invite_state(p, I["pending"]) == "approved")

# The selected mentee also still sees it (regression guard).
sel_c = cl(E["selected"], I["selected"], "2")
check("selected mentee still sees the meeting",
      "Fireside" in sel_c.get("/mentee_calendar").get_data(as_text=True))

# An unrelated mentee must NOT see it.
with app.app_context():
    outsider = User(name="Reg Outsider", email=f"r_out_{stamp}@t.com", user_type="2",
                    created_at=dt.datetime.utcnow())
    supervisor = User(name="Reg Supervisor", email=f"r_sup_{stamp}@t.com", user_type="0",
                      created_at=dt.datetime.utcnow())
    db.session.add_all([outsider, supervisor])
    db.session.commit()
    db.session.add(MenteeProfile(user_id=outsider.id))
    db.session.commit()
    OUT_EMAIL, OUT_ID = outsider.email, outsider.id
    SUP_EMAIL, SUP_ID = supervisor.email, supervisor.id
out_c = cl(OUT_EMAIL, OUT_ID, "2")
check("an unrelated mentee does NOT see the meeting",
      "Fireside" not in out_c.get("/mentee_calendar").get_data(as_text=True))
r = out_c.post(f"/sgm_request_to_join/{mid}")
check("an unrelated mentee cannot request to join", r.status_code == 403, r.status_code)

# ---------------------------------------------------------------------------
# 2 + 3. Navigation links must exist, or the pages are unreachable.
# ---------------------------------------------------------------------------
print("\n--- 2/3. navigation ---")

# The dashboards force profile completion and redirect, so assert the sidebar on the
# coupon pages themselves (both extend base2.html, which holds the nav).
sup_c = cl(SUP_EMAIL, SUP_ID, "0")
r = sup_c.get("/supervisor/coupons")
html = r.get_data(as_text=True)
check("supervisor can open All Coupons", r.status_code == 200, r.status_code)
check("BUG2: sidebar shows an 'All Coupons' nav item",
      'sidebar-nav-item' in html and "All Coupons" in html and "/supervisor/coupons" in html,
      "no All Coupons nav link")
check("BUG2: the nav item is marked active on that page",
      html.count("sidebar-nav-item active") >= 1)
check("BUG2: it shows the issuing form", "Issue new coupons" in html)
check("BUG2: it shows multi-assign controls", "Select all mentees" in html)

r = pending_c.get("/mentor/coupons")
html = r.get_data(as_text=True)
check("BUG3: mentee can open My Coupons", r.status_code == 200, r.status_code)
check("BUG3: sidebar shows a 'My Coupons' nav item",
      "sidebar-nav-item" in html and "My Coupons" in html and "/mentor/coupons" in html,
      "no My Coupons nav link for mentees")
check("BUG3: mentee's page has the request form", "Request coupons" in html)

# And the mentor still has the link (regression guard).
mentor_c = cl(E["mentor"], I["mentor"], "1")
check("BUG3: mentor still has 'My Coupons'",
      "My Coupons" in mentor_c.get("/mentor/coupons").get_data(as_text=True))

# A mentor must NOT be offered the All Coupons admin tab.
check("a mentor has no 'All Coupons' admin nav item",
      "/supervisor/coupons" not in mentor_c.get("/mentor/coupons").get_data(as_text=True))

print()
if failures:
    print("FAILURES:", failures)
    sys.exit(1)
print("ALL REGRESSION CHECKS PASSED")