"""
anchor_tasks_checker.py
-----------------------
Utility to check and fix anchor mentorship tasks in real-time.

Features:
1. Audits all approved anchor mentorships in the database.
2. Checks that every anchor mentorship has all 20 MasterTasks assigned to the mentee and linked to the mentor.
3. Automatically identifies missing tasks (1-20) and creates them with appropriate due dates.
4. Can be run standalone from CLI: `python anchor_tasks_checker.py`
5. Can be imported and invoked dynamically: `check_and_fix_anchor_tasks()`
"""

import sys
import logging
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("anchor_tasks_checker")


def check_and_fix_anchor_tasks(mentorship_id=None, mentee_id=None, mentor_id=None, auto_commit=True):
    """
    Checks all active/approved anchor mentorships and fixes any missing anchor tasks (1-20).
    Ensures that tasks are assigned to mentee and visible to the mentor.
    
    Args:
        mentorship_id: Optional ID of a specific mentorship to check/fix.
        mentee_id: Optional mentee ID filter.
        mentor_id: Optional mentor ID filter.
        auto_commit: Whether to commit changes to the database immediately (default True).
        
    Returns:
        dict: Detailed audit and remediation report.
    """
    from app import app, db, MentorshipRequest, MenteeTask, MasterTask, is_anchor_mentorship, calculate_due_date

    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_checked": 0,
        "anchor_mentorships": 0,
        "mentorships_with_missing_tasks": 0,
        "tasks_created": 0,
        "details": []
    }

    with app.app_context():
        # Retrieve all master tasks templates (ordered 1 to 20)
        master_tasks = MasterTask.query.order_by(MasterTask.meeting_number).all()
        if not master_tasks:
            logger.error("No MasterTask records found in the database. Cannot assign anchor tasks.")
            return report

        master_tasks_by_num = {mt.meeting_number: mt for mt in master_tasks}
        all_meeting_numbers = set(master_tasks_by_num.keys())

        # Query approved mentorship requests
        query = MentorshipRequest.query.filter(
            MentorshipRequest.final_status == "approved"
        )
        if mentorship_id:
            query = query.filter(MentorshipRequest.id == int(mentorship_id))
        if mentee_id:
            query = query.filter(MentorshipRequest.mentee_id == int(mentee_id))
        if mentor_id:
            query = query.filter(MentorshipRequest.mentor_id == int(mentor_id))

        mentorship_requests = query.all()
        report["total_checked"] = len(mentorship_requests)

        for req in mentorship_requests:
            if not is_anchor_mentorship(req):
                continue

            report["anchor_mentorships"] += 1
            m_id = req.mentee_id
            mentor_id_val = req.mentor_id
            start_date = getattr(req, "created_at", None) or datetime.utcnow()

            # Find existing tasks for this mentee-mentor pair
            existing_tasks = MenteeTask.query.filter_by(
                mentee_id=m_id,
                mentor_id=mentor_id_val
            ).all()

            existing_nums = {t.meeting_number for t in existing_tasks if t.meeting_number is not None}
            existing_tids = {t.task_id for t in existing_tasks if t.task_id is not None}

            # Also check if any tasks exist for this mentee where mentor_id was missing/null
            unassigned_tasks = MenteeTask.query.filter(
                MenteeTask.mentee_id == m_id,
                MenteeTask.mentor_id.is_(None)
            ).all()
            for ut in unassigned_tasks:
                if ut.meeting_number in all_meeting_numbers:
                    ut.mentor_id = mentor_id_val
                    existing_nums.add(ut.meeting_number)
                    existing_tids.add(ut.task_id)

            missing_meeting_numbers = sorted(list(all_meeting_numbers - existing_nums))

            if missing_meeting_numbers:
                report["mentorships_with_missing_tasks"] += 1
                created_for_this = []

                for m_num in missing_meeting_numbers:
                    m_task = master_tasks_by_num.get(m_num)
                    if not m_task:
                        continue

                    # Double check task_id not already assigned
                    if m_task.id in existing_tids:
                        continue

                    due_date = calculate_due_date(start_date, m_task.month, m_task.meeting_number)

                    new_task = MenteeTask(
                        mentee_id=m_id,
                        mentor_id=mentor_id_val,
                        task_id=m_task.id,
                        meeting_number=m_task.meeting_number,
                        month=str(m_task.month),
                        status="pending",
                        progress=0,
                        assigned_date=datetime.utcnow(),
                        due_date=due_date
                    )
                    db.session.add(new_task)
                    created_for_this.append(m_num)
                    report["tasks_created"] += 1

                report["details"].append({
                    "mentorship_id": req.id,
                    "mentee_id": m_id,
                    "mentor_id": mentor_id_val,
                    "missing_meetings_fixed": created_for_this,
                    "total_existing_before": len(existing_tasks),
                    "total_now": len(existing_tasks) + len(created_for_this)
                })

                logger.info(
                    f"[FIXED] Mentorship #{req.id} (Mentee {m_id}, Mentor {mentor_id_val}): "
                    f"Created {len(created_for_this)} missing tasks: {created_for_this}"
                )

        if report["tasks_created"] > 0 and auto_commit:
            try:
                db.session.commit()
                logger.info(f"Successfully committed {report['tasks_created']} anchor tasks to database.")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Failed to commit anchor tasks: {e}")
                report["commit_error"] = str(e)

    return report


def main():
    print("=" * 70)
    print("      ANCHOR MENTORSHIP TASKS REAL-TIME CHECKER & REPAIR TOOL")
    print("=" * 70)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    result = check_and_fix_anchor_tasks(auto_commit=True)

    print(f"Total Mentorships Scanned  : {result['total_checked']}")
    print(f"Anchor Mentorships Verified : {result['anchor_mentorships']}")
    print(f"Mentorships with Missing    : {result['mentorships_with_missing_tasks']}")
    print(f"Tasks Created & Linked     : {result['tasks_created']}")
    print("-" * 70)

    if result["tasks_created"] > 0:
        print("Detailed Fixes:")
        for d in result["details"]:
            print(f"  • Mentorship #{d['mentorship_id']} (Mentee {d['mentee_id']} <-> Mentor {d['mentor_id']}): "
                  f"Added meetings {d['missing_meetings_fixed']} (Total now: {d['total_now']})")
    else:
        print("All anchor mentorships have their complete set of 20 tasks properly assigned!")
    print("=" * 70)


if __name__ == "__main__":
    main()
