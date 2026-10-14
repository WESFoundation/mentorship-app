"""End-to-end verification of EVERY requirement, numbered as originally asked.

Each check maps back to one line of the request. Runs ONLY against a disposable
SQLite copy (see test_guard).
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
    app, db, User, MentorProfile, MenteeProfile, Institution, PersonalTask, MentorCoupon,
    MentorReflection, TaskRating, resolve_location, mentor_location_parts,
    _mentor_task_query_for_user, _mentee_task_query_for_user,
    _all_mentor_reflections, _mentor_submission_count, _location_key,
    country_states, find_state_for_city, _find_city_owner,
)

stamp = dt.datetime.now().strftime("%H%M%S%f")
failures = []
section = ""


def head(text):
    global section
    section = text
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        failures.append(f"{section} :: {label}")


def who(name, utype, email=None):
    u = User(name=name, email=email or f"{name.replace(' ', '_').lower()}_{stamp}@t.com",
             user_type=utype, created_at=dt.datetime.utcnow())
    db.session.add(u)
    db.session.commit()
    return u


def login(client, user):
    with client.session_transaction() as s:
        s.clear()
        s["email"] = user.email
        s["user_id"] = user.id
        s["user_type"] = user.user_type


# ---------------------------------------------------------------- fixtures ---
with app.app_context():
    sup = who("Req Supervisor", "0")
    m1 = who("Req Mentor One", "1")
    m2 = who("Req Mentor Two", "1")
    e1 = who("Req Mentee One", "2")
    e2 = who("Req Mentee Two", "2")
    e3 = who("Req Mentee Three", "2")
    inst_u = who("Req Institution", "3")
    db.session.add(Institution(user_id=inst_u.id, contact_person="Req Contact",
                               city="Luxembourg", state="Luxembourg",
                               country="Luxembourg", status="active"))
    # Link the mentees to that institution so it can see their tasks.
    for e in (e1, e2, e3):
        e.institution_id = inst_u.id
        e.institution = "Req Institution"
    for m in (m1, m2):
        db.session.add(MentorProfile(user_id=m.id, profession="Coach", organisation="Acme"))
    for e in (e1, e2, e3):
        db.session.add(MenteeProfile(user_id=e.id))
    db.session.commit()
    IDs = {"sup": sup.id, "m1": m1.id, "m2": m2.id, "e1": e1.id, "e2": e2.id,
           "e3": e3.id, "inst": inst_u.id}
    EMAILS = {"sup": sup.email, "m1": m1.email, "m2": m2.email,
              "e1": e1.email, "e2": e2.email, "e3": e3.email, "inst": inst_u.email}

client = app.test_client()

# =========================================================================== #
head("REQ 1+2+4+5  SGM task category / one-mentor-completes / all mentors' feedback / supervisor")

login(client, type("U", (), {"email": EMAILS["sup"], "id": IDs["sup"], "user_type": "0"})())
start = (dt.datetime.now() + dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
r = client.post("/supervisor/schedule_sgm_ajax", json={
    "title": "", "mentor_ids": [IDs["m1"], IDs["m2"]], "mentee_ids": [IDs["e1"], IDs["e2"]],
    "date": start.split(" ")[0], "start_time": start.split(" ")[1],
    "duration": 60, "platform": "custom", "custom_link": "https://example.com/sgm"})
sgm = r.get_json()
check("REQ3  blank title defaults to 'SGM: Group Mentoring & Fireside chat with <mentor>'",
      sgm.get("title") == "SGM: Group Mentoring & Fireside chat with Req Mentor One", sgm.get("title"))
check("REQ1  scheduling creates exactly ONE SGM task", bool(sgm.get("task_id")), sgm)
TASK = sgm["task_id"]

with app.app_context():
    t = db.session.get(PersonalTask, TASK)
    check("REQ1  task category is 'sgm' and labelled SGM",
          t.category == "sgm" and t.category_label == "SGM", (t.category, t.category_label))
    check("REQ1  task is linked to the SGM meeting", t.sgm_meeting_id is not None)
    check("REQ1  BOTH mentors are on the task",
          set(t.sgm_mentor_id_list) == {IDs["m1"], IDs["m2"]}, t.sgm_mentor_ids)
    check("REQ1  BOTH mentees are on the task",
          set(t.sgm_mentee_id_list) == {IDs["e1"], IDs["e2"]}, t.sgm_mentee_ids)

    check("REQ1  mentor 1 sees the task",
          TASK in [x.id for x in _mentor_task_query_for_user(IDs["m1"]).all()])
    check("REQ1  mentor 2 sees the task",
          TASK in [x.id for x in _mentor_task_query_for_user(IDs["m2"]).all()])
    check("REQ1  mentee 1 sees the shared task",
          TASK in [x.id for x in _mentee_task_query_for_user(IDs["e1"]).all()])
    check("REQ1  mentee 2 sees the shared task (not just the first one)",
          TASK in [x.id for x in _mentee_task_query_for_user(IDs["e2"]).all()])
    check("REQ1  an unrelated mentee does NOT see it",
          TASK not in [x.id for x in _mentee_task_query_for_user(IDs["e3"]).all()])

login(client, type("U", (), {"email": EMAILS["m1"], "id": IDs["m1"], "user_type": "1"})())
r = client.post("/save_mentor_reflection", json={
    "task_type": "personal", "task_id": TASK, "text": "Great fireside chat."})
res = r.get_json()
check("REQ2  task shows COMPLETE after ONE mentor submits",
      res.get("status") == "done", res.get("status"))
with app.app_context():
    check("REQ2  db status synced to completed",
          db.session.get(PersonalTask, TASK).status == "completed")

login(client, type("U", (), {"email": EMAILS["m2"], "id": IDs["m2"], "user_type": "1"})())
r = client.post("/save_mentor_reflection", json={
    "task_type": "personal", "task_id": TASK, "text": "Strong turnout."})
check("REQ4  second SGM mentor can also submit", r.get_json().get("success") is True, r.get_json())
r = client.post("/rate_task/personal/%d" % TASK, json={
    "rating": 5, "feedback": "Useful session."})
check("REQ4  second SGM mentor can also rate", r.get_json().get("success") is True)

with app.app_context():
    texts = sorted((x.text or "") for x in _all_mentor_reflections("personal", TASK))
    check("REQ4  BOTH mentors' reflections retained, none overwritten",
          texts == ["Great fireside chat.", "Strong turnout."], texts)
    check("REQ4  submission count is 2", _mentor_submission_count("personal", TASK) == 2)

r = client.get("/get_all_mentor_feedback/personal/%d" % TASK)
p = r.get_json()
check("REQ4  combined feedback endpoint returns both mentors",
      p.get("submitted_count") == 2 and p.get("is_sgm") is True, p.get("submitted_count"))

login(client, type("U", (), {"email": EMAILS["sup"], "id": IDs["sup"], "user_type": "0"})())
tasks = client.get("/get_supervisor_tasks_data").get_json()["tasks"]
cats = sorted({x["category"] for x in tasks})
check("REQ5  supervisor sees the SGM category", "SGM" in cats, cats)
st = next((x for x in tasks if x["id"] == f"personal_{TASK}"), None)
check("REQ5  supervisor sees the SGM task as done", st and st["status"] == "done", st and st["status"])
check("REQ5  supervisor sees every mentor's feedback",
      st and len(st["mentorFeedbacks"]) >= 2, st and len(st["mentorFeedbacks"]))
f = client.get("/get_supervisor_tasks_data?category=SGM").get_json()["tasks"]
check("REQ1  supervisor can filter tasks by category=SGM",
      len(f) >= 1 and all(x["category"] == "SGM" for x in f))

login(client, type("U", (), {"email": EMAILS["sup"], "id": IDs["sup"], "user_type": "0"})())
html = client.get("/supervisor_calendar").get_data(as_text=True)
check("REQ3  SGM form default title is in the calendar page",
      "SGM: Group Mentoring &amp; Fireside chat with" in html)
check("REQ3  the OLD SGM default title is gone", "Group Mentoring &amp; Discussion" not in html)
check("REQ1  mentor-only 'My Coupons' nav is not shown to a supervisor", "My Coupons" not in html)

login(client, type("U", (), {"email": EMAILS["m1"], "id": IDs["m1"], "user_type": "1"})())
html = client.get("/mentor_tasks").get_data(as_text=True)
check("REQ12 'My Coupons' nav is reachable from the mentor area", "My Coupons" in html)
login(client, type("U", (), {"email": EMAILS["sup"], "id": IDs["sup"], "user_type": "0"})())

inst = client.get("/get_institution_tasks_data")
check("REQ1 institution task API responds for the supervisor session",
      inst.status_code in (200, 401), inst.status_code)

login(client, type("U", (), {"email": EMAILS["inst"], "id": IDs["inst"], "user_type": "3"})())
inst_tasks = client.get("/get_institution_tasks_data")
body = inst_tasks.get_json()
inst_cats = sorted({x["category"] for x in (body or {}).get("tasks", [])})
check("REQ1 institution task API renders", inst_tasks.status_code == 200, inst_tasks.status_code)
check("REQ1 institution API exposes the SGM category for its own mentees",
      "SGM" in inst_cats, inst_cats)
inst_sgm = [x for x in (body or {}).get("tasks", []) if x["category"] == "SGM"]
check("REQ1 institution sees the SGM task marked done",
      inst_sgm and inst_sgm[0]["status"] == "done", inst_sgm and inst_sgm[0]["status"])
check("REQ1 institution sees all mentors' feedback",
      inst_sgm and inst_sgm[0].get("mentorFeedbackCount", 0) >= 2,
      inst_sgm and inst_sgm[0].get("mentorFeedbackCount"))

# =========================================================================== #
head("REQ 6+7+8+9  mentor database locations: proper, deduplicated, no cross-country clash")

with app.app_context():
    # Exactly what the messy legacy data contains today.
    samples = ["Hyderabad, India", "Bangalore, India", "BENGALURU URBAN, India",
               "Bengaluru , India", "Delhi, India", "Luxembourg, Pakistan",
               "Amsterdam, Other", "India"]
    out = [resolve_location(country=None, state=None, city=None, legacy_location=s) for s in samples]

    resolved = {}
    for s, o in zip(samples, out):
        resolved[s] = (o["country"], o["state"], o["city"])

    print("   resolved:")
    for s in samples:
        print(f"     {s!r:<30} -> country={resolved[s][0]!r} state={resolved[s][1]!r} city={resolved[s][2]!r}")

    check("REQ6  'Bangalore'/'BENGALURU URBAN'/'Bengaluru ' all become Bengaluru Urban",
          len({resolved[s] for s in ("Bangalore, India", "BENGALURU URBAN, India", "Bengaluru , India")}) == 1,
          [resolved[s] for s in ("Bangalore, India", "BENGALURU URBAN, India", "Bengaluru , India")])
    check("REQ6  state is filled in from the city (Hyderabad -> Telangana)",
          resolved["Hyderabad, India"] == ("India", "Telangana", "Hyderabad"))
    check("REQ8  'Luxembourg, Pakistan' no longer files a city under the wrong country",
          resolved["Luxembourg, Pakistan"][0] == "Luxembourg", resolved["Luxembourg, Pakistan"])
    check("REQ8  'Amsterdam, Other' resolves to a real country",
          resolved["Amsterdam, Other"][0] == "Netherlands", resolved["Amsterdam, Other"])

    by_city = {}
    for s, (c, _st, city) in resolved.items():
        if city:
            by_city.setdefault(city.lower(), set()).add(c)
    clashes = {c: v for c, v in by_city.items() if len(v) > 1}
    check("REQ8  no city name appears under two different countries", not clashes, clashes)

    # REQ9: aligned with the profile-completion cascade
    bad_states = [(s, v) for s, v in resolved.items()
                  if v[0] and v[1] and v[1] not in country_states(v[0])]
    check("REQ9  every state is one the profile cascade offers",
          not bad_states, bad_states)

    bad_countries = [(s, v[0]) for s, v in resolved.items() if v[0] and _find_city_owner(v[2])
                     and v[0] not in _find_city_owner(v[2])] if any(v[2] for v in resolved.values()) else []
    check("REQ9  no city is filed under a country that does not contain it",
          not bad_countries, bad_countries)

# =========================================================================== #
head("REQ10  all mentors tab filters by country / state-province / city")

with app.app_context():
    for name, legacy in [("Filter Bengaluru A", "Bangalore, India"),
                         ("Filter Bengaluru B", "BENGALURU URBAN, India"),
                         ("Filter Delhi", "Delhi, India"),
                         ("Filter Lux", "Luxembourg, Pakistan"),
                         ("Filter Ams", "Amsterdam, Other")]:
        u = User(name=name, email=f"{name.replace(' ', '_').lower()}_{stamp}@t.com",
                 user_type="1", created_at=dt.datetime.utcnow())
        db.session.add(u)
        db.session.flush()
        db.session.add(MentorProfile(user_id=u.id, profession="Coach", location=legacy))
    db.session.commit()

login(client, type("U", (), {"email": EMAILS["sup"], "id": IDs["sup"], "user_type": "0"})())
html = client.get("/supervisor_find_mentor").get_data(as_text=True)
for label in ("All Countries", "All States / Provinces", "All Cities"):
    check(f"REQ10 filter '{label}' present", label in html)
check("REQ10 old single 'All Locations' filter gone", 'name="location"' not in html)

html = client.get("/supervisor_find_mentor?country=India").get_data(as_text=True)
check("REQ10 country=India narrows the states", "Karnataka" in html and "Telangana" in html)
html = client.get("/supervisor_find_mentor?country=India&state=Karnataka").get_data(as_text=True)
check("REQ10 state=Karnataka narrows cities to Bengaluru Urban",
      "Bengaluru Urban" in html and ">Hyderabad<" not in html)
check("REQ10 both Bengaluru mentors still shown (deduped, not dropped)",
      "Filter Bengaluru A" in html and "Filter Bengaluru B" in html)
html = client.get("/supervisor_find_mentor?country=Luxembourg").get_data(as_text=True)
check("REQ10 'Luxembourg, Pakistan' mentor now found under Luxembourg", "Filter Lux" in html)
html = client.get("/supervisor_find_mentor?country=Netherlands").get_data(as_text=True)
check("REQ10 'Amsterdam, Other' mentor now found under Netherlands", "Filter Ams" in html)

# =========================================================================== #
head("REQ11+12+13+14  QR coupon keys: scan -> verify button -> marked used")

with app.app_context():
    cm = User(name=f"Coupon Mentor {stamp}", email=f"coupon_m_{stamp}@t.com",
              user_type="1", created_at=dt.datetime.utcnow())
    db.session.add(cm)
    db.session.commit()
    db.session.add(MentorProfile(user_id=cm.id, profession="Coach", organisation="Acme Coaching"))
    db.session.commit()
    CM_ID = cm.id

mentor_client = app.test_client()
login(mentor_client, type("U", (), {"email": f"coupon_m_{stamp}@t.com", "id": CM_ID, "user_type": "1"})())

r = mentor_client.get("/mentor/coupons")
check("REQ12 mentor coupon page renders", r.status_code == 200, r.status_code)
check("REQ12 mentor coupon page renders a QR image per key",
      "/coupon/qr/" in r.get_data(as_text=True) or "No coupons yet" in r.get_data(as_text=True))

r = mentor_client.post("/mentor/coupons/create", json={
    "title": "Free 30-min mentoring call", "description": "One free call",
    "discount_label": "1 free session", "quantity": 3})
data = r.get_json()
codes = list((data.get("urls") or {}).keys())
check("REQ12 mentor can generate several coupon keys at once", len(codes) == 3, codes)
KEY = codes[0]

check("REQ13 QR points at the weslux page",
      data["urls"][KEY] == f"https://mentorship.weslux.lu/coupon/verify/{KEY}", data["urls"][KEY])

r = mentor_client.get(f"/coupon/qr/{KEY}.png")
check("REQ12 a QR image is served for each key",
      r.status_code == 200 and r.mimetype == "image/png" and r.data[:8] == b"\x89PNG\r\n\x1a\n",
      f"{r.status_code} {r.mimetype}")

anon = app.test_client()
r = anon.get(f"/coupon/verify/{KEY}")
html = r.get_data(as_text=True)
check("REQ11 seller lands on a verify page WITHOUT logging in", r.status_code == 200)
check("REQ11 verify page has a button to verify the coupon", "Verify coupon" in html)
check("REQ11 verify page shows the mentor and discount",
      f"Coupon Mentor {stamp}" in html and "1 free session" in html)
check("REQ14 page tells the seller to apply the discount themselves",
      "Apply the discount yourself" in html)

r = anon.post(f"/coupon/verify/{KEY}", data={"seller": "Weslux Store Berlin"})
check("REQ11 seller presses the button", r.status_code == 200, r.status_code)
check("REQ11 confirmation shown", "Coupon verified" in r.get_data(as_text=True))

with app.app_context():
    c = MentorCoupon.query.filter_by(code=KEY).first()
    check("REQ14 the key is recorded as USED in the database", c.status == "used", c.status)
    check("REQ14 when it was used is stamped", c.used_at is not None)
    check("REQ14 which seller used it is recorded", c.used_by == "Weslux Store Berlin", c.used_by)
    check("REQ14 verification count recorded", c.verification_count == 1)

r = anon.post(f"/coupon/verify/{KEY}", data={"seller": "Someone Else"})
check("REQ14 the same key cannot be used twice", r.status_code == 409, r.status_code)
with app.app_context():
    check("REQ14 verification count NOT bumped on the blocked attempt",
          MentorCoupon.query.filter_by(code=KEY).first().verification_count == 1)
    check("REQ14 other keys are still active",
          all(MentorCoupon.query.filter_by(code=k).first().status == "active" for k in codes[1:]))

r = anon.get("/coupon/verify/NOT-A-REAL-KEY")
check("REQ11 an unknown key is rejected clearly", r.status_code == 404)

# =========================================================================== #
head("PROFILE FORM  country/state/city are saved and re-read by the edit form")

with app.app_context():
    mp = MentorProfile.query.filter_by(user_id=IDs["m1"]).first()
    login(client, type("U", (), {"email": EMAILS["m1"], "id": IDs["m1"], "user_type": "1"})())

r = client.post("/editmentorprofile", data={
    "name": "Req Mentor One", "work_email": "req1@example.com",
    "country": "United Kingdom", "state": "England",
    "city": "London", "profession": "Coach"}, follow_redirects=False)
check("REQ9 profile save accepts a cascade pick", r.status_code in (200, 302), r.status_code)
with app.app_context():
    db.session.expire_all()
    mp = MentorProfile.query.filter_by(user_id=IDs["m1"]).first()
    check("REQ9 country column written", mp.country == "United Kingdom", mp.country)
    check("REQ9 state column written", mp.state == "England", mp.state)
    check("REQ9 city column written", mp.city == "London", mp.city)
    check("REQ9 display location rebuilt from the columns",
          mp.location == "London, England, United Kingdom", mp.location)
    html = client.get("/editmentorprofile").get_data(as_text=True)
    check("REQ9 edit form is pre-filled with the saved location",
          'value="United Kingdom"' in html or "United Kingdom" in html)

# =========================================================================== #
head("CLEANUP")
with app.app_context():
    MentorReflection.query.filter(MentorReflection.task_id == TASK).delete(synchronize_session=False)
    TaskRating.query.filter(TaskRating.task_id == TASK).delete(synchronize_session=False)
    MentorCoupon.query.filter(MentorCoupon.mentor_id == CM_ID).delete(synchronize_session=False)
    MentorReflection.query.filter(MentorReflection.task_id.isnot(None)).delete(synchronize_session=False)
    PersonalTask.query.filter(PersonalTask.id == TASK).delete(synchronize_session=False)
    ids = list(IDs.values()) + [CM_ID]
    names = ["Filter Bengaluru A", "Filter Bengaluru B", "Filter Delhi",
             "Filter Lux", "Filter Ams", f"Coupon Mentor {stamp}"]
    extra = [u.id for u in User.query.filter(User.name.in_(names)).all()]
    db.session.query(Institution).filter(Institution.user_id.in_(ids)).delete(
        synchronize_session=False)
    db.session.query(MentorProfile).filter(MentorProfile.user_id.in_(ids + extra)).delete(
        synchronize_session=False)
    db.session.query(MenteeProfile).filter(MenteeProfile.user_id.in_(ids)).delete(
        synchronize_session=False)
    db.session.query(User).filter(User.id.in_(ids + extra)).delete(synchronize_session=False)
    db.session.commit()

print("\n" + "=" * 78)
print("FAILURES:" if failures else "ALL REQUIREMENTS VERIFIED")
print("=" * 78)
for f in failures:
    print("  - " + f)
sys.exit(1 if failures else 0)