"""
Mobile API Blueprint for Mentor Connect Flutter Application.
Provides secure, unified REST endpoints for:
- Authentication & Sessions
- Mentee Profile, Dashboard Stats, Tasks, & Connections
- Mentor Profile, Requests, & Mentees
- Institution & Admin Metrics
- Notifications
Replaces all direct PostgreSQL client queries in the Flutter app.
"""

from flask import Blueprint, request, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import or_, and_, func
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

api_bp = Blueprint("mobile_api", __name__, url_prefix="/api")


def get_current_user_from_req(User):
    """
    Extract authenticated user from Session or Authorization header (Bearer email/token).
    """
    email = session.get("email")
    if not email:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            # If token is email or simple token
            if "@" in token:
                email = token

    if not email:
        email = request.args.get("email") or (request.is_json and request.json.get("email"))

    if email:
        return User.query.filter(func.lower(User.email) == email.strip().lower()).first()
    return None


def register_mobile_api(app, db, User, MentorProfile, MenteeProfile, Institution, SupervisorProfile, MenteeTask, MentorshipRequest, MeetingRequest, Notification, calculate_mentor_rating_func=None):
    """Register all mobile API endpoints with the Flask app."""

    # -------------------------------------------------------------
    # 1. AUTHENTICATION & LOGIN / REGISTER
    # -------------------------------------------------------------
    @api_bp.route("/auth/login", methods=["POST"])
    def api_login():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""

        if not email:
            return jsonify({"success": False, "message": "Email is required"}), 400

        user = User.query.filter(func.lower(User.email) == email).first()
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        # Verify password if user has password set
        if user.password:
            valid = False
            try:
                valid = check_password_hash(user.password, password)
            except Exception:
                valid = (user.password == password)

            if not valid and password != user.password:
                return jsonify({"success": False, "message": "Invalid password"}), 401

        # Determine normalized role: '0'=admin/supervisor, '1'=mentor, '2'=mentee, '3'=institution
        raw_role = str(user.user_type or "2").strip()
        role = raw_role
        if raw_role in ("admin", "supervisor", "0"):
            role = "0"
        elif raw_role in ("mentor", "1"):
            role = "1"
        elif raw_role in ("institution", "3"):
            role = "3"
        else:
            role = "2"

        session["user_id"] = user.id
        session["email"] = user.email
        session["user_type"] = role
        session.permanent = True

        return jsonify({
            "success": True,
            "token": user.email,  # Mobile client stores this in SharedPreferences
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": role,
                "is_corporate": getattr(user, "is_corporate", False),
            }
        })

    @api_bp.route("/auth/register", methods=["POST"])
    def api_register():
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        user_type = str(data.get("user_type") or "2").strip()

        if not email or not name:
            return jsonify({"success": False, "message": "Name and email are required"}), 400

        existing = User.query.filter(func.lower(User.email) == email).first()
        if existing:
            return jsonify({"success": False, "message": "User already exists with this email"}), 409

        hashed_password = generate_password_hash(password, method="pbkdf2:sha256", salt_length=8) if password else None
        new_user = User(
            name=name,
            email=email,
            password=hashed_password,
            user_type=user_type,
            created_at=datetime.utcnow()
        )
        db.session.add(new_user)
        db.session.commit()

        try:
            if user_type == "1":
                mentor_p = MentorProfile(user_id=new_user.id, name=new_user.name, email=new_user.email)
                db.session.add(mentor_p)
                db.session.commit()
            elif user_type == "2":
                mentee_p = MenteeProfile(user_id=new_user.id, name=new_user.name, email=new_user.email)
                db.session.add(mentee_p)
                db.session.commit()
        except Exception as e:
            logger.warning("Could not auto-create profile row: %s", e)
            db.session.rollback()

        return jsonify({
            "success": True,
            "message": "User account created successfully",
            "user": {
                "id": new_user.id,
                "name": new_user.name,
                "email": new_user.email,
                "role": user_type
            }
        }), 201

    # -------------------------------------------------------------
    # 2. MENTEE ENDPOINTS
    # -------------------------------------------------------------
    @api_bp.route("/mentee/profile", methods=["GET"])
    def api_get_mentee_profile():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        profile = MenteeProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            # Fallback basic profile
            return jsonify({
                "success": True,
                "profile": {
                    "id": user.id,
                    "user_id": str(user.id),
                    "numeric_user_id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "who_am_i": "student",
                    "career_goal": "",
                    "school_college_name": "",
                    "institution_name": "",
                    "profile_picture": None,
                    "status": "active"
                }
            })

        pic = profile.profile_picture
        if pic and not pic.startswith("http"):
            pic = f"/static/uploads/{pic}"

        return jsonify({
            "success": True,
            "profile": {
                "id": profile.id,
                "user_id": str(user.id),
                "numeric_user_id": user.id,
                "name": user.name,
                "email": user.email,
                "who_am_i": profile.who_am_i or "student",
                "education_level": profile.education_level or "",
                "institution_name": profile.institution_name or profile.school_college_name or "",
                "school_college_name": profile.school_college_name or profile.institution_name or "",
                "career_goal": profile.career_goal or profile.goal or "",
                "goal": profile.goal or profile.career_goal or "",
                "profile_picture": pic,
                "status": profile.status or "active"
            }
        })

    @api_bp.route("/mentee/profile", methods=["PUT", "POST"])
    def api_update_mentee_profile():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        name = data.get("name")
        career_goal = data.get("career_goal") or data.get("goal")
        school_name = data.get("school_name") or data.get("institution_name")
        profile_picture = data.get("profile_picture")

        if name:
            user.name = name.strip()

        profile = MenteeProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            profile = MenteeProfile(user_id=user.id)
            db.session.add(profile)

        if career_goal is not None:
            profile.goal = career_goal
            profile.career_goal = career_goal
        if school_name is not None:
            profile.school_college_name = school_name
            profile.institution_name = school_name
        if profile_picture:
            profile.profile_picture = profile_picture

        try:
            db.session.commit()
            return jsonify({"success": True, "message": "Profile updated successfully"})
        except Exception as e:
            db.session.rollback()
            logger.error("Error updating mentee profile: %s", e)
            return jsonify({"success": False, "message": str(e)}), 500

    @api_bp.route("/mentee/stats", methods=["GET"])
    def api_get_mentee_stats():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        # Active mentors count
        active_mentors = MentorshipRequest.query.filter(
            MentorshipRequest.mentee_id == user.id,
            or_(
                MentorshipRequest.final_status == "approved",
                MentorshipRequest.supervisor_status == "approved",
                MentorshipRequest.mentor_status == "accepted"
            )
        ).count()

        # Sessions done
        sessions_done = MeetingRequest.query.filter(
            or_(MeetingRequest.requester_id == user.id, MeetingRequest.requested_to_id == user.id),
            MeetingRequest.status == "completed"
        ).count()

        # Upcoming sessions
        upcoming_meetings = MeetingRequest.query.filter(
            or_(MeetingRequest.requester_id == user.id, MeetingRequest.requested_to_id == user.id),
            ~MeetingRequest.status.in_(["completed", "rejected"])
        ).count()

        return jsonify({
            "success": True,
            "stats": {
                "active_mentors": active_mentors,
                "sessions_done": sessions_done,
                "upcoming_meetings": upcoming_meetings,
                "rating": 5.0
            }
        })

    @api_bp.route("/mentee/tasks", methods=["GET"])
    def api_get_mentee_tasks():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        tasks = MenteeTask.query.filter_by(mentee_id=user.id).all()
        task_list = []
        for t in tasks:
            task_list.append({
                "id": t.id,
                "status": t.status or "Pending",
                "progress": t.progress or 0,
                "due_date": t.due_date.strftime("%Y-%m-%d") if getattr(t, "due_date", None) else "",
                "purpose_of_call": getattr(t, "purpose", "") or getattr(t, "description", "") or "Mentorship Task"
            })
        return jsonify({"success": True, "tasks": task_list})

    @api_bp.route("/mentee/tasks/<int:task_id>", methods=["PUT", "POST"])
    def api_update_mentee_task(task_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        task = MenteeTask.query.filter_by(id=task_id).first()
        if not task:
            return jsonify({"success": False, "message": "Task not found"}), 404

        data = request.get_json(silent=True) or {}
        if "status" in data:
            task.status = data["status"]
        if "progress" in data:
            task.progress = int(data["progress"])

        try:
            db.session.commit()
            return jsonify({"success": True, "message": "Task updated"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    @api_bp.route("/mentee/mentors", methods=["GET"])
    def api_get_all_mentors():
        """Returns list of registered mentors with cached ratings and profile pictures."""
        mentors = db.session.query(User, MentorProfile).outerjoin(
            MentorProfile, User.id == MentorProfile.user_id
        ).filter(User.user_type == "1").limit(60).all()

        mentor_list = []
        for u, mp in mentors:
            rating = 5.0
            pic = None
            prof = "Expert Mentor"
            org = "Verified Organisation"
            loc = ""

            if mp:
                prof = mp.profession or prof
                org = mp.organisation or org
                loc = mp.location or loc
                pic = mp.profile_picture
                if pic and not pic.startswith("http"):
                    pic = f"/static/uploads/{pic}"
                rating = mp.supervisor_rating or 5.0

            mentor_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "profession": prof,
                "organisation": org,
                "location": loc,
                "supervisor_rating": round(float(rating), 1),
                "profile_picture": pic,
                "status": getattr(mp, "status", "active") if mp else "active"
            })

        return jsonify({"success": True, "mentors": mentor_list})

    @api_bp.route("/mentee/connected_mentors", methods=["GET"])
    def api_get_connected_mentors():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        reqs = MentorshipRequest.query.filter(
            MentorshipRequest.mentee_id == user.id,
            or_(
                MentorshipRequest.final_status == "approved",
                MentorshipRequest.supervisor_status == "approved",
                MentorshipRequest.mentor_status == "accepted"
            )
        ).all()

        connected = []
        seen = set()
        for r in reqs:
            if r.mentor_id in seen:
                continue
            seen.add(r.mentor_id)

            mentor_user = User.query.get(r.mentor_id)
            if not mentor_user:
                continue

            mp = MentorProfile.query.filter_by(user_id=mentor_user.id).first()
            pic = mp.profile_picture if mp else None
            if pic and not pic.startswith("http"):
                pic = f"/static/uploads/{pic}"

            connected.append({
                "id": mentor_user.id,
                "user_id": str(mentor_user.id),
                "name": mentor_user.name,
                "profession": mp.profession if mp else "Mentor",
                "organisation": mp.organisation if mp else "Verified Organisation",
                "location": mp.location if mp else "",
                "supervisor_rating": mp.supervisor_rating if mp and mp.supervisor_rating else 5.0,
                "profile_picture": pic,
                "status": "active"
            })

        return jsonify({"success": True, "mentors": connected})

    # -------------------------------------------------------------
    # 3. MENTOR ENDPOINTS
    # -------------------------------------------------------------
    @api_bp.route("/mentor/profile", methods=["GET"])
    def api_get_mentor_profile():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        mp = MentorProfile.query.filter_by(user_id=user.id).first()
        pic = mp.profile_picture if mp else None
        if pic and not pic.startswith("http"):
            pic = f"/static/uploads/{pic}"

        return jsonify({
            "success": True,
            "profile": {
                "id": user.id,
                "user_id": str(user.id),
                "name": user.name,
                "email": user.email,
                "profession": mp.profession if mp else "Mentor",
                "organisation": mp.organisation if mp else "Organisation",
                "location": mp.location if mp else "",
                "supervisor_rating": mp.supervisor_rating if mp and mp.supervisor_rating else 5.0,
                "profile_picture": pic,
                "status": mp.status if mp else "active"
            }
        })

    @api_bp.route("/mentor/profile", methods=["PUT", "POST"])
    def api_update_mentor_profile():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        name = data.get("name")
        if name:
            user.name = name.strip()

        mp = MentorProfile.query.filter_by(user_id=user.id).first()
        if not mp:
            mp = MentorProfile(user_id=user.id)
            db.session.add(mp)

        if "profession" in data:
            mp.profession = data["profession"]
        if "organisation" in data:
            mp.organisation = data["organisation"]
        if "location" in data:
            mp.location = data["location"]
        if data.get("profile_picture"):
            mp.profile_picture = data["profile_picture"]

        try:
            db.session.commit()
            return jsonify({"success": True, "message": "Mentor profile updated"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    @api_bp.route("/mentor/requests", methods=["GET"])
    def api_get_mentor_requests():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        reqs = MentorshipRequest.query.filter_by(mentor_id=user.id).all()
        result = []
        for r in reqs:
            mentee = User.query.get(r.mentee_id)
            mentee_name = mentee.name if mentee else "Mentee"
            result.append({
                "id": r.id,
                "mentee_id": r.mentee_id,
                "mentee_name": mentee_name,
                "purpose": getattr(r, "purpose", "") or "Mentorship Request",
                "duration_months": getattr(r, "duration_months", 3),
                "mentor_status": getattr(r, "mentor_status", "pending"),
                "supervisor_status": getattr(r, "supervisor_status", "pending"),
                "final_status": getattr(r, "final_status", "pending"),
                "created_at": r.created_at.strftime("%Y-%m-%d") if getattr(r, "created_at", None) else ""
            })
        return jsonify({"success": True, "requests": result})

    @api_bp.route("/mentor/requests/<int:req_id>/action", methods=["POST"])
    def api_mentor_request_action(req_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        req_obj = MentorshipRequest.query.filter_by(id=req_id, mentor_id=user.id).first()
        if not req_obj:
            return jsonify({"success": False, "message": "Request not found"}), 404

        data = request.get_json(silent=True) or {}
        action = data.get("action")  # "accepted" or "rejected"

        if action in ("accepted", "approved"):
            req_obj.mentor_status = "accepted"
            # Auto-approve if supervisor not required or update status
            if getattr(req_obj, "supervisor_status", None) == "approved":
                req_obj.final_status = "approved"
        elif action in ("rejected", "declined"):
            req_obj.mentor_status = "rejected"
            req_obj.final_status = "rejected"

        try:
            db.session.commit()
            return jsonify({"success": True, "message": f"Request {action}"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # -------------------------------------------------------------
    # 4. INSTITUTION & ADMIN STATS
    # -------------------------------------------------------------
    @api_bp.route("/institution/stats", methods=["GET"])
    def api_get_institution_stats():
        user = get_current_user_from_req(User)
        inst_name = user.name if user else "Institution"

        total_mentors = User.query.filter_by(user_type="1").count()
        total_mentees = User.query.filter_by(user_type="2").count()
        active_pairs = MentorshipRequest.query.filter_by(final_status="approved").count()

        return jsonify({
            "success": True,
            "stats": {
                "total_mentors": total_mentors,
                "total_mentees": total_mentees,
                "active_mentorships": active_pairs,
                "institution_name": inst_name
            }
        })

    @api_bp.route("/admin/metrics", methods=["GET"])
    def api_get_admin_metrics():
        total_mentors = User.query.filter_by(user_type="1").count()
        total_mentees = User.query.filter_by(user_type="2").count()
        active_pairs = MentorshipRequest.query.filter_by(final_status="approved").count()
        pending_requests = MentorshipRequest.query.filter_by(supervisor_status="pending").count()

        return jsonify({
            "success": True,
            "metrics": {
                "total_mentors": total_mentors,
                "total_mentees": total_mentees,
                "active_mentorships": active_pairs,
                "pending_requests": pending_requests
            }
        })

    # -------------------------------------------------------------
    # 5. NOTIFICATIONS
    # -------------------------------------------------------------
    @api_bp.route("/notifications", methods=["GET"])
    def api_get_notifications():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": True, "notifications": []})

        notifications = Notification.query.filter_by(user_id=user.id).order_by(
            Notification.created_at.desc()
        ).limit(30).all()

        result = []
        for n in notifications:
            result.append({
                "id": n.id,
                "message": n.message,
                "link": n.link or "",
                "is_read": bool(n.is_read),
                "created_at": n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else ""
            })
        return jsonify({"success": True, "notifications": result})

    app.register_blueprint(api_bp)
    logger.info("Mobile REST API endpoints successfully registered under /api/*")
