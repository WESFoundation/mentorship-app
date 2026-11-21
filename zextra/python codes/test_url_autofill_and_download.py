"""Tests: (1) LinkedIn-URL-only profile autofill, (2) institution profile download buttons.

The profile provider is the built-in mock (no network). Disposable SQLite copy only.
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
os.environ["LINKEDIN_PROVIDER"] = "mock"

import app as application  # noqa: E402
import linkedin_provider as li  # noqa: E402
from app import app, db, User  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

stamp = dt.datetime.now().strftime("%H%M%S%f")
failures = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        failures.append(label)


def client(email, uid, utype):
    c = app.test_client()
    with c.session_transaction() as s:
        s["email"], s["user_id"], s["user_type"] = email, uid, utype
    return c


# ------------------------------------------------------------ URL validation
for good in ("https://www.linkedin.com/in/jane-doe", "linkedin.com/in/jane-doe/", "https://lu.linkedin.com/in/jane-doe?trk=x"):
    check(f"accepts {good}", li.normalize_url(good) == "https://www.linkedin.com/in/jane-doe", li.normalize_url(good))
for bad in ("", "https://evil.com/in/jane-doe", "https://www.linkedin.com/company/acme", "https://linkedin.com.evil.com/in/jane",
            "http://169.254.169.254/latest/meta-data", "https://www.linkedin.com/in/ab", "javascript:alert(1)"):
    try:
        li.normalize_url(bad)
        check(f"rejects {bad!r}", False)
    except li.LinkedInError as e:
        check(f"rejects {bad!r}", e.status == 400)

# ---------------------------------------------------------------- mapping
p = li._fetch_mock("https://www.linkedin.com/in/jane-doe")
m = li.map_to_fields(p, "mentor")
check("mentor mapping", m["role"] == "Senior Data Engineer" and m["organisation"] == "Acme Analytics"
      and m["skills"] == "Python, SQL, Airflow" and m["years_of_experience"] == "9", m)
check("mentor uses newest education", m["university_name"] == "University of Luxembourg" and m["graduation_year"] == "2015"
      and m["degree_name"] == "M.Sc." and m["field_of_study"] == "Computer Science", m)
e = li.map_to_fields(p, "mentee")
check("mentee mapping", e["current_role"] == "Senior Data Engineer" and e["last_role"] == "Data Engineer"
      and e["school_name"] == "University of Luxembourg" and e["key_skills"] == "Python, SQL, Airflow", e)
check("partial data maps partially", li.map_to_fields({"current_title": "Chef"}, "mentee") == {"current_role": "Chef"})
check("empty data maps to nothing", li.map_to_fields({}, "mentor") == {})

# ------------------------------------------------------------------ route
with app.app_context():
    mentor = User(name=f"UA Mentor {stamp}", email=f"ua_m_{stamp}@t.com", user_type="1", created_at=dt.datetime.utcnow())
    mentee = User(name=f"UA Mentee {stamp}", email=f"ua_e_{stamp}@t.com", user_type="2", created_at=dt.datetime.utcnow())
    db.session.add_all([mentor, mentee])
    db.session.commit()
    ids = {"m": (mentor.email, mentor.id), "e": (mentee.email, mentee.id)}

URL = "/ai/profile_from_linkedin_url"
good = {"url": "https://www.linkedin.com/in/jane-doe", "own_profile": True}
check("signed-out rejected", app.test_client().post(URL, json=good).status_code == 401)
mc = client(*ids["m"], "1")
check("must confirm own profile", mc.post(URL, json={"url": good["url"]}).status_code == 400)
check("bad URL is a 400", mc.post(URL, json={"url": "https://evil.com/in/x", "own_profile": True}).status_code == 400)
r = mc.post(URL, json=good)
j = r.get_json()
check("mentor lookup succeeds", r.status_code == 200 and j["success"] and j["fields"]["role"] == "Senior Data Engineer", j)
check("canonical URL returned for the link field", j["fields"]["linkedin_link"] == "https://www.linkedin.com/in/jane-doe")
r = client(*ids["e"], "2").post(URL, json=good)
check("mentee gets mentee fields", r.status_code == 200 and "current_role" in r.get_json()["fields"]
      and "role" not in r.get_json()["fields"], r.get_json())
r = mc.post(URL, json={"url": "https://www.linkedin.com/in/not-found", "own_profile": True})
check("unknown profile is a clean 404", r.status_code == 404, r.get_json())
os.environ["LINKEDIN_PROVIDER"] = ""
r = mc.post(URL, json=good)
check("unconfigured server says so (503)", r.status_code == 503 and "PDF" in r.get_json()["message"], r.get_json())
os.environ["LINKEDIN_PROVIDER"] = "peopledatalabs"
os.environ.pop("LINKEDIN_API_KEY", None)
r = mc.post(URL, json=good)
check("provider without a key is a clean 503", r.status_code == 503 and "LINKEDIN_API_KEY" in r.get_json()["message"], r.get_json())
os.environ["LINKEDIN_PROVIDER"] = "mock"

# ----------------------------- PDF/URL component present on the edit pages
with app.test_client() as c:
    for who, utype, path in ((ids["m"], "1", "/editmentorprofile"), (ids["e"], "2", "/editmenteeprofile")):
        r = client(*who, utype).get(path)
        body = r.get_data(as_text=True)
        check(f"{path} offers the LinkedIn link fill", r.status_code == 200 and "li-go-url" in body, r.status_code)

# ------------------------------------------- institution (Esha) download
ESHA = "esha01.wes@gmail.com"
with app.app_context():
    esha = User.query.filter_by(email=ESHA).first()
    check("Esha's institution account exists in the data copy", esha is not None and str(esha.user_type) == "3")
    mentors, mentees = application._get_institution_members(esha, include_paired=True)
    member = next((u for u in mentees if u.mentee_profile is not None), mentees[0] if mentees else None)
    member_mentor = mentors[0] if mentors else None
    member_ids = {u.id for u in mentors} | {u.id for u in mentees}
    outsider = User.query.filter(User.user_type.in_(["1", "2"]), ~User.id.in_(member_ids)).first()
    esha_id = esha.id
    m_id, m_name = member.id, member.name
    mm_id = member_mentor.id if member_mentor else None
    out_id = outsider.id if outsider else None
check("Esha has members to download", m_id is not None)

ec = client(ESHA, esha_id, "3")
for path, label in (("/institution_mentees", "mentees"), ("/institution_mentors", "mentors")):
    r = ec.get(path)
    body = r.get_data(as_text=True)
    check(f"Esha's {label} page shows View Profile and Download", r.status_code == 200 and "View Profile" in body
          and "institution/download_profile/" in body and "Download" in body, r.status_code)

r = ec.get(f"/institution/download_profile/{m_id}")
check("download returns an Excel file", r.status_code == 200 and "spreadsheetml" in r.content_type
      and "attachment" in r.headers.get("Content-Disposition", ""), (r.status_code, r.content_type))
ws = load_workbook(io.BytesIO(r.data)).active
cells = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
check("file contains the person's name and email", m_name in cells, cells[:6])
check("file has the profile section", any("profile" in c.lower() for c in cells))
check("secrets/paths are not exported", not any(k in " ".join(cells).lower() for k in ("consent token", "profile picture", "criminal certificate")))
if mm_id:
    check("mentor profile downloads too", ec.get(f"/institution/download_profile/{mm_id}").status_code == 200)
if out_id:
    check("someone outside her institution is refused", ec.get(f"/institution/download_profile/{out_id}").status_code == 404)
check("unknown user is a 404", ec.get("/institution/download_profile/99999999").status_code == 404)
check("a mentor cannot use the download", client(*ids["m"], "1").get(f"/institution/download_profile/{m_id}").status_code == 302)
check("signed-out cannot download", app.test_client().get(f"/institution/download_profile/{m_id}").status_code == 302)

print()
if failures:
    print(f"{len(failures)} FAILED:", *failures, sep="\n  - ")
    sys.exit(1)
print("ALL PASSED")
