"""Institution coordinator: invite ALL institution mentees to an SGM.

Extra invitees (not in the selected list) are recorded as pending and must
request access + be approved by the coordinator before joining.

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
    app, db, User, Institution, MentorProfile, MenteeProfile, PersonalTask, MeetingRequest,
    _get_meeting_participants, _sgm_invite_state,
)

stamp = dt.datetime.now().strftime("%H%M%S%f")
failures = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        failures.append(label)


def make(name, email, utype, inst_id=None, inst_name=None):
    u = User(name=name, email=email, user_type=utype,
             institution_id=inst_id, institution=inst_name,
             created_at=dt.datetime.utcnow())
    db.session.add(u)
    db.session.commit()
    return u


with app.app_context():
    # Coordinator carries a real Institution row so BOTH lookup paths are exercised:
    #   legacy  -> mentees matched on User.institution (name)
    #   current -> mentees matched on User.institution_id
    inst = Institution(user_id=1, email_domain="testinst.example")
    db.session.add(inst)
    db.session.commit()
    coord = make("Coord", f"sgmc_coord_{stamp}@t.com", "3", inst_id=inst.id, inst_name="Test Institute")
    other_coord = make("Other Coord", f"sgmc_other_{stamp}@t.com", "3", inst_name="Other Institute")
    mentor = make("Inst Mentor", f"sgmc_m_{stamp}@t.com", "1", inst_name="Test Institute")
    sel = make("Selected Mentee", f"sgmc_sel_{stamp}@t.com", "2", inst_name="Test Institute")
    extra1 = make("Extra Mentee One", f"sgmc_x1_{stamp}@t.com", "2", inst_name="Test Institute")
    extra2 = make("Extra Mentee Two", f"sgmc_x2_{stamp}@t.com", "2", inst_id=inst.id)
    outsider = make("Outsider Mentee", f"sgmc_out_{stamp}@t.com", "2", inst_name="Other Institute")
    db.session.add(MentorProfile(user_id=mentor.id, profession="Tester"))
    for e in (sel, extra1, extra2, outsider):
        db.session.add(MenteeProfile(user_id=e.id))
    db.session.commit()
    ids = dict(coord=coord.id, other_coord=other_coord.id, mentor=mentor.id, sel=sel.id,
               extra1=extra1.id, extra2=extra2.id, outsider=outsider.id)
    coord_email, mentor_email, sel_email = coord.email, mentor.email, sel.email
    extra1_email, extra2_email, outsider_email = extra1.email, extra2.email, outsider.email

client = app.test_client()
with client.session_transaction() as s:
    s["email"] = coord_email
    s["user_id"] = ids["coord"]
    s["user_type"] = "3"

start = (dt.datetime.now() + dt.timedelta(days=9)).strftime("%Y-%m-%d %H:%M")

# ---- schedule with invite_all_mentees ----
resp = client.post("/institution/schedule_sgm_ajax", json={
    "title": "",
    "mentor_ids": [ids["mentor"]],
    "mentor_id": ids["mentor"],
    "mentee_ids": [ids["sel"]],
    "invite_all_mentees": True,
    "date": start.split(" ")[0],
    "start_time": start.split(" ")[1],
    "duration": 60,
    "platform": "custom",
    "custom_link": "https://example.com/sgm-inst",
})
data = resp.get_json()
check("POST /institution/schedule_sgm_ajax", resp.status_code == 200 and data.get("success"), data)
check("response flags invite_all_mentees", data.get("invited_all_mentees") is True, data.get("invited_all_mentees"))
check("2 institution mentees left pending", data.get("pending_mentee_count") == 2,
      data.get("pending_mentee_count"))
meeting_id = data.get("meeting_id")
check("meeting id returned", bool(meeting_id), meeting_id)

with app.app_context():
    p = _get_meeting_participants(meeting_id)
    check("participants marked invited_all_mentees", p.get("invited_all_mentees") is True, p.get("invited_all_mentees"))
    pending = set(p.get("pending_mentee_ids") or [])
    check("pending = the 2 unselected institution mentees",
          pending == {ids["extra1"], ids["extra2"]}, sorted(pending))
    check("out-of-institution mentee NOT invited", ids["outsider"] not in pending)
    check("selected mentee is a full participant", ids["sel"] in (p.get("mentee_ids") or []))
    check("outsider sees no invite", _sgm_invite_state(p, ids["outsider"]) == "none")
    check("selected mentee is approved", _sgm_invite_state(p, ids["sel"]) == "approved")
    check("extra mentees start pending",
          _sgm_invite_state(p, ids["extra1"]) == "pending" and _sgm_invite_state(p, ids["extra2"]) == "pending")
    # The selected mentee gets the per-mentee learning task AND is the anchor of the
    # shared SGM task, so two rows is correct here.
    tasks = PersonalTask.query.filter_by(mentee_id=ids["sel"]).all()
    check("selected mentee got the per-mentee learning task",
          any(t.title.startswith("Learning & Feedback:") for t in tasks), [t.title for t in tasks])
    check("selected mentee is the anchor of the shared SGM task",
          any((t.category or "").lower() == "sgm" for t in tasks), [t.category for t in tasks])
    check("pending mentee has NO task yet",
          PersonalTask.query.filter_by(mentee_id=ids["extra1"]).count() == 0)

# ---- extra mentee cannot request as the wrong person ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = outsider_email
    s["user_id"] = ids["outsider"]
    s["user_type"] = "2"
r = client.post(f"/sgm_request_to_join/{meeting_id}")
check("outsider cannot request (not invited)", r.get_json().get("success") is False, r.get_json())

# ---- extra mentee requests to join ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = extra1_email
    s["user_id"] = ids["extra1"]
    s["user_type"] = "2"
r = client.post(f"/sgm_request_to_join/{meeting_id}")
body = r.get_json()
check("invited mentee can request to join", body.get("success") is True, body)
check("state becomes requested", body.get("state") == "requested", body.get("state"))
r = client.post(f"/sgm_request_to_join/{meeting_id}")
check("duplicate request is refused", r.get_json().get("success") is False, r.get_json())

with app.app_context():
    p = _get_meeting_participants(meeting_id)
    check("requested list recorded", ids["extra1"] in (p.get("requested_mentee_ids") or []))

# ---- a mentee cannot approve ----
r = client.post(f"/sgm_review_invitee/{meeting_id}/{ids['extra1']}", json={"decision": "approve"})
check("mentee cannot approve others", r.status_code == 403, r.status_code)

# ---- another coordinator cannot approve ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = coord_email
    s["user_id"] = ids["coord"]
    s["user_type"] = "3"
r = client.post(f"/sgm_review_invitee/{meeting_id}/{ids['extra1']}", json={"decision": "bogus"})
check("invalid decision refused", r.get_json().get("success") is False, r.get_json())

# ---- coordinator approves ----
r = client.post(f"/sgm_review_invitee/{meeting_id}/{ids['extra1']}", json={"decision": "approve"})
body = r.get_json()
check("coordinator can approve", body.get("success") is True, body)
check("state becomes approved", body.get("state") == "approved", body.get("state"))

with app.app_context():
    p = _get_meeting_participants(meeting_id)
    check("approved mentee now a participant", ids["extra1"] in (p.get("mentee_ids") or []))
    check("approved mentee removed from pending",
          ids["extra1"] not in (p.get("pending_mentee_ids") or []))
    check("approved mentee removed from requested",
          ids["extra1"] not in (p.get("requested_mentee_ids") or []))
    check("approved mentee state", _sgm_invite_state(p, ids["extra1"]) == "approved")
    check("approved mentee got a learning task",
          PersonalTask.query.filter_by(mentee_id=ids["extra1"]).count() == 1)
    check("the other mentee is still pending",
          _sgm_invite_state(p, ids["extra2"]) == "pending")

# approving twice is refused
r = client.post(f"/sgm_review_invitee/{meeting_id}/{ids["extra1"]}", json={"decision": "approve"})
check("double approval refused", r.get_json().get("success") is False, r.get_json())

# ---- coordinator rejects the other ----
r = client.post(f"/sgm_review_invitee/{meeting_id}/{ids['extra2']}", json={"decision": "reject"})
check("coordinator can reject", r.get_json().get("success") is True, r.get_json())
with app.app_context():
    p = _get_meeting_participants(meeting_id)
    check("rejected state recorded", _sgm_invite_state(p, ids["extra2"]) == "rejected")
    check("rejected mentee has no task",
          PersonalTask.query.filter_by(mentee_id=ids["extra2"]).count() == 0)

# a rejected mentee cannot re-request
with client.session_transaction() as s:
    s.clear()
    s["email"] = extra2_email
    s["user_id"] = ids["extra2"]
    s["user_type"] = "2"
r = client.post(f"/sgm_request_to_join/{meeting_id}")
check("rejected mentee cannot re-request", r.get_json().get("success") is False, r.get_json())

# ---- without the flag, nobody extra is invited ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = coord_email
    s["user_id"] = ids["coord"]
    s["user_type"] = "3"
resp = client.post("/institution/schedule_sgm_ajax", json={
    "title": "Plain SGM",
    "mentor_ids": [ids["mentor"]],
    "mentee_ids": [ids["sel"]],
    "invite_all_mentees": False,
    "date": start.split(" ")[0],
    "start_time": start.split(" ")[1],
    "duration": 60,
    "platform": "custom",
    "custom_link": "https://example.com/sgm-plain",
})
data2 = resp.get_json()
check("plain schedule succeeds", data2.get("success") is True, data2)
check("no pending mentees without the flag", data2.get("pending_mentee_count") == 0,
      data2.get("pending_mentee_count"))
with app.app_context():
    p2 = _get_meeting_participants(data2.get("meeting_id"))
    check("extra mentee has no invite on a plain SGM",
          _sgm_invite_state(p2, ids["extra1"]) == "none")

# ---- a supervisor cannot use the institution-wide option ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = mentor_email
    s["user_id"] = ids["mentor"]
    s["user_type"] = "1"
resp = client.post("/supervisor/schedule_sgm_ajax", json={
    "title": "", "mentor_ids": [ids["mentor"]], "mentee_ids": [ids["sel"]],
    "invite_all_mentees": True,
    "date": start.split(" ")[0], "start_time": start.split(" ")[1],
    "duration": 60, "platform": "custom", "custom_link": "https://example.com/x",
})
check("mentor cannot schedule an SGM at all", resp.status_code == 403, resp.status_code)

print()
if failures:
    print("FAILURES:", failures)
    sys.exit(1)
print("FAILURES: none")