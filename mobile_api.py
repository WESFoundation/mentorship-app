"""
Mobile API Blueprint for Mentor Connect Flutter Application.
Provides secure, unified REST endpoints for:
- Authentication, Sessions & Password Reset
- File & Profile Photo Uploads
- Mentee Profile (all 35 fields), Dashboard Stats, Tasks, & Connections
- Mentor Profile (all 38 fields), Requests, Tasks, & Mentees
- Unified Meetings & Scheduling
- Certificate Eligibility
- Institution & Admin Metrics, Network Members, & Requests
- Notifications & Resource Notes
Replaces all direct PostgreSQL client queries in the Flutter app.
"""

from flask import Blueprint, request, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import or_, and_, func
from datetime import datetime
import json
import logging
import storage_service

logger = logging.getLogger(__name__)

api_bp = Blueprint("mobile_api", __name__, url_prefix="/api")


def get_current_user_from_req(User):
    """
    Extract authenticated user from Session, Authorization header (Bearer email/token/user_id),
    or email/user_id query params.
    """
    email = session.get("email")
    if not email:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if "@" in token:
                email = token
            elif token.isdigit():
                return User.query.get(int(token))

    if not email:
        email = request.args.get("email") or (request.is_json and request.json.get("email"))

    if email:
        return User.query.filter(func.lower(User.email) == email.strip().lower()).first()

    # Fallback to user_id parameter if provided
    user_id = request.args.get("user_id") or (request.is_json and request.json.get("user_id"))
    if user_id:
        try:
            return User.query.get(int(user_id))
        except (ValueError, TypeError):
            pass

    return None


def format_pic_url(pic):
    """Normalize stored profile picture path/URL for mobile rendering."""
    if not pic:
        return None
    p = str(pic).strip()
    if not p:
        return None
    if p.startswith("http://") or p.startswith("https://"):
        return p
    if p.startswith("/static/uploads/"):
        return p
    if p.startswith("static/uploads/"):
        return f"/{p}"
    if p.startswith("uploads/"):
        return f"/static/{p}"
    return f"/static/uploads/{p}"


def calc_mentor_rating_helper(mentor_id, mp, MenteeTask, db):
    """Compute 3-factor composite mentor rating (profile + supervisor + tasks)."""
    profile_stars = 3.0
    if mp:
        fields = 0
        if mp.profession and mp.profession.strip(): fields += 1
        if mp.organisation and mp.organisation.strip(): fields += 1
        if mp.location and mp.location.strip(): fields += 1
        profile_stars = (fields / 3.0) * 5.0

    admin_stars = float(mp.supervisor_rating) if mp and getattr(mp, "supervisor_rating", None) is not None else 5.0

    task_stars = 4.5
    try:
        if MenteeTask:
            tasks = MenteeTask.query.filter_by(mentor_id=mentor_id).all()
            if tasks:
                done_cnt = sum(1 for t in tasks if (t.status or "").lower() in ("done", "completed") or (t.progress or 0) >= 100)
                task_stars = (done_cnt / len(tasks)) * 5.0
    except Exception:
        pass

    final_rating = round((profile_stars + admin_stars + task_stars) / 3.0, 1)
    return min(5.0, max(1.0, final_rating))


def calc_mentee_rating_helper(mentee_id, db):
    """Compute average rating given to mentee's tasks by mentors."""
    try:
        TaskRating = db.Model._decl_class_registry.get("TaskRating")
        if TaskRating:
            ratings = TaskRating.query.filter_by(mentee_id=mentee_id).all()
            if ratings:
                avg = sum(r.rating for r in ratings if r.rating) / len(ratings)
                return round(float(avg), 1)
    except Exception:
        pass
    return 5.0


def register_mobile_api(app, db, User, MentorProfile, MenteeProfile, Institution, SupervisorProfile, MenteeTask, MentorshipRequest, MeetingRequest, Notification, calculate_mentor_rating_func=None, PersonalTask=None, MasterTask=None, **kwargs):
    """Register all mobile API endpoints with the Flask app."""
    if PersonalTask is None:
        try:
            PersonalTask = db.Model._decl_class_registry.get("PersonalTask")
        except Exception:
            PersonalTask = None
    if MasterTask is None:
        try:
            MasterTask = db.Model._decl_class_registry.get("MasterTask")
        except Exception:
            MasterTask = None

    # -------------------------------------------------------------
    # 0. UNIVERSAL FILE / PHOTO UPLOAD
    # -------------------------------------------------------------
    @api_bp.route("/upload", methods=["POST"])
    def api_upload_file():
        user = get_current_user_from_req(User)
        file = request.files.get("file") or request.files.get("profile_picture")
        if not file or not file.filename:
            return jsonify({"success": False, "message": "No file provided"}), 400

        user_id = user.id if user else "guest"
        role_str = str(user.user_type if user else "0")
        default_folder = f"profiles/user_{user_id}"
        if role_str == "1":
            default_folder = f"mentors/{user_id}"
        elif role_str == "2":
            default_folder = f"mentees/{user_id}"
        elif role_str == "3":
            default_folder = f"institutions/{user_id}"

        folder = request.form.get("folder") or request.form.get("folder_prefix") or default_folder
        file_url, stored_name = storage_service.upload_file(file, folder_prefix=folder)
        if not file_url:
            return jsonify({"success": False, "message": "Upload failed"}), 500

        res_url = format_pic_url(file_url if file_url.startswith("http") else stored_name)
        return jsonify({
            "success": True,
            "url": res_url,
            "filename": stored_name
        })

    # -------------------------------------------------------------
    # 1. AUTHENTICATION & LOGIN / REGISTER / RESET
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

        if user.password:
            valid = False
            try:
                valid = check_password_hash(user.password, password)
            except Exception:
                valid = (user.password == password)

            if not valid and password != user.password:
                return jsonify({"success": False, "message": "Invalid password"}), 401

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
            "token": user.email,
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

    @api_bp.route("/auth/reset_password", methods=["POST"])
    def api_reset_password():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        if not email:
            return jsonify({"success": False, "message": "Email is required"}), 400
        user = User.query.filter(func.lower(User.email) == email).first()
        if not user:
            return jsonify({"success": True, "message": "If account exists, reset instructions have been sent."})

        new_password = data.get("password")
        if new_password:
            user.password = generate_password_hash(new_password, method="pbkdf2:sha256", salt_length=8)
            db.session.commit()
            return jsonify({"success": True, "message": "Password updated successfully"})

        return jsonify({"success": True, "message": "Reset code sent to your registered email"})

    # -------------------------------------------------------------
    # 2. MENTEE ENDPOINTS (ALL 35 FIELDS + STATS + CERTIFICATE)
    # -------------------------------------------------------------
    @api_bp.route("/mentee/profile", methods=["GET"])
    def api_get_mentee_profile():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        profile = MenteeProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            return jsonify({
                "success": True,
                "profile": {
                    "id": user.id,
                    "user_id": str(user.id),
                    "numeric_user_id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "who_am_i": "student",
                    "status": "active"
                }
            })

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
                "board_university": profile.board_university or "",
                "course_stream": profile.course_stream or profile.stream or "",
                "school_board": profile.school_board or "",
                "school_passing_year": profile.school_passing_year or "",
                "career_interest": profile.career_interest or "",
                "current_role": profile.current_role or "",
                "industry": profile.industry or "",
                "years_experience": profile.years_experience or "",
                "current_organization": profile.current_organization or "",
                "key_skills": profile.key_skills or "",
                "career_goal": profile.career_goal or profile.goal or "",
                "goal": profile.goal or profile.career_goal or "",
                "startup_stage": profile.startup_stage or "",
                "startup_name": profile.startup_name or "",
                "startup_industry": profile.startup_industry or "",
                "team_size": profile.team_size or "",
                "main_challenge": profile.main_challenge or "",
                "mentorship_type": profile.mentorship_type or "",
                "freelance_skill": profile.freelance_skill or "",
                "freelance_experience": profile.freelance_experience or "",
                "freelance_platforms": profile.freelance_platforms or "",
                "freelance_challenge": profile.freelance_challenge or "",
                "last_role": profile.last_role or "",
                "career_break_reason": profile.career_break_reason or "",
                "restart_field": profile.restart_field or "",
                "support_expected": profile.support_expected or "",
                "dob": profile.dob or "",
                "father_name": profile.father_name or "",
                "address_line1": profile.address_line1 or "",
                "address_line2": profile.address_line2 or "",
                "city": profile.city or "",
                "state": profile.state or "",
                "postal_code": profile.postal_code or "",
                "country": profile.country or "",
                "mobile_number": profile.mobile_number or "",
                "mobile_country_code": profile.mobile_country_code or "+1",
                "whatsapp_number": profile.whatsapp_number or "",
                "whatsapp_country_code": profile.whatsapp_country_code or "+1",
                "stream": profile.stream or profile.course_stream or "",
                "class_year": profile.class_year or "",
                "favourite_subject": profile.favourite_subject or "",
                "parent_name": profile.parent_name or "",
                "parent_mobile": profile.parent_mobile or "",
                "parent_mobile_country_code": profile.parent_mobile_country_code or "+1",
                "parent_email": profile.parent_email or "",
                "parent_consent_status": profile.parent_consent_status or "pending",
                "mentorship_expectations": profile.mentorship_expectations or "",
                "linkedin_link": profile.linkedin_link or "",
                "terms_agreement": profile.terms_agreement or "",
                "profile_picture": format_pic_url(profile.profile_picture),
                "status": profile.status or "active"
            }
        })

    @api_bp.route("/mentee/profile", methods=["PUT", "POST"])
    def api_update_mentee_profile():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        if data.get("name"):
            user.name = data["name"].strip()

        profile = MenteeProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            profile = MenteeProfile(user_id=user.id)
            db.session.add(profile)

        # Update all supported fields
        direct_fields = [
            "who_am_i", "education_level", "institution_name", "board_university",
            "course_stream", "school_name", "school_board", "school_passing_year",
            "career_interest", "current_role", "industry", "years_experience",
            "current_organization", "key_skills", "startup_stage", "startup_name",
            "startup_industry", "team_size", "main_challenge", "mentorship_type",
            "freelance_skill", "freelance_experience", "freelance_platforms",
            "freelance_challenge", "last_role", "career_break_reason", "restart_field",
            "support_expected", "dob", "father_name", "address_line1", "address_line2",
            "city", "state", "postal_code", "country", "mobile_number",
            "mobile_country_code", "whatsapp_number", "whatsapp_country_code",
            "stream", "class_year", "favourite_subject", "parent_name", "parent_mobile",
            "parent_mobile_country_code", "parent_email", "mentorship_expectations",
            "linkedin_link", "terms_agreement"
        ]

        for field in direct_fields:
            if field in data:
                setattr(profile, field, data[field])

        # Aliases
        goal_val = data.get("career_goal") or data.get("goal")
        if goal_val is not None:
            profile.career_goal = goal_val
            profile.goal = goal_val

        inst_val = data.get("school_name") or data.get("institution_name") or data.get("school_college_name")
        if inst_val is not None:
            profile.institution_name = inst_val
            profile.school_college_name = inst_val

        pic_val = data.get("profile_picture")
        if pic_val is not None:
            profile.profile_picture = pic_val

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

        active_mentors = MentorshipRequest.query.filter(
            MentorshipRequest.mentee_id == user.id,
            or_(
                MentorshipRequest.final_status == "approved",
                MentorshipRequest.supervisor_status == "approved",
                MentorshipRequest.mentor_status == "accepted"
            )
        ).count()

        sessions_done = MeetingRequest.query.filter(
            or_(MeetingRequest.requester_id == user.id, MeetingRequest.requested_to_id == user.id),
            MeetingRequest.status == "completed"
        ).count()

        upcoming_meetings = MeetingRequest.query.filter(
            or_(MeetingRequest.requester_id == user.id, MeetingRequest.requested_to_id == user.id),
            ~MeetingRequest.status.in_(["completed", "rejected"])
        ).count()

        real_rating = calc_mentee_rating_helper(user.id, db)

        return jsonify({
            "success": True,
            "stats": {
                "active_mentors": active_mentors,
                "sessions_done": sessions_done,
                "upcoming_meetings": upcoming_meetings,
                "rating": real_rating
            }
        })

    @api_bp.route("/mentee/certificate_eligibility", methods=["GET"])
    def api_mentee_certificate_eligibility():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        completed_tasks = MenteeTask.query.filter(
            MenteeTask.mentee_id == user.id,
            or_(MenteeTask.status == "Done", MenteeTask.status == "completed", MenteeTask.progress >= 100)
        ).count()

        is_scholarly = getattr(user, "scholarly", False) == True
        is_corporate = getattr(user, "is_corporate", False) == True
        is_eligible = completed_tasks >= 5 or is_scholarly or is_corporate

        return jsonify({
            "success": True,
            "eligibility": {
                "isEligible": is_eligible,
                "completedTasks": completed_tasks,
                "requiredTasks": 5,
                "isScholarly": is_scholarly,
                "isCorporate": is_corporate
            }
        })

    @api_bp.route("/mentee/mentors", methods=["GET"])
    def api_get_all_mentors():
        """Returns list of registered mentors with formatted photos and computed ratings."""
        mentors = db.session.query(User, MentorProfile).outerjoin(
            MentorProfile, User.id == MentorProfile.user_id
        ).filter(User.user_type == "1").limit(60).all()

        mentor_list = []
        for u, mp in mentors:
            prof = mp.profession if mp and mp.profession else "Expert Mentor"
            org = mp.organisation if mp and mp.organisation else "Verified Organisation"
            loc = mp.location if mp and mp.location else ""
            pic = format_pic_url(mp.profile_picture if mp else None)
            comp_rating = calc_mentor_rating_helper(u.id, mp, MenteeTask, db)

            mentor_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "profession": prof,
                "organisation": org,
                "location": loc,
                "supervisor_rating": comp_rating,
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
            pic = format_pic_url(mp.profile_picture if mp else None)
            comp_rating = calc_mentor_rating_helper(mentor_user.id, mp, MenteeTask, db)

            connected.append({
                "id": mentor_user.id,
                "user_id": str(mentor_user.id),
                "name": mentor_user.name,
                "profession": mp.profession if mp and mp.profession else "Mentor",
                "organisation": mp.organisation if mp and mp.organisation else "Verified Organisation",
                "location": mp.location if mp and mp.location else "",
                "supervisor_rating": comp_rating,
                "profile_picture": pic,
                "status": "active"
            })

        return jsonify({"success": True, "mentors": connected})

    # -------------------------------------------------------------
    # 3. MENTOR ENDPOINTS (ALL 38 FIELDS + MENTEES + TASKS)
    # -------------------------------------------------------------
    @api_bp.route("/mentor/profile", methods=["GET"])
    def api_get_mentor_profile():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        mp = MentorProfile.query.filter_by(user_id=user.id).first()
        comp_rating = calc_mentor_rating_helper(user.id, mp, MenteeTask, db)

        return jsonify({
            "success": True,
            "profile": {
                "id": user.id,
                "user_id": str(user.id),
                "name": user.name,
                "email": user.email,
                "profession": mp.profession if mp else "Mentor",
                "organisation": mp.organisation if mp else "Organisation",
                "years_of_experience": mp.years_of_experience if mp else "",
                "whatsapp": mp.whatsapp if mp else "",
                "location": mp.location if mp else "",
                "education": mp.education if mp else "",
                "language": mp.language if mp else "",
                "highest_qualification": mp.highest_qualification if mp else "",
                "degree_name": mp.degree_name if mp else "",
                "field_of_study": mp.field_of_study if mp else "",
                "university_name": mp.university_name if mp else "",
                "graduation_year": mp.graduation_year if mp else "",
                "academic_status": mp.academic_status if mp else "",
                "certifications": mp.certifications if mp else "",
                "research_work": mp.research_work if mp else "",
                "linkedin_link": mp.linkedin_link if mp else "",
                "github_link": mp.github_link if mp else "",
                "portfolio_link": mp.portfolio_link if mp else "",
                "other_social_link": mp.other_social_link if mp else "",
                "target_audience": mp.target_audience if mp else "",
                "base_mentorship_topics": mp.base_mentorship_topics if mp else "",
                "mentorship_topics": mp.mentorship_topics if mp else "",
                "mentorship_type_preference": mp.mentorship_type_preference if mp else "",
                "preferred_communication": mp.preferred_communication if mp else "",
                "availability": mp.availability if mp else "",
                "connect_frequency": mp.connect_frequency if mp else "",
                "preferred_duration": mp.preferred_duration if mp else "",
                "why_mentor": mp.why_mentor if mp else "",
                "mentorship_philosophy": mp.mentorship_philosophy if mp else "",
                "mentorship_motto": mp.mentorship_motto if mp else "",
                "additional_info": mp.additional_info if mp else "",
                "profile_picture": format_pic_url(mp.profile_picture if mp else None),
                "criminal_certificate": format_pic_url(mp.criminal_certificate if mp else None),
                "supervisor_rating": comp_rating,
                "status": mp.status if mp else "active"
            }
        })

    @api_bp.route("/mentor/profile", methods=["PUT", "POST"])
    def api_update_mentor_profile():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        if data.get("name"):
            user.name = data["name"].strip()

        mp = MentorProfile.query.filter_by(user_id=user.id).first()
        if not mp:
            mp = MentorProfile(user_id=user.id)
            db.session.add(mp)

        direct_fields = [
            "profession", "organisation", "years_of_experience", "whatsapp",
            "location", "education", "language", "highest_qualification",
            "degree_name", "field_of_study", "university_name", "graduation_year",
            "academic_status", "certifications", "research_work", "linkedin_link",
            "github_link", "portfolio_link", "other_social_link", "target_audience",
            "base_mentorship_topics", "mentorship_topics", "mentorship_type_preference",
            "preferred_communication", "availability", "connect_frequency",
            "preferred_duration", "why_mentor", "mentorship_philosophy",
            "mentorship_motto", "additional_info", "profile_picture", "criminal_certificate"
        ]

        for field in direct_fields:
            if field in data:
                setattr(mp, field, data[field])

        try:
            db.session.commit()
            return jsonify({"success": True, "message": "Mentor profile updated"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    @api_bp.route("/mentor/mentees", methods=["GET"])
    def api_get_connected_mentees():
        """Returns ONLY approved mentees connected to this mentor."""
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        reqs = MentorshipRequest.query.filter(
            MentorshipRequest.mentor_id == user.id,
            or_(
                MentorshipRequest.final_status == "approved",
                MentorshipRequest.supervisor_status == "approved",
                MentorshipRequest.mentor_status == "accepted"
            )
        ).all()

        connected = []
        seen = set()
        for r in reqs:
            if r.mentee_id in seen:
                continue
            seen.add(r.mentee_id)

            mentee_u = User.query.get(r.mentee_id)
            if not mentee_u:
                continue

            mp = MenteeProfile.query.filter_by(user_id=mentee_u.id).first()
            pic = format_pic_url(mp.profile_picture if mp else None)
            goal = mp.career_goal or mp.goal or "Career Development" if mp else "Mentee"
            inst = mp.institution_name or mp.school_college_name or "Student" if mp else "Student"

            connected.append({
                "id": mentee_u.id,
                "user_id": str(mentee_u.id),
                "name": mentee_u.name,
                "career_goal": goal,
                "goal": goal,
                "institution_name": inst,
                "profile_picture": pic,
                "status": "active"
            })

        return jsonify({"success": True, "mentees": connected})

    @api_bp.route("/mentor/all_mentees", methods=["GET"])
    def api_get_all_mentees():
        """Returns all registered mentees for Find Mentees directory."""
        mentees = db.session.query(User, MenteeProfile).outerjoin(
            MenteeProfile, User.id == MenteeProfile.user_id
        ).filter(User.user_type == "2").limit(60).all()

        result = []
        for u, mp in mentees:
            pic = format_pic_url(mp.profile_picture if mp else None)
            goal = mp.career_goal or mp.goal or "Career Guidance" if mp else "Mentee"
            inst = mp.institution_name or mp.school_college_name or "Student" if mp else "Student"

            result.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "career_goal": goal,
                "goal": goal,
                "institution_name": inst,
                "profile_picture": pic,
                "status": getattr(mp, "status", "active") if mp else "active"
            })

        return jsonify({"success": True, "mentees": result})

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
            mp = MenteeProfile.query.filter_by(user_id=r.mentee_id).first()
            result.append({
                "id": r.id,
                "mentee_id": r.mentee_id,
                "mentee_name": mentee_name,
                "profile_picture": format_pic_url(mp.profile_picture if mp else None),
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
        action = data.get("action")

        if action in ("accepted", "approved"):
            req_obj.mentor_status = "accepted"
            if getattr(req_obj, "supervisor_status", None) == "approved":
                req_obj.final_status = "approved"
                try:
                    from anchor_tasks_checker import check_and_fix_anchor_tasks
                    check_and_fix_anchor_tasks(mentorship_id=req_obj.id, mentee_id=req_obj.mentee_id, auto_commit=False)
                except Exception as e:
                    logger.warning("Error checking anchor tasks upon mentor acceptance: %s", e)
        elif action in ("rejected", "declined"):
            req_obj.mentor_status = "rejected"
            req_obj.final_status = "rejected"

        try:
            db.session.commit()
            return jsonify({"success": True, "message": f"Request {action}"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    @api_bp.route("/mentor/tasks", methods=["GET"])
    def api_get_mentor_tasks():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        tasks = MenteeTask.query.filter_by(mentor_id=user.id).order_by(MenteeTask.meeting_number).all()
        task_list = []
        for t in tasks:
            status_str = (t.status or "pending").strip().lower()
            if status_str in ("done", "completed") or (t.progress or 0) >= 100:
                display_status = "Done"
            elif status_str in ("in-progress", "in_progress", "committed"):
                display_status = "In Progress"
            else:
                display_status = "Pending"

            mt = getattr(t, "master_task", None)
            title_val = (mt.journey_phase if mt and mt.journey_phase else (mt.mentee_focus if mt and mt.mentee_focus else f"Curriculum Task #{t.meeting_number}"))
            desc_val = (mt.purpose_of_call if mt and mt.purpose_of_call else (mt.mentee_focus if mt and mt.mentee_focus else "Curriculum Task"))

            task_list.append({
                "id": t.id,
                "serial": t.meeting_number,
                "title": title_val,
                "purpose_of_call": desc_val,
                "description": desc_val,
                "status": display_status,
                "raw_status": t.status or "pending",
                "progress": t.progress or (100 if display_status == "Done" else 0),
                "due_date": t.due_date.strftime("%Y-%m-%d") if getattr(t, "due_date", None) else "",
                "type": "Curriculum Task",
                "task_type": "master",
                "mentee_id": t.mentee_id,
                "mentee_name": t.mentee.name if getattr(t, "mentee", None) else f"Mentee #{t.mentee_id}",
                "month": t.month or (mt.month if mt else "")
            })

        if PersonalTask:
            p_tasks = PersonalTask.query.filter_by(mentor_id=user.id).order_by(PersonalTask.created_date.desc()).all()
            for pt in p_tasks:
                status_str = (pt.status or "pending").strip().lower()
                if status_str in ("done", "completed") or (pt.progress or 0) >= 100:
                    display_status = "Done"
                elif status_str in ("in-progress", "in_progress"):
                    display_status = "In Progress"
                else:
                    display_status = "Pending"

                task_list.append({
                    "id": pt.id,
                    "serial": len(task_list) + 1,
                    "title": pt.title or "Personal Task",
                    "purpose_of_call": pt.description or "Personal Task",
                    "description": pt.description or "",
                    "status": display_status,
                    "raw_status": pt.status or "pending",
                    "progress": pt.progress or (100 if display_status == "Done" else 0),
                    "due_date": pt.due_date.strftime("%Y-%m-%d") if getattr(pt, "due_date", None) else "",
                    "type": "Personal Task",
                    "task_type": "personal",
                    "mentee_id": pt.mentee_id,
                    "mentee_name": pt.mentee.name if getattr(pt, "mentee", None) else f"Mentee #{pt.mentee_id}",
                    "month": "Ongoing"
                })

        return jsonify({"success": True, "tasks": task_list})

    # -------------------------------------------------------------
    # 4. MEETINGS & CALENDAR ENDPOINTS
    # -------------------------------------------------------------
    @api_bp.route("/meetings", methods=["GET"])
    def api_get_meetings():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        meetings = MeetingRequest.query.filter(
            or_(MeetingRequest.requester_id == user.id, MeetingRequest.requested_to_id == user.id)
        ).order_by(MeetingRequest.meeting_date.desc(), MeetingRequest.meeting_time.desc()).all()

        result = []
        for m in meetings:
            other_id = m.requested_to_id if m.requester_id == user.id else m.requester_id
            other_user = User.query.get(other_id)
            other_name = other_user.name if other_user else f"User #{other_id}"

            result.append({
                "id": m.id,
                "requester_id": m.requester_id,
                "requested_to_id": m.requested_to_id,
                "title": m.meeting_title,
                "meeting_title": m.meeting_title,
                "description": m.meeting_description or "",
                "meeting_description": m.meeting_description or "",
                "date": m.meeting_date.strftime("%Y-%m-%d") if m.meeting_date else "",
                "meeting_date": m.meeting_date.strftime("%Y-%m-%d") if m.meeting_date else "",
                "time": m.meeting_time.strftime("%I:%M %p") if m.meeting_time else "",
                "meeting_time": m.meeting_time.strftime("%I:%M %p") if m.meeting_time else "",
                "status": m.status or "pending",
                "other_party_name": other_name,
                "meet_link": m.meet_link or ""
            })

        return jsonify({"success": True, "meetings": result})

    @api_bp.route("/meetings", methods=["POST"])
    def api_create_meeting():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        requested_to_id = data.get("requested_to_id")
        title = data.get("title") or data.get("meeting_title") or "Mentorship Session"
        desc = data.get("description") or data.get("meeting_description") or ""
        date_str = data.get("date") or data.get("meeting_date")
        time_str = data.get("time") or data.get("meeting_time") or "10:00:00"

        if not requested_to_id or not date_str:
            return jsonify({"success": False, "message": "Participant and Date are required"}), 400

        try:
            m_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except Exception:
            m_date = datetime.utcnow().date()

        try:
            # Parse time flexibly (e.g. "10:00 AM" or "10:00:00")
            clean_time = time_str.strip()
            if "AM" in clean_time.upper() or "PM" in clean_time.upper():
                m_time = datetime.strptime(clean_time, "%I:%M %p").time()
            else:
                m_time = datetime.strptime(clean_time[:8], "%H:%M:%S" if len(clean_time) >= 8 else "%H:%M").time()
        except Exception:
            m_time = datetime.strptime("10:00", "%H:%M").time()

        new_meeting = MeetingRequest(
            requester_id=user.id,
            requested_to_id=int(requested_to_id),
            meeting_title=title,
            meeting_description=desc,
            meeting_date=m_date,
            meeting_time=m_time,
            status="pending"
        )
        db.session.add(new_meeting)
        db.session.commit()

        return jsonify({"success": True, "message": "Meeting scheduled successfully", "id": new_meeting.id}), 201

    # -------------------------------------------------------------
    # 5. TASKS ENDPOINTS (MENTEE CURRICULUM + PERSONAL)
    # -------------------------------------------------------------
    @api_bp.route("/mentee/tasks", methods=["GET"])
    @api_bp.route("/tasks", methods=["GET"])
    def api_get_mentee_tasks():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        try:
            from anchor_tasks_checker import check_and_fix_anchor_tasks
            check_and_fix_anchor_tasks(mentee_id=user.id, auto_commit=True)
        except Exception as e:
            logger.warning("Error checking anchor tasks for mentee %s: %s", user.id, e)

        tasks = MenteeTask.query.filter_by(mentee_id=user.id).order_by(MenteeTask.meeting_number).all()
        task_list = []
        for t in tasks:
            status_str = (t.status or "pending").strip().lower()
            if status_str in ("done", "completed") or (t.progress or 0) >= 100:
                display_status = "Done"
            elif status_str in ("in-progress", "in_progress", "committed"):
                display_status = "In Progress"
            else:
                display_status = "Pending"

            mt = getattr(t, "master_task", None)
            title_val = (mt.journey_phase if mt and mt.journey_phase else (mt.mentee_focus if mt and mt.mentee_focus else f"Curriculum Task #{t.meeting_number}"))
            desc_val = (mt.purpose_of_call if mt and mt.purpose_of_call else (mt.mentee_focus if mt and mt.mentee_focus else "Mentorship Curriculum Assignment"))

            task_list.append({
                "id": t.id,
                "serial": t.meeting_number,
                "title": title_val,
                "purpose_of_call": desc_val,
                "description": desc_val,
                "mentee_focus": mt.mentee_focus if mt else "",
                "status": display_status,
                "raw_status": t.status or "pending",
                "progress": t.progress or (100 if display_status == "Done" else 0),
                "due_date": t.due_date.strftime("%Y-%m-%d") if getattr(t, "due_date", None) else "",
                "type": "Curriculum Task",
                "task_type": "master",
                "mentor_name": t.mentor.name if getattr(t, "mentor", None) else "Assigned Mentor",
                "mentor_id": t.mentor_id,
                "month": t.month or (mt.month if mt else "")
            })

        if PersonalTask:
            p_tasks = PersonalTask.query.filter_by(mentee_id=user.id).order_by(PersonalTask.created_date.desc()).all()
            for pt in p_tasks:
                status_str = (pt.status or "pending").strip().lower()
                if status_str in ("done", "completed") or (pt.progress or 0) >= 100:
                    display_status = "Done"
                elif status_str in ("in-progress", "in_progress"):
                    display_status = "In Progress"
                else:
                    display_status = "Pending"

                task_list.append({
                    "id": pt.id,
                    "serial": len(task_list) + 1,
                    "title": pt.title or "Personal Task",
                    "purpose_of_call": pt.description or "Personal Assignment",
                    "description": pt.description or "",
                    "mentee_focus": "",
                    "status": display_status,
                    "raw_status": pt.status or "pending",
                    "progress": pt.progress or (100 if display_status == "Done" else 0),
                    "due_date": pt.due_date.strftime("%Y-%m-%d") if getattr(pt, "due_date", None) else "",
                    "type": "Personal Task",
                    "task_type": "personal",
                    "mentor_name": pt.mentor.name if getattr(pt, "mentor", None) else "Self",
                    "mentor_id": pt.mentor_id,
                    "month": "Ongoing"
                })

        return jsonify({"success": True, "tasks": task_list})

    @api_bp.route("/mentee/tasks/<int:task_id>", methods=["PUT", "POST"])
    @api_bp.route("/tasks/<int:task_id>", methods=["PUT", "POST"])
    def api_update_mentee_task(task_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        task = MenteeTask.query.filter_by(id=task_id).first()
        is_personal = False
        if not task and PersonalTask:
            task = PersonalTask.query.filter_by(id=task_id).first()
            is_personal = True

        if not task:
            return jsonify({"success": False, "message": "Task not found"}), 404

        data = request.get_json(silent=True) or {}
        raw_status = (data.get("status") or "").strip()
        progress = data.get("progress")

        if raw_status:
            norm_status = raw_status.lower()
            if norm_status in ("done", "completed"):
                task.status = "done" if not is_personal else "completed"
                if hasattr(task, "completed_date"):
                    task.completed_date = datetime.utcnow()
            elif norm_status in ("in progress", "in-progress"):
                task.status = "in-progress"
            else:
                task.status = "pending"

        if progress is not None:
            task.progress = int(progress)
            if task.progress >= 100 and task.status not in ("done", "completed"):
                task.status = "done" if not is_personal else "completed"
                if hasattr(task, "completed_date"):
                    task.completed_date = datetime.utcnow()

        try:
            db.session.commit()
            return jsonify({"success": True, "message": "Task updated"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # -------------------------------------------------------------
    # 6. INSTITUTION & ADMIN MODULES
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

    @api_bp.route("/institution/members", methods=["GET"])
    def api_get_institution_members():
        """Returns all mentors and mentees under institution."""
        mentors = db.session.query(User, MentorProfile).outerjoin(
            MentorProfile, User.id == MentorProfile.user_id
        ).filter(User.user_type == "1").all()

        mentees = db.session.query(User, MenteeProfile).outerjoin(
            MenteeProfile, User.id == MenteeProfile.user_id
        ).filter(User.user_type == "2").all()

        m_list = []
        for u, mp in mentors:
            m_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "profession": mp.profession if mp and mp.profession else "Mentor",
                "organisation": mp.organisation if mp and mp.organisation else "Organisation",
                "profile_picture": format_pic_url(mp.profile_picture if mp else None),
                "role": "Mentor"
            })

        me_list = []
        for u, mp in mentees:
            me_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "institution_name": mp.institution_name if mp and mp.institution_name else "Student",
                "career_goal": mp.career_goal or mp.goal if mp else "Career Guidance",
                "profile_picture": format_pic_url(mp.profile_picture if mp else None),
                "role": "Mentee"
            })

        return jsonify({"success": True, "mentors": m_list, "mentees": me_list})

    @api_bp.route("/institution/meetings", methods=["GET"])
    def api_get_institution_meetings():
        meetings = MeetingRequest.query.order_by(MeetingRequest.meeting_date.desc()).limit(50).all()
        result = []
        for m in meetings:
            req_u = User.query.get(m.requester_id)
            tar_u = User.query.get(m.requested_to_id)
            result.append({
                "id": m.id,
                "title": m.meeting_title,
                "date": m.meeting_date.strftime("%Y-%m-%d") if m.meeting_date else "",
                "time": m.meeting_time.strftime("%I:%M %p") if m.meeting_time else "",
                "status": m.status or "scheduled",
                "other_party_name": f"{req_u.name if req_u else 'User'} & {tar_u.name if tar_u else 'User'}"
            })
        return jsonify({"success": True, "meetings": result})

    @api_bp.route("/institution/requests", methods=["GET"])
    def api_get_institution_requests():
        reqs = MentorshipRequest.query.order_by(MentorshipRequest.created_at.desc()).limit(50).all()
        result = []
        for r in reqs:
            me = User.query.get(r.mentee_id)
            mo = User.query.get(r.mentor_id)
            result.append({
                "id": r.id,
                "mentee_id": r.mentee_id,
                "mentee_name": me.name if me else f"Mentee #{r.mentee_id}",
                "mentor_id": r.mentor_id,
                "mentor_name": mo.name if mo else f"Mentor #{r.mentor_id}",
                "final_status": r.final_status or "pending",
                "created_at": r.created_at.strftime("%Y-%m-%d") if r.created_at else ""
            })
        return jsonify({"success": True, "requests": result})

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

    @api_bp.route("/admin/users", methods=["GET"])
    def api_get_admin_users():
        mentors = db.session.query(User, MentorProfile).outerjoin(
            MentorProfile, User.id == MentorProfile.user_id
        ).filter(User.user_type == "1").all()

        mentees = db.session.query(User, MenteeProfile).outerjoin(
            MenteeProfile, User.id == MenteeProfile.user_id
        ).filter(User.user_type == "2").all()

        m_list = []
        for u, mp in mentors:
            m_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "email": u.email,
                "profession": mp.profession if mp and mp.profession else "Mentor",
                "organisation": mp.organisation if mp and mp.organisation else "Organisation",
                "profile_picture": format_pic_url(mp.profile_picture if mp else None),
                "role": "Mentor"
            })

        me_list = []
        for u, mp in mentees:
            me_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "email": u.email,
                "institution_name": mp.institution_name if mp and mp.institution_name else "Student",
                "profile_picture": format_pic_url(mp.profile_picture if mp else None),
                "role": "Mentee"
            })

        return jsonify({"success": True, "mentors": m_list, "mentees": me_list})

    @api_bp.route("/admin/requests", methods=["GET"])
    def api_get_admin_requests():
        reqs = MentorshipRequest.query.order_by(MentorshipRequest.created_at.desc()).limit(50).all()
        result = []
        for r in reqs:
            me = User.query.get(r.mentee_id)
            mo = User.query.get(r.mentor_id)
            result.append({
                "id": r.id,
                "mentee_id": r.mentee_id,
                "mentee_name": me.name if me else f"Mentee #{r.mentee_id}",
                "mentor_id": r.mentor_id,
                "mentor_name": mo.name if mo else f"Mentor #{r.mentor_id}",
                "final_status": r.final_status or "pending",
                "created_at": r.created_at.strftime("%Y-%m-%d") if r.created_at else ""
            })
        return jsonify({"success": True, "requests": result})

    @api_bp.route("/admin/requests/<int:req_id>/action", methods=["POST"])
    def api_admin_request_action(req_id):
        user = get_current_user_from_req(User)
        req_obj = MentorshipRequest.query.get(req_id)
        if not req_obj:
            return jsonify({"success": False, "message": "Request not found"}), 404

        data = request.get_json(silent=True) or {}
        action = data.get("action")  # "approved" or "rejected"
        if action in ("approved", "accepted"):
            req_obj.supervisor_status = "approved"
            req_obj.final_status = "approved"
            try:
                from anchor_tasks_checker import check_and_fix_anchor_tasks
                check_and_fix_anchor_tasks(mentorship_id=req_obj.id, mentee_id=req_obj.mentee_id, auto_commit=False)
            except Exception as e:
                logger.warning("Error checking anchor tasks: %s", e)
        else:
            req_obj.supervisor_status = "rejected"
            req_obj.final_status = "rejected"

        db.session.commit()
        return jsonify({"success": True, "message": f"Request {action} successfully"})

    # -------------------------------------------------------------
    # 7. NOTIFICATIONS & RESOURCE NOTES
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

    @api_bp.route("/resources", methods=["GET"])
    def api_get_resources():
        """Returns standard mentor and mentee guidebook notes."""
        return jsonify({
            "success": True,
            "notes": [
                {
                    "id": 1,
                    "title": "Mentorship Handbook 2026",
                    "content": "Comprehensive guidelines for setting goals, scheduling curriculum tasks, and meeting etiquette.",
                    "created_at": "2026-09-01"
                },
                {
                    "id": 2,
                    "title": "Goal Setting & Action Plan Template",
                    "content": "SMART framework guide for mentees to define academic and professional quarterly targets.",
                    "created_at": "2026-09-10"
                },
                {
                    "id": 3,
                    "title": "Luxembourg Career Navigation Guide",
                    "content": "Industry sectors, internship opportunities, and corporate networking best practices.",
                    "created_at": "2026-09-15"
                }
            ]
        })

    app.register_blueprint(api_bp)
    logger.info("Mobile REST API endpoints successfully registered under /api/*")
