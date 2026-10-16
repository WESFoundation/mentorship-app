"""SGM task category / all-mentors feedback / complete-on-first-feedback.

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
    app, db, User, MentorProfile, MenteeProfile, PersonalTask, TaskRating, MentorReflection,
    compute_task_progress_status, _mentor_task_query_for_user,
    _all_mentor_reflections, _mentor_submission_count,
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
    sup = make("SGM Test Supervisor", f"sgm_sup_{stamp}@t.com", "0")
    m1 = make("Mentor One", f"sgm_m1_{stamp}@t.com", "1")
    m2 = make("Mentor Two", f"sgm_m2_{stamp}@t.com", "1")
    e1 = make("Mentee One", f"sgm_e1_{stamp}@t.com", "2")
    e2 = make("Mentee Two", f"sgm_e2_{stamp}@t.com", "2")
    for m in (m1, m2):
        db.session.add(MentorProfile(user_id=m.id, profession="Tester"))
    for e in (e1, e2):
        db.session.add(MenteeProfile(user_id=e.id))
    db.session.commit()
    sup_email, m1_email, m2_email = sup.email, m1.email, m2.email
    m1_id, m2_id, e1_id = m1.id, m2.id, e1.id
    all_ids = [sup.id, m1.id, m2.id, e1.id, e2.id]

client = app.test_client()
with client.session_transaction() as s:
    s["email"] = sup_email
    s["user_id"] = sup.id
    s["user_type"] = "0"

start = (dt.datetime.now() + dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
resp = client.post("/supervisor/schedule_sgm_ajax", json={
    "title": "",                       # blank -> default with the mentor's name
    "mentor_id": m1_id,
    "mentee_ids": [e1_id],
    "date": start.split(" ")[0],
    "start_time": start.split(" ")[1],
    "duration": 60,
    "platform": "custom",
    "custom_link": "https://example.com/sgm",
})
data = resp.get_json()
check("POST /supervisor/schedule_sgm_ajax", resp.status_code == 200 and data.get("success"), data)
check("default title names the mentor",
      data.get("title") == "SGM: Group Mentoring & Fireside chat with Mentor One", data.get("title"))
check("response reports the SGM category", data.get("task_category") == "SGM", data.get("task_category"))
task_id = data.get("task_id")
check("an SGM task was created", bool(task_id), task_id)

with app.app_context():
    task = db.session.get(PersonalTask, task_id)
    check("task category is 'sgm'", task.category == "sgm", task.category)
    check("task.is_sgm", task.is_sgm)
    check("category_label is 'SGM'", task.category_label == "SGM", task.category_label)
    check("linked to its meeting", task.sgm_meeting_id is not None)
    check("mentor can access", task.mentor_has_access(m1_id))
    check("non-participant cannot access", not task.mentor_has_access(999999))

    st = compute_task_progress_status("personal", task.id, task.mentee_id, task.mentor_id, task_obj=task)
    check("before feedback the task is 'committed'", st == "committed", st)

# ---- first mentor submits: task becomes in-progress (not done until mentee + institute also submit) ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = m1_email
    s["user_id"] = m1_id
    s["user_type"] = "1"

r = client.post("/save_mentor_reflection", json={
    "task_type": "personal", "task_id": task_id, "text": "Great fireside chat.", "extra": "M1"})
res = r.get_json()
check("mentor reflection saved", res.get("success") is True, res)
check("task in-progress after only mentor submits", res.get("status") == "in-progress", res.get("status"))
check("submission count is 1", res.get("submission_count") == 1, res.get("submission_count"))

with app.app_context():
    check("db status synced to in-progress",
          db.session.get(PersonalTask, task_id).status == "in-progress")

# ---- a second mentor also contributes ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = m2_email
    s["user_id"] = m2_id
    s["user_type"] = "1"
r = client.post("/save_mentor_reflection", json={
    "task_type": "personal", "task_id": task_id, "text": "Strong turnout."})
check("a non-assigned mentor is refused on a non-SGM task",
      r.get_json().get("success") is False, r.get_json())

# Now verify multi-mentor SGM access works
with app.app_context():
    task = db.session.get(PersonalTask, task_id)
    task.sgm_mentor_ids = f",{m1_id},{m2_id},"
    db.session.commit()

r = client.post("/save_mentor_reflection", json={
    "task_type": "personal", "task_id": task_id, "text": "Strong turnout."})
res = r.get_json()
check("second SGM mentor can also submit", res.get("success") is True, res)
check("still in-progress (waiting for mentee and institute)", res.get("status") == "in-progress", res.get("status"))
check("submission count is now 2", res.get("submission_count") == 2, res.get("submission_count"))

with app.app_context():
    refs = _all_mentor_reflections("personal", task_id)
    ids = sorted(x.mentor_id for x in refs)
    check("BOTH mentors' reflections retained", ids == sorted([m1_id, m2_id]), ids)
    texts = sorted((x.text or "") for x in refs)
    check("no mentor's text was overwritten", texts == sorted(["Great fireside chat.", "Strong turnout."]), texts)

# ---- ratings are kept per mentor too ----
r = client.post("/rate_task/personal/%d" % task_id, json={
    "rating": 5, "feedback": "Useful session.", "strengths": "Engaged", "improvements": "More Q&A"})
check("mentor rating saved", r.get_json().get("success") is True, r.get_json())
with app.app_context():
    ratings = TaskRating.query.filter_by(task_id=task_id, task_type="personal").all()
    check("rating rows kept per mentor", len(ratings) == 1, len(ratings))

# ---- both mentors see the task in their list ----
with app.app_context():
    for mid in (m1_id, m2_id):
        seen = [t.id for t in _mentor_task_query_for_user(mid).all()]
        check(f"mentor {mid} sees the SGM task", task_id in seen)

# ---- combined feedback endpoint ----
r = client.get(f"/get_all_mentor_feedback/personal/{task_id}")
p = r.get_json()
check("combined feedback endpoint", p.get("success") and p.get("submitted_count") == 2, p)
check("flagged as SGM", p.get("is_sgm") is True)

# ---- mentee submits feedback ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = e1.email
    s["user_id"] = e1.id
    s["user_type"] = "2"
r = client.post("/save_mentee_feedback", json={
    "task_type": "personal", "task_id": task_id, "rating": 5, "text": "Learned a lot from mentors."})
check("mentee feedback saved", r.get_json().get("success") is True, r.get_json())

with app.app_context():
    st_after_mentee = compute_task_progress_status("personal", task_id, e1_id, m1_id)
    check("after mentor + mentee, status is still in-progress", st_after_mentee == "in-progress", st_after_mentee)

# ---- institute submits reflection: now all 3 have submitted, task becomes done ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = sup_email
    s["user_id"] = sup.id
    s["user_type"] = "0"
r = client.post("/save_institution_reflection", json={
    "task_type": "personal", "task_id": task_id, "text": "Great group session organized."})
check("institution reflection saved", r.get_json().get("success") is True, r.get_json())

with app.app_context():
    st_all_three = compute_task_progress_status("personal", task_id, e1_id, m1_id)
    check("task COMPLETE only after all 3 (mentee, mentor, institute) submit", st_all_three == "done", st_all_three)

# ---- supervisor sees SGM in the category filter ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = sup_email
    s["user_id"] = sup.id
    s["user_type"] = "0"
r = client.get("/get_supervisor_tasks_data")
tasks = r.get_json()["tasks"]
cats = sorted({t["category"] for t in tasks})
check("supervisor categories include SGM", "SGM" in cats, cats)
sgm_task = next((t for t in tasks if t["id"] == f"personal_{task_id}"), None)
check("SGM task present in supervisor payload", sgm_task is not None)
if sgm_task:
    check("supervisor sees isSGM", sgm_task["isSGM"] is True)
    check("supervisor sees 'done' status after all 3 submitted", sgm_task["status"] == "done", sgm_task["status"])
    check("supervisor sees all mentors' feedback", len(sgm_task["mentorFeedbacks"]) >= 2,
          sgm_task["mentorFeedbacks"])

r = client.get("/get_supervisor_tasks_data?category=SGM")
f = r.get_json()["tasks"]
check("can filter by category=SGM", len(f) >= 1 and all(t["category"] == "SGM" for t in f))

# ---- mentor task detail access ----
with client.session_transaction() as s:
    s.clear()
    s["email"] = m2_email
    s["user_id"] = m2_id
    s["user_type"] = "1"
r = client.get(f"/get_mentor_task_details/{task_id}?type=personal")
d = r.get_json()
check("SGM mentor can open the task detail", d.get("success") is True, d)
check("detail reports categoryLabel SGM", d.get("task", {}).get("categoryLabel") == "SGM", d.get("task"))

# ---- cleanup ----
with app.app_context():
    MentorReflection.query.filter(MentorReflection.task_id == task_id).delete(synchronize_session=False)
    TaskRating.query.filter(TaskRating.task_id == task_id).delete(synchronize_session=False)
    PersonalTask.query.filter(PersonalTask.id == task_id).delete(synchronize_session=False)
    ids = all_ids
    db.session.query(MentorProfile).filter(MentorProfile.user_id.in_(ids)).delete(synchronize_session=False)
    db.session.query(MenteeProfile).filter(MenteeProfile.user_id.in_(ids)).delete(synchronize_session=False)
    db.session.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()

print()
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)