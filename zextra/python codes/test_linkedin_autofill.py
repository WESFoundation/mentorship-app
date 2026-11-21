"""Tests for the LinkedIn-PDF profile autofill route (/ai/profile_from_linkedin).

The AI call itself is stubbed: this checks auth, upload validation, rate limiting,
field whitelisting per role, and that nothing is saved. Disposable SQLite only.
"""
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_guard import bootstrap, ensure_test_schema, use_disposable_db  # noqa: E402

use_disposable_db(__file__)
bootstrap()
ensure_test_schema()

import app as application  # noqa: E402
import ai_service  # noqa: E402
from app import app, db, User, MentorProfile  # noqa: E402

stamp = dt.datetime.now().strftime("%H%M%S%f")
failures = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        failures.append(label)


calls = []


def fake_extract(pdf_bytes, role):
    calls.append(role)
    allowed = ai_service.PROFILE_FIELDS[role]
    raw = {"role": "Staff Engineer", "skills": ["Python", "Flask"], "research_work": "Paper A, Patent B",
           "current_role": "Intern", "password": "hunter2", "is_admin": True}
    return ai_service._clean(raw, allowed)


ai_service.extract_profile_from_pdf = fake_extract

with app.app_context():
    mentor = User(name=f"LI Mentor {stamp}", email=f"li_m_{stamp}@t.com", user_type="1", created_at=dt.datetime.utcnow())
    mentee = User(name=f"LI Mentee {stamp}", email=f"li_e_{stamp}@t.com", user_type="2", created_at=dt.datetime.utcnow())
    inst = User(name=f"LI Inst {stamp}", email=f"li_i_{stamp}@t.com", user_type="3", created_at=dt.datetime.utcnow())
    db.session.add_all([mentor, mentee, inst])
    db.session.commit()
    db.session.add(MentorProfile(user_id=mentor.id, role="Existing Role"))
    db.session.commit()
    who = {k: (u.email, u.id, u.user_type) for k, u in (("mentor", mentor), ("mentee", mentee), ("inst", inst))}


def client(k):
    c = app.test_client()
    with c.session_transaction() as s:
        s["email"], s["user_id"], s["user_type"] = who[k]
    return c


PDF = b"%PDF-1.4 fake"


def post(c, data=PDF, name="p.pdf"):
    return c.post("/ai/profile_from_linkedin", data={"file": (io.BytesIO(data), name)},
                  content_type="multipart/form-data")


check("signed-out is rejected", post(app.test_client()).status_code == 401)
check("institution users are rejected", post(client("inst")).status_code == 401)
check("missing file is a 400", client("mentor").post("/ai/profile_from_linkedin", data={}).status_code == 400)
check("non-PDF is a 400", post(client("mentor"), b"hello").status_code == 400)
check("oversized PDF is a 400", post(client("mentor"), PDF + b"x" * (5 * 1024 * 1024 + 1)).status_code == 400)
check("rejected uploads never reach the AI", calls == [], calls)

r = post(client("mentor"))
j = r.get_json()
check("mentor upload succeeds", r.status_code == 200 and j["success"], j)
check("mentor gets mentor fields incl. research_work",
      j["fields"].get("role") == "Staff Engineer" and j["fields"].get("research_work") == "Paper A, Patent B", j["fields"])
check("list values are joined to text", j["fields"].get("skills") == "Python, Flask", j["fields"])
check("unknown / dangerous keys are dropped", "password" not in j["fields"] and "is_admin" not in j["fields"]
      and "current_role" not in j["fields"], j["fields"])
check("mentor extraction used the mentor spec", calls[-1] == "mentor")

r = post(client("mentee"))
j = r.get_json()
check("mentee gets mentee fields only", r.status_code == 200 and j["fields"] == {"current_role": "Intern"}, j.get("fields"))

with app.app_context():
    check("nothing is saved by the route", MentorProfile.query.filter_by(user_id=who["mentor"][1]).first().role == "Existing Role")

ai_service.extract_profile_from_pdf = lambda b, r_: {}
r = post(client("mentor"))
check("empty extraction is a 422", r.status_code == 422, r.status_code)


def boom(b, r_):
    raise ai_service.AIError("service down")


ai_service.extract_profile_from_pdf = boom
r = post(client("mentor"))
check("AI outage is a clean 502", r.status_code == 502 and r.get_json()["message"] == "service down", r.status_code)

application._ai_calls.clear()
ai_service.extract_profile_from_pdf = fake_extract
codes = [post(client("mentee")).status_code for _ in range(application.AI_CALLS_PER_HOUR + 1)]
check("rate limit kicks in after the hourly budget", codes[-1] == 429 and codes[0] == 200, codes[-2:])

print()
if failures:
    print(f"{len(failures)} FAILED:", *failures, sep="\n  - ")
    sys.exit(1)
print("ALL PASSED")
