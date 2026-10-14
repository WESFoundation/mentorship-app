"""All Mentors filters by country / state-province / city.

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
    app, db, User, MentorProfile, SupervisorProfile, resolve_location, mentor_location_parts,
)

stamp = dt.datetime.now().strftime("%H%M%S%f")
failures = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        failures.append(label)


CASES = [
    ("bangalore guy", "Bangalore, India"),
    ("bengaluru guy", "BENGALURU URBAN, India"),
    ("bengaluru 2 guy", "Bengaluru , India"),
    ("delhi guy", "Delhi, India"),
    ("pune guy", "Pune, India"),
    ("luxembourg guy", "Luxembourg, Pakistan"),
    ("amsterdam guy", "Amsterdam, Other"),
]

with app.app_context():
    sup = User(name="Loc Sup", email=f"loc_sup_{stamp}@t.com", user_type="0",
               created_at=dt.datetime.utcnow())
    db.session.add(sup)
    db.session.commit()
    # /supervisordashboard is behind @profile_required, so the supervisor needs
    # a complete profile to reach the All Mentors tab.
    db.session.add(SupervisorProfile(
        user_id=sup.id, organisation="WES", whatsapp="+352 000 000",
        location="Luxembourg, Luxembourg", role="Supervisor",
        additional_info="test", profile_picture="test.png"))
    db.session.commit()
    for name, legacy in CASES:
        u = User(name=name, email=f"loc_{name.replace(' ', '_')}_{stamp}@t.com",
                 user_type="1", created_at=dt.datetime.utcnow())
        db.session.add(u)
        db.session.flush()
        # Exactly what a mentor submitting the profile form would store.
        r = resolve_location(country=None, state=None, city=None, legacy_location=legacy)
        db.session.add(MentorProfile(user_id=u.id, profession="Tester", location=legacy))
        print(f"  {name:<20} legacy={legacy!r:<32} -> country={r['country']!r} "
              f"state={r['state']!r} city={r['city']!r}")
    db.session.commit()
    sup_email, sup_id = sup.email, sup.id

client = app.test_client()
with client.session_transaction() as s:
    s["email"] = sup_email
    s["user_id"] = sup_id
    s["user_type"] = "0"

r = client.get("/supervisor_find_mentor")
html = r.get_data(as_text=True)
check("GET /supervisor_find_mentor renders", r.status_code == 200, r.status_code)
for label in ("All Countries", "All States / Provinces", "All Cities"):
    check(f"'{label}' filter present", label in html)
check("legacy 'All Locations' filter removed", 'name="location"' not in html)

r = client.get("/supervisor_find_mentor?country=India")
html = r.get_data(as_text=True)
check("filter by country=India", r.status_code == 200)
check("Karnataka offered for India", "Karnataka" in html)
check("Telangana offered for India", "Telangana" in html)

r = client.get("/supervisor_find_mentor?country=India&state=Karnataka")
html = r.get_data(as_text=True)
check("filter India+Karnataka", r.status_code == 200)
check("city list narrows to Bengaluru Urban only",
      "Bengaluru Urban" in html and ">Hyderabad<" not in html)
for variant in ("bangalore guy", "bengaluru guy", "bengaluru 2 guy"):
    check(f"all three Bengaluru spellings kept: {variant}", variant in html)

r = client.get("/supervisor_find_mentor?country=Luxembourg")
html = r.get_data(as_text=True)
check("'Luxembourg, Pakistan' is filed under Luxembourg",
      r.status_code == 200 and "luxembourg guy" in html)

r = client.get("/supervisor_find_mentor?country=Netherlands")
html = r.get_data(as_text=True)
check("'Amsterdam, Other' is filed under Netherlands",
      r.status_code == 200 and "amsterdam guy" in html)

r = client.get("/supervisor_find_mentor?country=India&state=Karnataka&city=Bengaluru%20Urban")
html = r.get_data(as_text=True)
check("filter all three levels", r.status_code == 200 and "bangalore guy" in html)
check("non-matching mentors excluded", "pune guy" not in html)

r = client.get("/supervisor_find_mentor?country=India&state=Telangana")
html = r.get_data(as_text=True)
check("Telangana mentors excluded once state is set", "pune guy" not in html)

r = client.get("/api/search_mentors?q=Tester")
check("GET /api/search_mentors still works", r.status_code == 200, r.status_code)

# ---- mentee-facing find_mentor page ----
mentee = None
with app.app_context():
    mentee = User(name="Loc Mentee", email=f"loc_ee_{stamp}@t.com", user_type="2",
                  created_at=dt.datetime.utcnow())
    db.session.add(mentee)
    db.session.commit()
    mentee_email, mentee_id = mentee.email, mentee.id

with client.session_transaction() as s:
    s.clear()
    s["email"] = mentee_email
    s["user_id"] = mentee_id
    s["user_type"] = "2"
r = client.get("/find_mentor")
html = r.get_data(as_text=True)
check("GET /find_mentor renders", r.status_code == 200, r.status_code)
check("country filter on mentee page", "All Countries" in html)
check("state filter on mentee page", "All States" in html)
check("city filter on mentee page", "All Cities" in html)

r = client.get("/find_mentor?country=India&state=Karnataka&city=Bengaluru%20Urban")
check("mentee page accepts the same filters", r.status_code == 200, r.status_code)

# ---- supervisor dashboard mentors tab ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = sup_email
    s["user_id"] = sup_id
    s["user_type"] = "0"
r = client.get("/supervisordashboard?country=India&state=Karnataka")
html = r.get_data(as_text=True)
check("dashboard All Mentors tab accepts the filters", r.status_code == 200, r.status_code)
check("dashboard shows the country filter", "All Countries" in html)

# ---- cleanup ----
with app.app_context():
    ids = [sup.id, mentee_id]
    names = [c[0] for c in CASES]
    uids = [u.id for u in User.query.filter(User.name.in_(names)).all()]
    db.session.query(MentorProfile).filter(MentorProfile.user_id.in_(uids + ids)).delete(
        synchronize_session=False)
    db.session.query(SupervisorProfile).filter(
        SupervisorProfile.user_id.in_(ids)).delete(synchronize_session=False)
    db.session.query(User).filter(User.id.in_(uids + ids)).delete(synchronize_session=False)
    db.session.commit()

print()
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)