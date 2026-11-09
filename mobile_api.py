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

from flask import Blueprint, request, jsonify, session, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import or_, and_, func
from datetime import datetime, timedelta, time as dtime
import time
import json
import logging
import os
import secrets
import io
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
        email = (
            request.args.get("email")
            or request.args.get("mentee_email")
            or (request.is_json and (request.json.get("email") or request.json.get("mentee_email")))
        )

    if email:
        return User.query.filter(func.lower(User.email) == str(email).strip().lower()).first()

    # Fallback to user_id, mentor_id, or mentee_id parameter if provided
    user_id = (
        request.args.get("user_id")
        or request.args.get("mentor_id")
        or request.args.get("mentee_id")
        or (
            request.is_json
            and (
                request.json.get("user_id")
                or request.json.get("mentor_id")
                or request.json.get("mentee_id")
            )
        )
    )
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
    if p.startswith("/static/"):
        return p
    if p.startswith("static/"):
        return f"/{p}"
    if p.startswith("uploads/"):
        return f"/static/{p}"
    if p.startswith("/"):
        return p
    return f"/static/uploads/{p}"


def resolve_profile_pic(profile_obj, user_obj=None):
    """Resolve picture preferring profile_picture/logo on profile, falling back to user's picture."""
    pic = None
    if profile_obj and getattr(profile_obj, "profile_picture", None):
        pic = profile_obj.profile_picture
    if not pic and profile_obj and getattr(profile_obj, "logo", None):
        pic = profile_obj.logo
    if not pic and user_obj and getattr(user_obj, "profile_picture_url", None):
        pic = user_obj.profile_picture_url
    if not pic and user_obj and getattr(user_obj, "profile_picture", None):
        pic = user_obj.profile_picture
    return format_pic_url(pic)


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

    TaskRating = kwargs.get("TaskRating")
    if TaskRating is None:
        try:
            TaskRating = db.Model._decl_class_registry.get("TaskRating")
        except Exception:
            TaskRating = None

    MenteeFeedback = kwargs.get("MenteeFeedback")
    if MenteeFeedback is None:
        try:
            MenteeFeedback = db.Model._decl_class_registry.get("MenteeFeedback")
        except Exception:
            MenteeFeedback = None

    MentorReflection = kwargs.get("MentorReflection")
    if MentorReflection is None:
        try:
            MentorReflection = db.Model._decl_class_registry.get("MentorReflection")
        except Exception:
            MentorReflection = None

    SellerProfile = kwargs.get("SellerProfile")
    if SellerProfile is None:
        try:
            SellerProfile = db.Model._decl_class_registry.get("SellerProfile")
        except Exception:
            SellerProfile = None

    MentorCoupon = kwargs.get("MentorCoupon")
    if MentorCoupon is None:
        try:
            MentorCoupon = db.Model._decl_class_registry.get("MentorCoupon")
        except Exception:
            MentorCoupon = None

    CouponAssignment = kwargs.get("CouponAssignment")
    if CouponAssignment is None:
        try:
            CouponAssignment = db.Model._decl_class_registry.get("CouponAssignment")
        except Exception:
            CouponAssignment = None

    CouponRequest = kwargs.get("CouponRequest")
    if CouponRequest is None:
        try:
            CouponRequest = db.Model._decl_class_registry.get("CouponRequest")
        except Exception:
            CouponRequest = None

    SellerShop = kwargs.get("SellerShop")
    if SellerShop is None:
        try:
            SellerShop = db.Model._decl_class_registry.get("SellerShop")
        except Exception:
            SellerShop = None

    SellerReferral = kwargs.get("SellerReferral")
    if SellerReferral is None:
        try:
            SellerReferral = db.Model._decl_class_registry.get("SellerReferral")
        except Exception:
            SellerReferral = None

    ChatConversation = kwargs.get("ChatConversation")
    if ChatConversation is None:
        try:
            ChatConversation = db.Model._decl_class_registry.get("ChatConversation")
        except Exception:
            ChatConversation = None

    ChatMessage = kwargs.get("ChatMessage")
    if ChatMessage is None:
        try:
            ChatMessage = db.Model._decl_class_registry.get("ChatMessage")
        except Exception:
            ChatMessage = None

    ResourceNote = kwargs.get("ResourceNote")
    if ResourceNote is None:
        try:
            ResourceNote = db.Model._decl_class_registry.get("ResourceNote")
        except Exception:
            ResourceNote = None

    ReminderSettings = kwargs.get("ReminderSettings")
    if ReminderSettings is None:
        try:
            ReminderSettings = db.Model._decl_class_registry.get("ReminderSettings")
        except Exception:
            ReminderSettings = None

    ProfileCompletionReminder = kwargs.get("ProfileCompletionReminder")
    if ProfileCompletionReminder is None:
        try:
            ProfileCompletionReminder = db.Model._decl_class_registry.get("ProfileCompletionReminder")
        except Exception:
            ProfileCompletionReminder = None

    compute_profile_completeness = kwargs.get("compute_profile_completeness")
    compute_profile_stats = kwargs.get("compute_profile_stats")
    get_canonical_countries = kwargs.get("CANONICAL_COUNTRIES")
    get_country_states = kwargs.get("country_states")
    get_state_cities = kwargs.get("state_cities")
    resolve_loc_func = kwargs.get("resolve_location")
    get_institution_details = kwargs.get("get_institution_details")
    get_institution_members = kwargs.get("get_institution_members")
    compute_task_prog_status = kwargs.get("compute_task_progress_status")
    PremiumApplication = kwargs.get("PremiumApplication")
    if PremiumApplication is None:
        try:
            PremiumApplication = db.Model._decl_class_registry.get("PremiumApplication")
        except Exception:
            PremiumApplication = None

    ScholarlyApplication = kwargs.get("ScholarlyApplication")
    if ScholarlyApplication is None:
        try:
            ScholarlyApplication = db.Model._decl_class_registry.get("ScholarlyApplication")
        except Exception:
            ScholarlyApplication = None

    get_supervisor_comparative_analytics = kwargs.get("get_supervisor_comparative_analytics")

    # -------------------------------------------------------------
    # LOCATION CASCADE ENDPOINTS (STRICT DROPDOWNS)
    # -------------------------------------------------------------
    @api_bp.route("/locations/countries", methods=["GET"])
    def api_get_countries():
        countries = get_canonical_countries() if callable(get_canonical_countries) else []
        return jsonify({"success": True, "countries": countries})

    @api_bp.route("/locations/states", methods=["GET"])
    def api_get_states():
        country = (request.args.get("country") or "").strip()
        states = get_country_states(country) if callable(get_country_states) and country else []
        return jsonify({"success": True, "country": country, "states": states})

    @api_bp.route("/locations/cities", methods=["GET"])
    def api_get_cities():
        country = (request.args.get("country") or "").strip()
        state = (request.args.get("state") or "").strip()
        cities = get_state_cities(country, state) if callable(get_state_cities) and country and state else []
        return jsonify({"success": True, "country": country, "state": state, "cities": cities})

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
        is_oauth = bool(data.get("is_oauth") or data.get("oauth"))

        if not email:
            return jsonify({"success": False, "message": "Email is required"}), 400

        user = User.query.filter(func.lower(User.email) == email).first()
        if not user and hasattr(User, "login_email_choice"):
            user = User.query.filter(
                or_(
                    and_(User.login_email_choice == "work", func.lower(User.work_email) == email),
                    and_(User.login_email_choice == "personal", func.lower(User.personal_email) == email)
                )
            ).first()

        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        if getattr(user, "login_email_choice", None):
            active_email = user.work_email if user.login_email_choice == "work" else user.personal_email
            active_email = (active_email or "").strip().lower()
            if active_email and active_email != email:
                kind = "work" if user.login_email_choice == "work" else "personal"
                return jsonify({"success": False, "message": f"This address is kept for records only. Please sign in with your {kind} email."}), 400

        if not is_oauth and user.password:
            valid = False
            try:
                valid = check_password_hash(user.password, password)
            except Exception:
                valid = (user.password == password)

            if not valid and password != user.password:
                return jsonify({"success": False, "message": "Invalid password"}), 401

        needs_otp = kwargs.get("account_needs_otp")
        if needs_otp and needs_otp(user.id):
            start_otp = kwargs.get("start_login_otp")
            if start_otp:
                try:
                    start_otp(user)
                except Exception as e:
                    logger.warning("Could not dispatch OTP for user %s: %s", user.email, e)
            return jsonify({
                "success": False,
                "otp_required": True,
                "email": user.email,
                "message": "A verification code has been sent to your email. Please enter it to continue."
            }), 200

        raw_role = str(user.user_type or "2").strip()
        role = raw_role
        if raw_role in ("admin", "supervisor", "0"):
            role = "0"
        elif raw_role in ("mentor", "1"):
            role = "1"
        elif raw_role in ("institution", "3"):
            role = "3"
        elif raw_role in ("seller", "partner", "4"):
            role = "4"
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

    @api_bp.route("/auth/verify_otp", methods=["POST"])
    def api_verify_otp():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        otp = (data.get("otp") or "").strip()

        if not email or not otp:
            return jsonify({"success": False, "message": "Email and OTP code are required"}), 400

        user = User.query.filter(func.lower(User.email) == email).first()
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        verify_fn = kwargs.get("verify_login_otp")
        if verify_fn:
            ok, msg = verify_fn(user, otp)
            if not ok:
                return jsonify({"success": False, "message": msg}), 400
        else:
            return jsonify({"success": False, "message": "Verification service unavailable"}), 500

        raw_role = str(user.user_type or "2").strip()
        role = raw_role
        if raw_role in ("admin", "supervisor", "0"):
            role = "0"
        elif raw_role in ("mentor", "1"):
            role = "1"
        elif raw_role in ("institution", "3"):
            role = "3"
        elif raw_role in ("seller", "partner", "4"):
            role = "4"
        else:
            role = "2"

        session["user_id"] = user.id
        session["email"] = user.email
        session["user_type"] = role
        session.permanent = True

        return jsonify({
            "success": True,
            "message": "Email verified successfully",
            "token": user.email,
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": role,
                "is_corporate": getattr(user, "is_corporate", False),
            }
        }), 200

    @api_bp.route("/auth/resend_otp", methods=["POST"])
    def api_resend_otp():
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()

        if not email:
            return jsonify({"success": False, "message": "Email is required"}), 400

        user = User.query.filter(func.lower(User.email) == email).first()
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        start_otp = kwargs.get("start_login_otp")
        if start_otp:
            start_otp(user)
            return jsonify({"success": True, "message": "Verification code resent successfully"}), 200
        return jsonify({"success": False, "message": "OTP service unavailable"}), 500

    @api_bp.route("/auth/register", methods=["POST"])
    def api_register():
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        user_type = str(data.get("user_type") or "2").strip()
        work_email = (data.get("work_email") or "").strip().lower() or None
        personal_email = (data.get("personal_email") or "").strip().lower() or None
        login_email_choice = (data.get("login_email_choice") or "").strip().lower()
        if login_email_choice not in ("work", "personal"):
            login_email_choice = None

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
        if work_email and hasattr(new_user, "work_email"):
            new_user.work_email = work_email
        if personal_email and hasattr(new_user, "personal_email"):
            new_user.personal_email = personal_email
        if login_email_choice and hasattr(new_user, "login_email_choice"):
            new_user.login_email_choice = login_email_choice
        db.session.add(new_user)
        db.session.commit()
        if kwargs.get("mark_account_unverified"):
            kwargs["mark_account_unverified"](new_user.id)

        try:
            if user_type == "1":
                mentor_p = MentorProfile(user_id=new_user.id, name=new_user.name, email=new_user.email)
                db.session.add(mentor_p)
                db.session.commit()
            elif user_type == "2":
                mentee_p = MenteeProfile(user_id=new_user.id)
                db.session.add(mentee_p)
                db.session.commit()
            elif user_type == "3":
                inst_p = Institution(user_id=new_user.id, status="active")
                db.session.add(inst_p)
                db.session.commit()
            elif user_type == "4" and SellerProfile:
                seller_p = SellerProfile(user_id=new_user.id, partner_label="Partner", shop_name=new_user.name, is_verified=True)
                db.session.add(seller_p)
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
        prof_stats = {}
        if compute_profile_stats:
            try:
                prof_stats = compute_profile_stats(user.id, "2") or {}
            except Exception:
                prof_stats = {}
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
                    "status": "active",
                    "completion": prof_stats.get("percentage", 0),
                    "missing_fields": prof_stats.get("missing_fields", []),
                    "completed_fields": prof_stats.get("completed_fields", 0),
                    "total_fields": prof_stats.get("total_fields", 12),
                    "profile_stats": prof_stats
                },
                "profile_stats": prof_stats
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
                "profile_picture": resolve_profile_pic(profile, user),
                "status": profile.status or "active",
                "completion": prof_stats.get("percentage", 100),
                "missing_fields": prof_stats.get("missing_fields", []),
                "completed_fields": prof_stats.get("completed_fields", 0),
                "total_fields": prof_stats.get("total_fields", 12),
                "profile_stats": prof_stats
            },
            "profile_stats": prof_stats
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

        if "country" in data or "state" in data or "city" in data:
            c_val = (data.get("country") or profile.country or "").strip()
            s_val = (data.get("state") or profile.state or "").strip()
            ci_val = (data.get("city") or profile.city or "").strip()
            if resolve_loc_func:
                c_res, s_res, ci_res, _, _ = resolve_loc_func(country=c_val, state=s_val, city=ci_val)
                profile.country = c_res
                profile.state = s_res
                profile.city = ci_res

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
    @api_bp.route("/mentee/dashboard", methods=["GET"])
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

    @api_bp.route("/mentors", methods=["GET"])
    @api_bp.route("/mentee/mentors", methods=["GET"])
    def api_get_all_mentors():
        """Returns list of registered mentors with formatted photos and computed ratings."""
        mentors = db.session.query(User, MentorProfile).outerjoin(
            MentorProfile, User.id == MentorProfile.user_id
        ).filter(or_(User.user_type == "1", User.user_type == "mentor")).limit(100).all()

        mentor_list = []
        for u, mp in mentors:
            prof = mp.profession if mp and mp.profession else "Expert Mentor"
            org = mp.organisation if mp and mp.organisation else "Verified Organisation"
            loc = mp.location if mp and mp.location else ""
            pic = resolve_profile_pic(mp, u)
            comp_rating = calc_mentor_rating_helper(u.id, mp, MenteeTask, db)

            mentor_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "profession": prof,
                "organisation": org,
                "organization": org,
                "location": loc,
                "industry": getattr(mp, "industry_sector", getattr(mp, "industry", "")) if mp else "",
                "years_of_experience": getattr(mp, "years_of_experience", "") if mp else "",
                "education": getattr(mp, "education", getattr(mp, "highest_qualification", "")) if mp else "",
                "bio": getattr(mp, "bio", getattr(mp, "mentorship_philosophy", getattr(mp, "additional_info", ""))) if mp else "",
                "about_me": getattr(mp, "mentorship_philosophy", getattr(mp, "additional_info", "")) if mp else "",
                "key_skills": getattr(mp, "key_skills", getattr(mp, "skills", "")) if mp else "",
                "skills": getattr(mp, "skills", getattr(mp, "key_skills", "")) if mp else "",
                "mobile_number": getattr(mp, "mobile_number", getattr(mp, "whatsapp", "")) if mp else "",
                "whatsapp": getattr(mp, "whatsapp", getattr(mp, "mobile_number", "")) if mp else "",
                "linkedin_link": getattr(mp, "linkedin_link", "") if mp else "",
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
            MentorshipRequest.final_status != "rejected",
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
            pic = resolve_profile_pic(mp, mentor_user)
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

    @api_bp.route("/mentee/request_mentorship", methods=["POST"])
    @api_bp.route("/request_mentorship", methods=["POST"])
    def api_request_mentorship():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        mentor_id = data.get("mentor_id")
        purpose = data.get("purpose")
        mentor_type = data.get("mentor_type") or "anchor"
        term = data.get("term") or "long"
        duration_months = data.get("duration_months")
        why_need_mentor = data.get("why_need_mentor")
        linkedin_profile = (data.get("linkedin_profile") or "").strip()
        if linkedin_profile and not linkedin_profile.startswith(("http://", "https://")):
            linkedin_profile = f"https://{linkedin_profile}"

        if not all([mentor_id, purpose, mentor_type, term, duration_months, why_need_mentor]):
            return jsonify({"success": False, "message": "Missing required fields"}), 400

        try:
            mentor_id = int(mentor_id)
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": "Invalid mentor ID"}), 400

        try:
            if isinstance(duration_months, str):
                import re
                nums = re.findall(r'\d+', duration_months)
                duration_months = int(nums[0]) if nums else int(duration_months)
            else:
                duration_months = int(duration_months)
            if duration_months <= 0:
                return jsonify({"success": False, "message": "Duration must be positive"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": "Invalid duration value"}), 400

        if user.id == mentor_id:
            return jsonify({"success": False, "message": "Cannot request mentorship from yourself"}), 400

        mentor_user_id = data.get("mentor_user_id")
        mentor_profile_id = data.get("mentor_profile_id")

        mentor_user = None
        if mentor_user_id:
            try:
                mentor_user = User.query.get(int(mentor_user_id))
            except Exception:
                pass

        if not mentor_user and mentor_profile_id:
            try:
                m_prof = MentorProfile.query.get(int(mentor_profile_id))
                if m_prof:
                    mentor_user = User.query.get(m_prof.user_id)
            except Exception:
                pass

        if not mentor_user:
            mentor_user = User.query.get(mentor_id)

        # If mentor_user is not found or is not a mentor, check if mentor_id is a MentorProfile.id
        if not mentor_user or str(getattr(mentor_user, "user_type", "")) not in ("1", "mentor"):
            m_prof = MentorProfile.query.get(mentor_id)
            if m_prof:
                resolved_user = User.query.get(m_prof.user_id)
                if resolved_user:
                    mentor_user = resolved_user

        if not mentor_user:
            return jsonify({"success": False, "message": "Mentor not found"}), 404

        mentor_id = mentor_user.id

        existing_reqs = MentorshipRequest.query.filter_by(
            mentee_id=user.id,
            mentor_id=mentor_id,
        ).all()

        for req in existing_reqs:
            if req.mentor_status == "pending" or req.supervisor_status == "pending":
                return jsonify({"success": False, "message": "You already have a pending request with this mentor."}), 400
            if req.mentor_status == "accepted" and req.supervisor_status == "approved" and req.final_status == "approved":
                return jsonify({"success": False, "message": "You are already connected to this mentor."}), 400

        try:
            new_request = MentorshipRequest(
                mentee_id=user.id,
                mentor_id=mentor_id,
                purpose=str(purpose).strip()[:1000] if purpose else "",
                mentor_type=str(mentor_type).strip()[:20] if mentor_type else "",
                term=str(term).strip()[:20] if term else "",
                duration_months=duration_months,
                why_need_mentor=str(why_need_mentor).strip() if why_need_mentor else "",
                linkedin_profile=linkedin_profile[:500] if linkedin_profile else None,
                mentor_status="pending",
                institution_status="pending",
                supervisor_status="pending",
                final_status="pending",
                created_at=datetime.utcnow()
            )
            db.session.add(new_request)
            db.session.commit()

            # Create in-app notification for mentor
            if Notification:
                try:
                    notif = Notification(
                        user_id=mentor_id,
                        message=f"You have a new mentorship request from {user.name or 'a mentee'}.",
                        link="/mentor_mentorship_request"
                    )
                    db.session.add(notif)
                    db.session.commit()
                except Exception as notif_err:
                    db.session.rollback()
                    logger.warning(f"Failed to create mentor notification: {notif_err}")

            return jsonify({"success": True, "message": "Mentorship request sent successfully!", "request_id": new_request.id})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": f"Failed to submit request: {str(e)}"}), 500

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
        prof_stats = {}
        if compute_profile_stats:
            try:
                prof_stats = compute_profile_stats(user.id, "1") or {}
            except Exception:
                prof_stats = {}

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
                "referred_by_seller_id": mp.referred_by_seller_id if mp else None,
                "referring_seller_name": (
                    (SellerProfile.query.filter_by(user_id=mp.referred_by_seller_id).first().display_name
                     if SellerProfile and SellerProfile.query.filter_by(user_id=mp.referred_by_seller_id).first()
                     else (User.query.get(mp.referred_by_seller_id).name if User.query.get(mp.referred_by_seller_id) else None))
                ) if (mp and mp.referred_by_seller_id) else None,
                "profile_picture": resolve_profile_pic(mp, user),
                "criminal_certificate": format_pic_url(mp.criminal_certificate if mp else None),
                "supervisor_rating": comp_rating,
                "status": mp.status if mp else "active",
                "completion": prof_stats.get("percentage", 100),
                "missing_fields": prof_stats.get("missing_fields", []),
                "completed_fields": prof_stats.get("completed_fields", 0),
                "total_fields": prof_stats.get("total_fields", 32),
                "profile_stats": prof_stats
            },
            "profile_stats": prof_stats
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

        if "location" in data or "country" in data or "city" in data:
            c_val = (data.get("country") or "").strip()
            s_val = (data.get("state") or "").strip()
            ci_val = (data.get("city") or "").strip()
            loc_val = (data.get("location") or "").strip()
            if resolve_loc_func:
                c_res, s_res, ci_res, loc_str, _ = resolve_loc_func(country=c_val, state=s_val, city=ci_val, legacy_location=loc_val)
                mp.location = loc_str
                if hasattr(mp, "country"): mp.country = c_res
                if hasattr(mp, "state"): mp.state = s_res
                if hasattr(mp, "city"): mp.city = ci_res

        # Handle seller referral
        if "has_seller_referral" in data or "referred_by_seller_id" in data:
            has_ref = data.get("has_seller_referral") in (True, "yes", "true", 1, "1")
            ref_id = data.get("referred_by_seller_id") if has_ref else None
            prev_seller_id = mp.referred_by_seller_id
            if ref_id:
                try:
                    new_seller_id = int(ref_id)
                    mp.referred_by_seller_id = new_seller_id
                    if prev_seller_id != new_seller_id:
                        seller = User.query.get(new_seller_id)
                        if seller:
                            import sys
                            send_fn = getattr(sys.modules.get('__main__'), 'send_email_reminder', None) or getattr(sys.modules.get('app'), 'send_email_reminder', None)
                            if send_fn:
                                try:
                                    send_fn(
                                        seller.email,
                                        "New Mentor Referred by Your Shop",
                                        f"<p>Hi {seller.name},</p><p>Mentor <strong>{user.name}</strong> has indicated they were referred by your shop!</p>"
                                    )
                                except Exception as e:
                                    logger.warning("Failed to send partner referral email: %s", e)
                                for sup in User.query.filter_by(user_type="0").all():
                                    try:
                                        send_fn(
                                            sup.email,
                                            f"New Mentor Referral from {seller.name}",
                                            f"<p>Hi {sup.name},</p><p>Mentor <strong>{user.name}</strong> was referred by partner <strong>{seller.name}</strong> ({seller.email}).</p>"
                                        )
                                    except Exception as e:
                                        logger.warning("Failed to send supervisor referral email: %s", e)
                except (ValueError, TypeError):
                    mp.referred_by_seller_id = None
            else:
                mp.referred_by_seller_id = None

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
            MentorshipRequest.final_status != "rejected",
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
            pic = resolve_profile_pic(mp, mentee_u)
            goal = mp.career_goal or mp.goal or "Career Development" if mp else "Mentee"
            inst = mp.institution_name or mp.school_college_name or "Student" if mp else "Student"

            m_rating = calc_mentee_rating_helper(mentee_u.id, db)

            connected.append({
                "id": mentee_u.id,
                "user_id": str(mentee_u.id),
                "name": mentee_u.name,
                "career_goal": goal,
                "goal": goal,
                "institution_name": inst,
                "education_level": mp.education_level if mp and mp.education_level else "",
                "who_am_i": mp.who_am_i if mp and mp.who_am_i else "",
                "key_skills": mp.key_skills if mp and mp.key_skills else "",
                "course_stream": mp.course_stream if mp and mp.course_stream else "",
                "city": mp.city if mp and mp.city else "",
                "state": mp.state if mp and mp.state else "",
                "country": mp.country if mp and mp.country else "",
                "rating": m_rating,
                "profile_picture": pic,
                "status": "active"
            })

        return jsonify({"success": True, "mentees": connected})

    @api_bp.route("/mentees", methods=["GET"])
    @api_bp.route("/mentor/all_mentees", methods=["GET"])
    def api_get_all_mentees():
        """Returns all registered mentees for Find Mentees directory."""
        mentees = db.session.query(User, MenteeProfile).outerjoin(
            MenteeProfile, User.id == MenteeProfile.user_id
        ).filter(or_(User.user_type == "2", User.user_type == "mentee")).limit(100).all()

        result = []
        for u, mp in mentees:
            pic = resolve_profile_pic(mp, u)
            goal = mp.career_goal or mp.goal or "Career Guidance" if mp else "Mentee"
            inst = mp.institution_name or mp.school_college_name or "Student" if mp else "Student"
            m_rating = calc_mentee_rating_helper(u.id, db)

            result.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "career_goal": goal,
                "goal": goal,
                "institution_name": inst,
                "education_level": mp.education_level if mp and mp.education_level else "",
                "who_am_i": mp.who_am_i if mp and mp.who_am_i else "",
                "key_skills": mp.key_skills if mp and mp.key_skills else "",
                "course_stream": mp.course_stream if mp and mp.course_stream else "",
                "city": mp.city if mp and mp.city else "",
                "state": mp.state if mp and mp.state else "",
                "country": mp.country if mp and mp.country else "",
                "rating": m_rating,
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
                "profile_picture": resolve_profile_pic(mp, mentee),
                "purpose": getattr(r, "purpose", "") or "Mentorship Request",
                "duration_months": getattr(r, "duration_months", 3),
                "mentor_status": getattr(r, "mentor_status", "pending"),
                "supervisor_status": getattr(r, "supervisor_status", "pending"),
                "final_status": getattr(r, "final_status", "pending"),
                "created_at": r.created_at.strftime("%Y-%m-%d") if getattr(r, "created_at", None) else ""
            })
        return jsonify({"success": True, "requests": result})

    @api_bp.route("/mentor/requests/<int:req_id>/action", methods=["POST"])
    @api_bp.route("/mentor/requests/<int:req_id>", methods=["POST", "PUT"])
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

    @api_bp.route("/mentor/certificate_eligibility", methods=["GET"])
    def api_mentor_certificate_eligibility():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        completed_tasks = MenteeTask.query.filter(
            MenteeTask.mentor_id == user.id,
            or_(MenteeTask.status == "Done", MenteeTask.status == "completed", MenteeTask.progress >= 100)
        ).count()

        active_mentees = MentorshipRequest.query.filter(
            MentorshipRequest.mentor_id == user.id,
            MentorshipRequest.final_status.in_(["approved", "completed", "active"])
        ).count()

        sessions_count = MeetingRequest.query.filter(
            or_(MeetingRequest.requested_to_id == user.id, MeetingRequest.requester_id == user.id),
            MeetingRequest.status != "rejected"
        ).count()

        is_scholarly = getattr(user, "scholarly", False) == True
        is_corporate = getattr(user, "is_corporate", False) == True

        return jsonify({
            "success": True,
            "eligibility": {
                "isEligible": True,
                "completedTasks": completed_tasks,
                "requiredTasks": 0,
                "activeMentees": active_mentees,
                "sessionsCount": sessions_count,
                "isScholarly": is_scholarly,
                "isCorporate": is_corporate,
                "userType": "1"
            }
        })

    @api_bp.route("/certificate/data", methods=["GET"])
    def api_get_certificate_data():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        # Format registration date
        if getattr(user, "created_at", None):
            registration_date = user.created_at.strftime("%B %d, %Y")
        elif getattr(user, "oauth_created_at", None):
            registration_date = user.oauth_created_at.strftime("%B %d, %Y")
        else:
            registration_date = "Registration date not available"

        user_type = str(user.user_type or "2")
        connections_list = []
        sessions_list = []
        tasks_list = []
        mentorship_details = []
        task_ratings = []

        def _norm_status(st):
            s = str(st or "").strip().lower()
            if s in ["done", "completed"]:
                return "completed"
            elif s in ["in_progress", "in-progress", "committed"]:
                return "in-progress"
            return "pending"

        if user_type == "1":  # Mentor
            active_mentorships = MentorshipRequest.query.filter(
                MentorshipRequest.mentor_id == user.id,
                MentorshipRequest.final_status.in_(["approved", "completed", "active"])
            ).all()
            seen_mentee_ids = set()
            for mr in active_mentorships:
                mentee = User.query.get(mr.mentee_id)
                if mentee and mentee.id not in seen_mentee_ids:
                    seen_mentee_ids.add(mentee.id)
                    connections_list.append({
                        "id": mr.id,
                        "name": mentee.name,
                        "type": "mentee",
                        "is_corporate": getattr(mentee, "is_corporate", False)
                    })

                mentorship_details.append({
                    "id": mr.id,
                    "partner": mentee.name if mentee else "Mentee",
                    "purpose": mr.purpose or "Mentorship Program",
                    "mentor_type": (mr.mentor_type or "Official").capitalize(),
                    "term": ("Long-term" if mr.term == "long" else "Short-term") if mr.term else "Standard",
                    "duration": f"{mr.duration_months} months" if mr.duration_months else "3 months",
                    "status": (mr.final_status or "pending").capitalize(),
                    "started": mr.created_at.strftime("%b %d, %Y") if getattr(mr, "created_at", None) else "Active"
                })

            # Linked mentees via MenteeTask
            mentee_tasks = MenteeTask.query.filter_by(mentor_id=user.id).all()
            for t in mentee_tasks:
                if t.mentee_id and t.mentee_id not in seen_mentee_ids:
                    mentee = User.query.get(t.mentee_id)
                    if mentee:
                        seen_mentee_ids.add(t.mentee_id)
                        connections_list.append({
                            "id": f"t_{t.id}",
                            "name": mentee.name,
                            "type": "mentee",
                            "is_corporate": getattr(mentee, "is_corporate", False)
                        })

                mt = getattr(t, "master_task", None)
                task_name = (mt.purpose_of_call if mt and mt.purpose_of_call else (mt.journey_phase if mt and mt.journey_phase else f"Task #{t.meeting_number}"))
                m_user = User.query.get(t.mentee_id)
                tasks_list.append({
                    "id": t.id,
                    "title": task_name,
                    "status": _norm_status(t.status),
                    "with": m_user.name if m_user else "Mentee"
                })

            if PersonalTask:
                p_tasks = PersonalTask.query.filter_by(mentor_id=user.id).all()
                for pt in p_tasks:
                    tasks_list.append({
                        "id": f"p{pt.id}",
                        "title": pt.title or "Personal Task",
                        "status": _norm_status(pt.status),
                        "with": "Personal"
                    })

            # Sessions
            sessions = MeetingRequest.query.filter(
                or_(MeetingRequest.requested_to_id == user.id, MeetingRequest.requester_id == user.id),
                MeetingRequest.status != "rejected"
            ).order_by(MeetingRequest.meeting_date.desc()).all()
            for s in sessions:
                other_id = s.requester_id if s.requested_to_id == user.id else s.requested_to_id
                other_u = User.query.get(other_id)
                m_date = getattr(s, "meeting_date", None)
                sessions_list.append({
                    "id": s.id,
                    "title": getattr(s, "meeting_title", None) or "Mentorship Meeting",
                    "date": m_date.strftime("%b %d, %Y") if m_date else "Scheduled",
                    "with": other_u.name if other_u else "Mentee"
                })

            connected_label = "Active Mentees"
            sessions_label = "Sessions Conducted"
            is_eligible = True

        else:  # Mentee (user_type == "2")
            active_mentorships = MentorshipRequest.query.filter(
                MentorshipRequest.mentee_id == user.id,
                MentorshipRequest.final_status.in_(["approved", "completed", "active"])
            ).all()
            seen_mentor_ids = set()
            for mr in active_mentorships:
                mentor = User.query.get(mr.mentor_id)
                if mentor and mentor.id not in seen_mentor_ids:
                    seen_mentor_ids.add(mentor.id)
                    connections_list.append({
                        "id": mr.id,
                        "name": mentor.name,
                        "type": "mentor",
                        "is_corporate": getattr(mentor, "is_corporate", False)
                    })

                mentorship_details.append({
                    "id": mr.id,
                    "partner": mentor.name if mentor else "Mentor",
                    "purpose": mr.purpose or "Mentorship Program",
                    "mentor_type": (mr.mentor_type or "Official").capitalize(),
                    "term": ("Long-term" if mr.term == "long" else "Short-term") if mr.term else "Standard",
                    "duration": f"{mr.duration_months} months" if mr.duration_months else "3 months",
                    "status": (mr.final_status or "pending").capitalize(),
                    "started": mr.created_at.strftime("%b %d, %Y") if getattr(mr, "created_at", None) else "Active"
                })

            mentee_tasks = MenteeTask.query.filter_by(mentee_id=user.id).all()
            for t in mentee_tasks:
                if t.mentor_id and t.mentor_id not in seen_mentor_ids:
                    mentor = User.query.get(t.mentor_id)
                    if mentor:
                        seen_mentor_ids.add(t.mentor_id)
                        connections_list.append({
                            "id": f"t_{t.id}",
                            "name": mentor.name,
                            "type": "mentor",
                            "is_corporate": getattr(mentor, "is_corporate", False)
                        })

                mt = getattr(t, "master_task", None)
                task_name = (mt.purpose_of_call if mt and mt.purpose_of_call else (mt.journey_phase if mt and mt.journey_phase else f"Task #{t.meeting_number}"))
                m_user = User.query.get(t.mentor_id)
                tasks_list.append({
                    "id": t.id,
                    "title": task_name,
                    "status": _norm_status(t.status),
                    "with": m_user.name if m_user else "Mentor"
                })

            if PersonalTask:
                p_tasks = PersonalTask.query.filter_by(mentee_id=user.id).all()
                for pt in p_tasks:
                    tasks_list.append({
                        "id": f"p{pt.id}",
                        "title": pt.title or "Personal Task",
                        "status": _norm_status(pt.status),
                        "with": "Self"
                    })

            sessions = MeetingRequest.query.filter(
                or_(MeetingRequest.requested_to_id == user.id, MeetingRequest.requester_id == user.id),
                MeetingRequest.status != "rejected"
            ).order_by(MeetingRequest.meeting_date.desc()).all()
            for s in sessions:
                other_id = s.requested_to_id if s.requester_id == user.id else s.requester_id
                other_u = User.query.get(other_id)
                m_date = getattr(s, "meeting_date", None)
                sessions_list.append({
                    "id": s.id,
                    "title": getattr(s, "meeting_title", None) or "Mentorship Session",
                    "date": m_date.strftime("%b %d, %Y") if m_date else "Scheduled",
                    "with": other_u.name if other_u else "Mentor"
                })

            connected_label = "Active Mentors"
            sessions_label = "Sessions Attended"
            completed_count = sum(1 for t in tasks_list if t["status"] == "completed")
            is_eligible = completed_count >= 5 or getattr(user, "scholarly", False) or getattr(user, "is_corporate", False)

        # Task ratings
        tr_model = kwargs.get("TaskRating")
        if not tr_model:
            try:
                from app import TaskRating as TR
                tr_model = TR
            except Exception:
                tr_model = None

        if tr_model:
            if user_type == "1":
                ratings = tr_model.query.filter_by(mentor_id=user.id).all()
            else:
                ratings = tr_model.query.filter_by(mentee_id=user.id).all()
            for r in ratings:
                me_u = User.query.get(r.mentee_id)
                mr_u = User.query.get(r.mentor_id)
                stars = "★" * (r.rating or 5) + "☆" * (5 - (r.rating or 5))
                task_ratings.append({
                    "task_id": r.task_id,
                    "task_type": r.task_type,
                    "mentee": me_u.name if me_u else "Mentee",
                    "mentor": mr_u.name if mr_u else "Mentor",
                    "rating": r.rating or 5,
                    "stars": stars,
                    "feedback": r.feedback or "Consistent progress and commitment.",
                    "strengths": r.strengths or "Diligent execution and clear communication.",
                    "improvements": r.improvements or "Continue exploring advanced concepts.",
                    "rated_at": r.rated_at.strftime("%b %d, %Y") if getattr(r, "rated_at", None) else "Completed"
                })

        # Calculate initial stats
        completed_tasks = sum(1 for t in tasks_list if t["status"] == "completed")
        in_progress_tasks = sum(1 for t in tasks_list if t["status"] == "in-progress")
        pending_tasks = len(tasks_list) - completed_tasks - in_progress_tasks

        return jsonify({
            "success": True,
            "data": {
                "user_name": user.name,
                "user_type": user_type,
                "user_id": user.id,
                "cert_id": f"WES-{user_type}-{user.id}",
                "registration_date": registration_date,
                "connections_list": connections_list,
                "sessions_list": sessions_list,
                "tasks_list": tasks_list,
                "mentorship_details": mentorship_details,
                "task_ratings": task_ratings,
                "mentorship_stats": {
                    "connected_count": len(connections_list),
                    "connected_type": connected_label,
                    "sessions_count": len(sessions_list),
                    "sessions_type": sessions_label
                },
                "task_stats": {
                    "total": len(tasks_list),
                    "completed": completed_tasks,
                    "in_progress": in_progress_tasks,
                    "pending": pending_tasks
                },
                "is_eligible": is_eligible
            }
        })

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

        import re
        import hashlib

        result = []
        for m in meetings:
            other_id = m.requested_to_id if m.requester_id == user.id else m.requester_id
            other_user = User.query.get(other_id)
            other_name = other_user.name if other_user else f"User #{other_id}"

            clean_desc = re.sub(r'<!--.*?-->', '', m.meeting_description or '', flags=re.DOTALL).strip()
            meet_link = (m.meet_link or "").strip()
            bogus_match = re.match(r"^https?://meet\.google\.com/[a-f0-9]{3}-[a-f0-9]{4}-[a-f0-9]{3}$", meet_link, re.I)
            if not meet_link or bogus_match or meet_link.lower() == "not specified":
                meet_link = "https://meet.google.com/new"

            req_user = User.query.get(m.requester_id)
            to_user = User.query.get(m.requested_to_id)
            req_name = req_user.name if req_user else "User"
            to_name = to_user.name if to_user else "User"

            # Determine who is mentor and mentee
            # user_type: 1=mentor, 2=mentee, 3=institution, 4=supervisor
            mentor_name = to_name if getattr(to_user, "user_type", None) == 1 else (req_name if getattr(req_user, "user_type", None) == 1 else other_name)
            mentee_name = req_name if getattr(req_user, "user_type", None) == 2 else (to_name if getattr(to_user, "user_type", None) == 2 else user.name)

            result.append({
                "id": m.id,
                "requester_id": m.requester_id,
                "requested_to_id": m.requested_to_id,
                "title": m.meeting_title,
                "meeting_title": m.meeting_title,
                "description": clean_desc,
                "meeting_description": clean_desc,
                "date": m.meeting_date.strftime("%Y-%m-%d") if m.meeting_date else "",
                "meeting_date": m.meeting_date.strftime("%Y-%m-%d") if m.meeting_date else "",
                "time": m.meeting_time.strftime("%I:%M %p") if m.meeting_time else "",
                "meeting_time": m.meeting_time.strftime("%I:%M %p") if m.meeting_time else "",
                "status": m.status or "scheduled",
                "other_party_name": other_name,
                "mentor_name": mentor_name,
                "mentee_name": mentee_name,
                "meet_link": meet_link
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

        # Enforce that mentee can only schedule meetings with mentors in an active, approved mentorship
        if getattr(user, "user_type", None) in ("2", "mentee"):
            approved = MentorshipRequest.query.filter(
                MentorshipRequest.mentee_id == user.id,
                MentorshipRequest.mentor_id == int(requested_to_id),
                or_(
                    MentorshipRequest.final_status == "approved",
                    MentorshipRequest.supervisor_status == "approved",
                    MentorshipRequest.mentor_status == "accepted"
                )
            ).first()
            if not approved:
                return jsonify({
                    "success": False,
                    "message": "You can only schedule meetings with mentors in an approved mentorship with you."
                }), 403

        try:
            m_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except Exception:
            m_date = datetime.utcnow().date()

        try:
            clean_time = time_str.strip()
            if "AM" in clean_time.upper() or "PM" in clean_time.upper():
                m_time = datetime.strptime(clean_time, "%I:%M %p").time()
            else:
                m_time = datetime.strptime(clean_time[:8], "%H:%M:%S" if len(clean_time) >= 8 else "%H:%M").time()
        except Exception:
            m_time = datetime.strptime("10:00", "%H:%M").time()

        duration = int(data.get("duration") or data.get("meeting_duration") or 60)
        meet_link = (data.get("meet_link") or "").strip()
        bogus_match = re.match(r"^https?://meet\.google\.com/[a-f0-9]{3}-[a-f0-9]{4}-[a-f0-9]{3}$", meet_link, re.I)
        if not meet_link or bogus_match:
            platform = (data.get("platform") or "").lower()
            if "team" in platform:
                meet_link = "https://teams.live.com/meet/create"
            else:
                meet_link = "https://meet.google.com/new"

        new_meeting = MeetingRequest(
            requester_id=user.id,
            requested_to_id=int(requested_to_id),
            meeting_title=title,
            meeting_description=desc,
            meeting_date=m_date,
            meeting_time=m_time,
            meeting_duration=duration,
            meet_link=meet_link,
            status="scheduled"
        )
        db.session.add(new_meeting)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Meeting scheduled successfully",
            "id": new_meeting.id,
            "meet_link": meet_link
        }), 201

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
    # 5B. TASK FEEDBACK (MENTEE) & REFLECTIONS (MENTOR)
    # -------------------------------------------------------------
    @api_bp.route("/tasks/feedback", methods=["GET", "POST"])
    def api_task_feedback():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        if request.method == "GET":
            task_id = request.args.get("task_id")
            task_type = request.args.get("task_type", "master")
            if not task_id:
                return jsonify({"success": False, "message": "task_id required"}), 400

            fb = None
            if MenteeFeedback:
                fb = MenteeFeedback.query.filter_by(
                    task_type=task_type,
                    task_id=int(task_id),
                    mentee_id=user.id
                ).first()
                if not fb and str(user.user_type) in ("1", "mentor"):
                    fb = MenteeFeedback.query.filter_by(
                        task_type=task_type,
                        task_id=int(task_id)
                    ).first()

            return jsonify({
                "success": True,
                "feedback": fb.to_dict() if fb and hasattr(fb, "to_dict") else None
            })

        data = request.get_json(silent=True) or {}
        task_id = data.get("task_id")
        task_type = data.get("task_type", "master")
        if not task_id:
            return jsonify({"success": False, "message": "task_id required"}), 400

        task_id = int(task_id)
        if not MenteeFeedback:
            return jsonify({"success": False, "message": "MenteeFeedback model unavailable"}), 500

        fb = MenteeFeedback.query.filter_by(
            mentee_id=user.id,
            task_type=task_type,
            task_id=task_id
        ).first()

        if not fb:
            fb = MenteeFeedback(
                mentee_id=user.id,
                task_type=task_type,
                task_id=task_id
            )
            db.session.add(fb)

        fb.rating = int(data.get("rating")) if data.get("rating") else None
        fb.mentor_rating = int(data.get("mentor_rating")) if data.get("mentor_rating") else None
        fb.text = (data.get("text") or data.get("reflection") or "").strip()
        fb.challenges = (data.get("challenges") or "").strip()
        fb.next_steps = (data.get("nextSteps") or data.get("next_steps") or "").strip()
        fb.extra = (data.get("extra") or "").strip()
        fb.created_at = datetime.utcnow()

        try:
            db.session.commit()
            return jsonify({
                "success": True,
                "message": "Feedback submitted successfully",
                "feedback": fb.to_dict() if hasattr(fb, "to_dict") else {
                    "id": fb.id,
                    "task_id": fb.task_id,
                    "rating": fb.rating,
                    "text": fb.text
                }
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    @api_bp.route("/tasks/reflection", methods=["GET", "POST"])
    def api_task_reflection():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        if request.method == "GET":
            task_id = request.args.get("task_id")
            task_type = request.args.get("task_type", "master")
            if not task_id:
                return jsonify({"success": False, "message": "task_id required"}), 400

            refl = None
            if MentorReflection:
                refl = MentorReflection.query.filter_by(
                    task_type=task_type,
                    task_id=int(task_id)
                ).first()

            return jsonify({
                "success": True,
                "reflection": refl.to_dict() if refl and hasattr(refl, "to_dict") else None
            })

        data = request.get_json(silent=True) or {}
        task_id = data.get("task_id")
        task_type = data.get("task_type", "master")
        if not task_id:
            return jsonify({"success": False, "message": "task_id required"}), 400

        task_id = int(task_id)
        if not MentorReflection:
            return jsonify({"success": False, "message": "MentorReflection model unavailable"}), 500

        refl = MentorReflection.query.filter_by(
            mentor_id=user.id,
            task_type=task_type,
            task_id=task_id
        ).first()

        if not refl:
            refl = MentorReflection(
                mentor_id=user.id,
                task_type=task_type,
                task_id=task_id
            )
            db.session.add(refl)

        refl.text = (data.get("text") or data.get("reflection") or "").strip()
        refl.extra = (data.get("extra") or "").strip()
        refl.created_at = datetime.utcnow()

        # Also support TaskRating record if mentor gave rating/feedback
        if TaskRating and data.get("rating"):
            t_rate = TaskRating.query.filter_by(
                task_type=task_type,
                task_id=task_id,
                mentor_id=user.id
            ).first()
            if not t_rate:
                # determine mentee_id
                target_mentee_id = data.get("mentee_id")
                if not target_mentee_id:
                    if task_type == "master":
                        mt = db.session.get(MenteeTask, task_id)
                        target_mentee_id = mt.mentee_id if mt else None
                    elif PersonalTask:
                        pt = db.session.get(PersonalTask, task_id)
                        target_mentee_id = pt.mentee_id if pt else None

                if target_mentee_id:
                    t_rate = TaskRating(
                        task_id=task_id,
                        task_type=task_type,
                        mentee_id=int(target_mentee_id),
                        mentor_id=user.id,
                        rating=int(data.get("rating")),
                        feedback=data.get("text") or "",
                        strengths=data.get("strengths") or "",
                        improvements=data.get("improvements") or ""
                    )
                    db.session.add(t_rate)
            else:
                t_rate.rating = int(data.get("rating"))
                t_rate.feedback = data.get("text") or t_rate.feedback
                t_rate.strengths = data.get("strengths") or t_rate.strengths
                t_rate.improvements = data.get("improvements") or t_rate.improvements

        try:
            db.session.commit()
            return jsonify({
                "success": True,
                "message": "Reflection saved successfully",
                "reflection": refl.to_dict() if hasattr(refl, "to_dict") else {
                    "id": refl.id,
                    "task_id": refl.task_id,
                    "text": refl.text
                }
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # -------------------------------------------------------------
    # 6. INSTITUTION & ADMIN MODULES
    # -------------------------------------------------------------
    def _helper_get_inst_context(req_user=None):
        u = req_user or get_current_user_from_req(User)
        inst_obj = None
        inst_id = None
        inst_name = "Institution"
        if u:
            if callable(get_institution_details):
                try:
                    inst_obj, inst_id, inst_name, _ = get_institution_details(u)
                except Exception as e:
                    logger.warning(f"Error calling get_institution_details: {e}")
            if not inst_obj and getattr(u, "institution_id", None):
                inst_obj = db.session.get(Institution, u.institution_id) if hasattr(db.session, "get") else Institution.query.get(u.institution_id)
                inst_id = inst_obj.id if inst_obj else u.institution_id
                inst_name = inst_obj.name if inst_obj else (getattr(u, "institution", None) or u.name)
            if not inst_obj and getattr(u, "id", None):
                inst_obj = Institution.query.filter_by(user_id=u.id).first()
                if inst_obj:
                    inst_id = inst_obj.id
                    inst_name = inst_obj.name

        mentors = []
        mentees = []
        if u and callable(get_institution_members):
            try:
                # Match Flask app.py institutiondashboard & institution_mentors routes:
                # Institution mentors directory exposes all platform mentors so coordinators can browse/pair
                all_m = User.query.options(joinedload(User.mentor_profile)).filter_by(user_type="1").all()
                all_m.sort(key=lambda x: (x.name or "").lower())
                mentors = all_m
                _, mentees = get_institution_members(u, include_paired=True)
            except Exception as e:
                logger.warning(f"Error calling get_institution_members: {e}")

        if not mentors:
            mentors = User.query.filter_by(user_type="1").all()
        if not mentees:
            if inst_id:
                mentees = User.query.filter(User.user_type == "2", User.institution_id == inst_id).all()
            if not mentees and u:
                mentees = User.query.filter(User.user_type == "2", func.lower(User.institution) == func.lower(u.name)).all()
            if not mentees and (not u or getattr(u, "user_type", None) == "0"):
                mentees = User.query.filter_by(user_type="2").all()

        return u, inst_obj, inst_id, inst_name, mentors, mentees

    @api_bp.route("/institution/stats", methods=["GET"])
    def api_get_institution_stats():
        user, inst_obj, inst_id, inst_name, mentors, mentees = _helper_get_inst_context()
        mentee_ids = [m.id for m in mentees] if mentees else []
        
        active_pairs = 0
        pending_pairs = 0
        if mentee_ids:
            active_pairs = MentorshipRequest.query.filter(
                MentorshipRequest.mentee_id.in_(mentee_ids),
                MentorshipRequest.final_status == "approved"
            ).count()
            pending_pairs = MentorshipRequest.query.filter(
                MentorshipRequest.mentee_id.in_(mentee_ids),
                MentorshipRequest.final_status != "approved"
            ).count()
        elif user and getattr(user, "user_type", None) == "0":
            active_pairs = MentorshipRequest.query.filter_by(final_status="approved").count()
            pending_pairs = MentorshipRequest.query.filter(MentorshipRequest.final_status != "approved").count()

        notes_count = 0
        if ResourceNote:
            try:
                if inst_id and user:
                    notes_count = ResourceNote.query.filter(
                        or_(ResourceNote.mentee_id == user.id, ResourceNote.institution_id == inst_id)
                    ).count()
                elif user:
                    notes_count = ResourceNote.query.filter_by(mentee_id=user.id).count()
            except Exception:
                notes_count = 0

        return jsonify({
            "success": True,
            "stats": {
                "total_mentors": len(mentors),
                "total_mentees": len(mentees),
                "active_mentorships": active_pairs,
                "pending_requests": pending_pairs,
                "total_notes": notes_count,
                "institution_name": inst_name or (user.name if user else "Institution"),
                "coordinator_name": getattr(inst_obj, "contact_person", None) or (user.name if user else "Coordinator"),
                "coordinator_avatar": resolve_profile_pic(inst_obj, user) if user else "",
                "logo": resolve_profile_pic(inst_obj, user) if user else "",
                "academic_term": "Autumn 2025 Cohort Cycle"
            }
        })

    @api_bp.route("/institution/members", methods=["GET"])
    def api_get_institution_members():
        """Returns mentors and mentees under the institution."""
        user, inst_obj, inst_id, inst_name, mentors, mentees = _helper_get_inst_context()
        req_type = (request.args.get("type") or "").strip().lower()
        search_query = (request.args.get("search") or "").strip().lower()

        m_list = []
        for u in mentors:
            if search_query and search_query not in (u.name or "").lower() and search_query not in (u.email or "").lower():
                continue
            mp = u.mentor_profile if hasattr(u, "mentor_profile") and u.mentor_profile else MentorProfile.query.filter_by(user_id=u.id).first()
            rating = calc_mentor_rating_helper(u.id, mp, MenteeTask, db)
            m_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name or "Mentor",
                "email": u.email or "",
                "profession": mp.profession if mp and mp.profession else "Mentor",
                "organisation": mp.organisation if mp and mp.organisation else "Organisation",
                "location": mp.location if mp and mp.location else "Luxembourg",
                "profile_picture": resolve_profile_pic(mp, u),
                "rating": rating,
                "is_premium": bool(getattr(u, "premium", False)),
                "scholarly": bool(getattr(u, "scholarly", False)),
                "skills": [s.strip() for s in (mp.skills or "").split(",") if s.strip()] if mp else [],
                "institution": getattr(u, "display_institution", None) or getattr(u, "institution", None) or (mp.organisation if mp and mp.organisation else "Independent Mentor"),
                "institution_name": getattr(u, "display_institution", None) or getattr(u, "institution", None) or (mp.organisation if mp and mp.organisation else "Independent Mentor"),
                "institution_id": getattr(u, "display_institution_id", None) or getattr(u, "institution_id", None),
                "role": "Mentor"
            })

        me_list = []
        for u in mentees:
            if search_query and search_query not in (u.name or "").lower() and search_query not in (u.email or "").lower():
                continue
            mp = u.mentee_profile if hasattr(u, "mentee_profile") and u.mentee_profile else MenteeProfile.query.filter_by(user_id=u.id).first()
            rating = calc_mentee_rating_helper(u.id, db)
            me_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name or "Mentee",
                "email": u.email or "",
                "institution_name": (mp.institution_name if mp and mp.institution_name else None) or getattr(u, "institution", None) or inst_name,
                "career_goal": (mp.career_goal or mp.goal) if mp else "Career Guidance",
                "profile_picture": resolve_profile_pic(mp, u),
                "rating": rating,
                "scholarly": bool(getattr(u, "scholarly", False)),
                "role": "Mentee"
            })

        all_members = m_list if req_type == "mentors" else me_list if req_type == "mentees" else (m_list + me_list)
        return jsonify({
            "success": True,
            "members": all_members,
            "mentors": m_list,
            "mentees": me_list
        })

    @api_bp.route("/institution/requests", methods=["GET"])
    @api_bp.route("/institution/mentorships", methods=["GET"])
    def api_get_institution_mentorships():
        user, inst_obj, inst_id, inst_name, mentors, mentees = _helper_get_inst_context()
        mentee_ids = [m.id for m in mentees] if mentees else []
        mentor_ids = [m.id for m in mentors] if mentors else []

        query = MentorshipRequest.query
        if mentee_ids:
            query = query.filter(MentorshipRequest.mentee_id.in_(mentee_ids))
        elif not (user and getattr(user, "user_type", None) == "0"):
            return jsonify({"success": True, "mentorships": [], "requests": []})

        status_param = (request.args.get("status") or "").strip().lower()
        if status_param == "pending":
            query = query.filter(MentorshipRequest.final_status != "approved")
        elif status_param == "approved":
            query = query.filter(MentorshipRequest.final_status == "approved")
        elif status_param:
            query = query.filter(func.lower(MentorshipRequest.final_status) == status_param)

        reqs = query.order_by(MentorshipRequest.created_at.desc()).limit(100).all()
        result = []
        for r in reqs:
            me = User.query.get(r.mentee_id)
            mo = User.query.get(r.mentor_id)
            ep = me.mentee_profile if me and hasattr(me, "mentee_profile") and me.mentee_profile else (MenteeProfile.query.filter_by(user_id=me.id).first() if me else None)
            mp = mo.mentor_profile if mo and hasattr(mo, "mentor_profile") and mo.mentor_profile else (MentorProfile.query.filter_by(user_id=mo.id).first() if mo else None)

            # Task completion
            total_tasks = MenteeTask.query.filter(
                or_(
                    and_(MenteeTask.mentee_id == r.mentee_id, MenteeTask.mentor_id == r.mentor_id),
                    getattr(MenteeTask, "mentorship_request_id", None) == r.id
                )
            ).count() if MenteeTask else 0
            completed_tasks = MenteeTask.query.filter(
                or_(
                    and_(MenteeTask.mentee_id == r.mentee_id, MenteeTask.mentor_id == r.mentor_id),
                    getattr(MenteeTask, "mentorship_request_id", None) == r.id
                ),
                MenteeTask.status.in_(["Done", "Completed", "done", "completed"])
            ).count() if MenteeTask else 0

            # Meeting counts
            total_meetings = MeetingRequest.query.filter(
                or_(
                    and_(MeetingRequest.requester_id == r.mentee_id, MeetingRequest.requested_to_id == r.mentor_id),
                    and_(MeetingRequest.requester_id == r.mentor_id, MeetingRequest.requested_to_id == r.mentee_id)
                )
            ).count() if MeetingRequest else 0
            completed_meetings = MeetingRequest.query.filter(
                or_(
                    and_(MeetingRequest.requester_id == r.mentee_id, MeetingRequest.requested_to_id == r.mentor_id),
                    and_(MeetingRequest.requester_id == r.mentor_id, MeetingRequest.requested_to_id == r.mentee_id)
                ),
                MeetingRequest.status.in_(["Completed", "completed"])
            ).count() if MeetingRequest else 0

            result.append({
                "id": r.id,
                "mentee_id": r.mentee_id,
                "mentee_name": me.name if me else f"Mentee #{r.mentee_id}",
                "mentee_email": me.email if me else "",
                "mentee_avatar": resolve_profile_pic(ep, me) if me else "",
                "mentee_scholarly": bool(getattr(me, "scholarly", False)) if me else False,
                "mentee_goal": (ep.career_goal or ep.goal) if ep else "",
                "mentor_id": r.mentor_id,
                "mentor_name": mo.name if mo else f"Mentor #{r.mentor_id}",
                "mentor_email": mo.email if mo else "",
                "mentor_avatar": resolve_profile_pic(mp, mo) if mo else "",
                "mentor_rating": calc_mentor_rating_helper(mo.id, mp, MenteeTask, db) if mo else 5.0,
                "mentor_premium": bool(getattr(mo, "premium", False)) if mo else False,
                "mentor_profession": mp.profession if mp and mp.profession else "Mentor",
                "mentor_organisation": mp.organisation if mp and mp.organisation else "Organisation",
                "purpose": getattr(r, "purpose", "") or "Mentorship Guidance",
                "mentor_type": getattr(r, "mentor_type", "guidance") or "guidance",
                "duration_months": getattr(r, "duration_months", 3) or 3,
                "final_status": r.final_status or "pending",
                "created_at": r.created_at.strftime("%Y-%m-%d") if r.created_at else "",
                "compatibility_score": 95,
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "total_meetings": total_meetings,
                "completed_meetings": completed_meetings
            })
        return jsonify({"success": True, "requests": result, "mentorships": result})

    @api_bp.route("/institution/mentorship/approval", methods=["POST"])
    @api_bp.route("/institution/mentorship_approval", methods=["POST"])
    def api_institution_mentorship_approval():
        user = get_current_user_from_req(User)
        data = request.get_json(silent=True) or request.form
        req_id = data.get("request_id") or data.get("id")
        action = (data.get("action") or data.get("status") or "approved").strip().lower()

        if not req_id:
            return jsonify({"success": False, "message": "Missing request_id"}), 400

        req = MentorshipRequest.query.get(int(req_id))
        if not req:
            return jsonify({"success": False, "message": "Request not found"}), 404

        status_val = "approved" if "approv" in action else "rejected"
        req.final_status = status_val
        req.supervisor_status = status_val
        if hasattr(req, "institution_status"):
            req.institution_status = status_val
        if hasattr(req, "updated_at"):
            req.updated_at = datetime.utcnow()

        try:
            db.session.commit()
            return jsonify({
                "success": True,
                "message": f"Mentorship request {status_val} successfully.",
                "request_id": req.id,
                "final_status": status_val
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    @api_bp.route("/institution/tasks", methods=["GET"])
    def api_get_institution_tasks():
        user, inst_obj, inst_id, inst_name, mentors, mentees = _helper_get_inst_context()
        mentee_ids = [m.id for m in mentees] if mentees else []

        if not mentee_ids and not (user and getattr(user, "user_type", None) == "0"):
            return jsonify({"success": True, "tasks": []})

        query = MenteeTask.query
        if mentee_ids:
            query = query.filter(MenteeTask.mentee_id.in_(mentee_ids))

        status_param = (request.args.get("status") or "").strip().lower()
        if status_param:
            query = query.filter(func.lower(MenteeTask.status) == status_param)

        search_query = (request.args.get("search") or "").strip().lower()
        tasks = query.order_by(MenteeTask.id.desc()).limit(100).all()
        result = []
        for t in tasks:
            if search_query and search_query not in (t.title or "").lower() and search_query not in (t.description or "").lower():
                continue
            me = User.query.get(t.mentee_id)
            mo = User.query.get(t.mentor_id) if t.mentor_id else None
            result.append({
                "id": t.id,
                "title": t.title or "Untitled Task",
                "description": t.description or "",
                "progress": t.progress if getattr(t, "progress", None) is not None else (100 if t.status in ["Done", "Completed"] else 0),
                "status": t.status or "Pending",
                "priority": getattr(t, "priority", "Medium") or "Medium",
                "due_date": t.due_date.strftime("%Y-%m-%d") if getattr(t, "due_date", None) else "",
                "created_at": t.created_at.strftime("%Y-%m-%d") if getattr(t, "created_at", None) else "",
                "mentee_id": t.mentee_id,
                "mentee_name": me.name if me else f"Mentee #{t.mentee_id}",
                "mentor_id": t.mentor_id,
                "mentor_name": mo.name if mo else "Mentor"
            })
        return jsonify({"success": True, "tasks": result})

    @api_bp.route("/institution/meetings", methods=["GET"])
    def api_get_institution_meetings():
        user, inst_obj, inst_id, inst_name, mentors, mentees = _helper_get_inst_context()
        user_ids = list(set([m.id for m in mentees] + [m.id for m in mentors] + ([user.id] if user else [])))

        query = MeetingRequest.query
        if user_ids:
            query = query.filter(or_(MeetingRequest.requester_id.in_(user_ids), MeetingRequest.requested_to_id.in_(user_ids)))
        elif not (user and getattr(user, "user_type", None) == "0"):
            return jsonify({"success": True, "meetings": []})

        meetings = query.order_by(MeetingRequest.meeting_date.desc(), MeetingRequest.meeting_time.desc()).limit(100).all()
        result = []
        now_dt = datetime.now()
        for m in meetings:
            req_u = User.query.get(m.requester_id)
            tar_u = User.query.get(m.requested_to_id)
            
            is_upcoming = True
            if m.meeting_date:
                m_dt = datetime.combine(m.meeting_date, m.meeting_time if m.meeting_time else datetime.min.time())
                is_upcoming = m_dt >= now_dt

            mentor_u = req_u if (req_u and getattr(req_u, "user_type", None) == "1") else tar_u if (tar_u and getattr(tar_u, "user_type", None) == "1") else None
            mentee_u = req_u if (req_u and getattr(req_u, "user_type", None) == "2") else tar_u if (tar_u and getattr(tar_u, "user_type", None) == "2") else None
            mp = mentor_u.mentor_profile if mentor_u and hasattr(mentor_u, "mentor_profile") else None
            ep = mentee_u.mentee_profile if mentee_u and hasattr(mentee_u, "mentee_profile") else None

            m_type = getattr(m, "meeting_type", "") or ("sgm" if (m.meeting_title or "").upper().startswith("SGM") else "standard")
            dur_val = getattr(m, "meeting_duration", None) or getattr(m, "duration", None) or 45
            dur_str = f"{dur_val} mins" if isinstance(dur_val, (int, float)) or (isinstance(dur_val, str) and dur_val.isdigit()) else str(dur_val)

            result.append({
                "id": m.id,
                "title": m.meeting_title or "Mentorship Session",
                "description": getattr(m, "meeting_description", "") or "",
                "date": m.meeting_date.strftime("%Y-%m-%d") if m.meeting_date else "",
                "time": m.meeting_time.strftime("%I:%M %p") if m.meeting_time else "",
                "duration": dur_str,
                "status": m.status or "scheduled",
                "is_upcoming": is_upcoming,
                "meeting_link": getattr(m, "meeting_link", "") or getattr(m, "meet_link", "") or "",
                "meeting_type": m_type,
                "is_sgm": m_type.lower() == "sgm" or (m.meeting_title or "").upper().startswith("SGM"),
                "requester_id": m.requester_id,
                "requester_name": req_u.name if req_u else "User",
                "requested_to_id": m.requested_to_id,
                "requested_to_name": tar_u.name if tar_u else "User",
                "other_party_name": f"{req_u.name if req_u else 'User'} & {tar_u.name if tar_u else 'User'}",
                "mentor_name": mentor_u.name if mentor_u else (tar_u.name if tar_u else "Mentor"),
                "mentor_avatar": resolve_profile_pic(mp, mentor_u) if mentor_u else "",
                "mentee_name": mentee_u.name if mentee_u else (req_u.name if req_u else "Mentee"),
                "mentee_avatar": resolve_profile_pic(ep, mentee_u) if mentee_u else ""
            })
        return jsonify({"success": True, "meetings": result})

    @api_bp.route("/institution/profile", methods=["GET", "POST", "PUT"])
    def api_institution_profile():
        user, inst_obj, inst_id, inst_name, mentors, mentees = _helper_get_inst_context()
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        if request.method == "GET":
            profile_data = {
                "id": inst_obj.id if inst_obj else user.id,
                "name": inst_name or user.name,
                "official_email": user.email,
                "contact_email": getattr(inst_obj, "contact_email", user.email) if inst_obj else user.email,
                "institution_type": getattr(inst_obj, "institution_type", "university") if inst_obj else "university",
                "email_domain": getattr(inst_obj, "email_domain", "") if inst_obj else "",
                "website": getattr(inst_obj, "website", "") if inst_obj else "",
                "contact_person": getattr(inst_obj, "contact_person", user.name) if inst_obj else user.name,
                "work_email": getattr(inst_obj, "work_email", "") if inst_obj else "",
                "personal_email": getattr(inst_obj, "personal_email", "") if inst_obj else "",
                "contact_phone": getattr(inst_obj, "contact_phone", "") if inst_obj else "",
                "address": getattr(inst_obj, "address", "") if inst_obj else "",
                "country": getattr(inst_obj, "country", "Luxembourg") if inst_obj else "Luxembourg",
                "state": getattr(inst_obj, "state", "") if inst_obj else "",
                "city": getattr(inst_obj, "city", "") if inst_obj else "",
                "logo": resolve_profile_pic(inst_obj, user),
                "status": getattr(inst_obj, "status", "active") if inst_obj else "active"
            }
            return jsonify({"success": True, "profile": profile_data})

        data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
        if not inst_obj and Institution:
            inst_obj = Institution(user_id=user.id, name=getattr(user, "institution", None) or user.name)
            db.session.add(inst_obj)

        if inst_obj:
            if "contact_person" in data:
                inst_obj.contact_person = data["contact_person"]
            if "institution_type" in data:
                inst_obj.institution_type = data["institution_type"]
            if "email_domain" in data:
                inst_obj.email_domain = data["email_domain"]
            if "website" in data:
                inst_obj.website = data["website"]
            if "work_email" in data:
                inst_obj.work_email = data["work_email"]
            if "personal_email" in data:
                inst_obj.personal_email = data["personal_email"]
            if "contact_phone" in data:
                inst_obj.contact_phone = data["contact_phone"]
            if "address" in data:
                inst_obj.address = data["address"]
            if "country" in data or "state" in data or "city" in data:
                c_val = (data.get("country") or getattr(inst_obj, "country", "") or "").strip()
                s_val = (data.get("state") or getattr(inst_obj, "state", "") or "").strip()
                ci_val = (data.get("city") or getattr(inst_obj, "city", "") or "").strip()
                if resolve_loc_func:
                    c_res, s_res, ci_res, _, _ = resolve_loc_func(country=c_val, state=s_val, city=ci_val)
                    inst_obj.country = c_res
                    inst_obj.state = s_res
                    inst_obj.city = ci_res
                else:
                    inst_obj.country = c_val or None
                    inst_obj.state = s_val or None
                    inst_obj.city = ci_val or None

        file = request.files.get("profile_picture") or request.files.get("logo")
        if file and file.filename and inst_obj:
            try:
                upload_res = storage_service.upload_file(file, folder_prefix=f"profiles/institution/{inst_obj.id}")
                if upload_res and isinstance(upload_res, dict) and upload_res.get("url"):
                    inst_obj.profile_picture = upload_res["url"]
                elif upload_res and isinstance(upload_res, str):
                    inst_obj.profile_picture = upload_res
            except Exception as e:
                logger.error(f"Error uploading institution logo: {e}")

        try:
            db.session.commit()
            return jsonify({
                "success": True,
                "message": "Institution profile updated successfully.",
                "profile": {
                    "id": inst_obj.id if inst_obj else user.id,
                    "name": inst_obj.name if inst_obj else user.name,
                    "contact_person": getattr(inst_obj, "contact_person", ""),
                    "institution_type": getattr(inst_obj, "institution_type", "university"),
                    "contact_phone": getattr(inst_obj, "contact_phone", ""),
                    "website": getattr(inst_obj, "website", ""),
                    "logo": resolve_profile_pic(inst_obj, user)
                }
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    @api_bp.route("/institution/tasks_for_mentorship", methods=["GET"])
    def api_get_tasks_for_mentorship():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        mentee_id = request.args.get("mentee_id", type=int)
        mentor_id = request.args.get("mentor_id", type=int)
        include_done = request.args.get("include_done", "0") in ("1", "true", "True")

        if not mentee_id or not mentor_id:
            return jsonify({"success": True, "tasks": []})

        if not MenteeTask:
            return jsonify({"success": True, "tasks": []})

        tasks = MenteeTask.query.filter_by(
            mentee_id=mentee_id,
            mentor_id=mentor_id
        ).all()

        task_list = []
        for t in tasks:
            if not include_done and getattr(t, 'status', None) == 'completed':
                continue
            status = getattr(t, 'status', 'pending')
            if compute_task_prog_status:
                try:
                    status = compute_task_prog_status("master", t.id, t.mentee_id, t.mentor_id)
                except Exception:
                    pass
            if not include_done and str(status).lower() in ("done", "completed"):
                continue
            master = getattr(t, 'master_task', None)
            task_list.append({
                "id": t.id,
                "meeting_number": getattr(t, 'meeting_number', 1),
                "month": getattr(t, 'month', 'Month 1'),
                "status": status,
                "due_date": t.due_date.strftime("%b %d, %Y") if getattr(t, 'due_date', None) else "",
                "purpose": master.purpose_of_call if master and getattr(master, 'purpose_of_call', None) else getattr(t, 'title', ''),
                "mentor_focus": master.mentor_focus if master and getattr(master, 'mentor_focus', None) else "",
                "mentee_focus": master.mentee_focus if master and getattr(master, 'mentee_focus', None) else ""
            })

        return jsonify({"success": True, "tasks": task_list})

    @api_bp.route("/institution/schedule_meeting", methods=["POST"])
    @api_bp.route("/institution/schedule_sgm", methods=["POST"])
    def api_institution_schedule_meeting():
        user = get_current_user_from_req(User)
        data = request.get_json(silent=True) or request.form
        title = (data.get("title") or "Mentorship Meeting").strip()
        desc = (data.get("description") or "").strip()
        mentor_id = data.get("mentor_id")
        raw_mentor_ids = data.get("mentor_ids") or []
        mentee_id = data.get("mentee_id")
        raw_mentee_ids = data.get("mentee_ids") or []
        date_str = data.get("date")
        time_str = data.get("time") or data.get("start_time")
        meeting_type = (data.get("meeting_type") or data.get("type") or "1on1").strip().lower()
        is_sgm = bool(data.get("is_sgm")) or meeting_type == "sgm" or "/schedule_sgm" in request.path
        task_id = data.get("task_id")
        platform = (data.get("platform") or "google").strip().lower()
        custom_link = (data.get("custom_link") or "").strip()
        timezone_str = (data.get("timezone") or "Asia/Kolkata").strip()
        include_institutions = bool(data.get("include_institutions"))

        if is_sgm:
            if not title.upper().startswith("SGM"):
                title = f"SGM: {title}"
            mids = []
            if mentor_id:
                mids.append(int(mentor_id))
            if isinstance(raw_mentor_ids, list):
                mids.extend([int(x) for x in raw_mentor_ids if str(x).isdigit()])
            mids = list(dict.fromkeys(mids))
            if mids:
                mentor_id = mids[0]

            eids = []
            if mentee_id:
                eids.append(int(mentee_id))
            if isinstance(raw_mentee_ids, list):
                eids.extend([int(x) for x in raw_mentee_ids if str(x).isdigit()])
            eids = list(dict.fromkeys(eids))
            if eids:
                mentee_id = eids[0]

        if not mentor_id or not mentee_id or not date_str:
            return jsonify({"success": False, "message": "Missing required fields (mentor, mentee, or date)"}), 400

        try:
            m_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            m_date = datetime.now().date()

        try:
            if time_str and ("AM" in time_str.upper() or "PM" in time_str.upper()):
                m_time = datetime.strptime(time_str.strip(), "%I:%M %p").time()
            elif time_str:
                m_time = datetime.strptime(time_str.strip(), "%H:%M").time()
            else:
                m_time = datetime.now().time()
        except Exception:
            m_time = datetime.now().time()

        # Parse duration
        duration_val = 45
        dur_str_raw = str(data.get("duration") or "45").strip().lower().replace("mins", "").replace("min", "").replace("minutes", "").strip()
        if dur_str_raw.isdigit():
            duration_val = int(dur_str_raw)

        # Generate meet link & platform resolution
        meet_link = custom_link if (platform == "custom" and custom_link) else (data.get("meet_link") or data.get("custom_link"))
        if not meet_link:
            if platform == "teams":
                meet_link = "https://teams.live.com/meet/create"
            else:
                meet_link = f"https://meet.google.com/lookup/sgm-{int(time.time())}" if is_sgm else "https://meet.google.com/new"

        mentor_obj = User.query.get(int(mentor_id))
        mentee_obj = User.query.get(int(mentee_id))
        
        full_desc = desc
        if task_id and MenteeTask:
            try:
                mentee_task = MenteeTask.query.get(int(task_id))
                if mentee_task and getattr(mentee_task, "master_task", None):
                    mt = mentee_task.master_task
                    task_ctx = (
                        f"\n\n--- Task to Discuss ---\n"
                        f"Meeting #{mentee_task.meeting_number} ({mentee_task.month})\n"
                        f"Purpose: {mt.purpose_of_call}\n"
                        f"Mentor Focus: {mt.mentor_focus}\n"
                        f"Mentee Focus: {mt.mentee_focus}\n"
                        f"Status: {mentee_task.status}"
                    )
                    full_desc = (full_desc or "") + task_ctx
            except Exception:
                pass
        if is_sgm:
            full_desc = f"Small Group Mentoring (SGM) session scheduled by Coordinator {user.name if user else 'Coordinator'}.\nLead Mentor: {mentor_obj.name if mentor_obj else mentor_id}\nInvited Students: {len(raw_mentee_ids) if raw_mentee_ids else 1}"
            if desc:
                full_desc += f"\n\nAgenda / Notes:\n{desc}"

        m = MeetingRequest(
            requester_id=user.id if user else int(mentor_id),
            requested_to_id=int(mentee_id),
            meeting_title=title,
            meeting_description=full_desc,
            meeting_date=m_date,
            meeting_time=m_time,
            meeting_duration=duration_val,
            meet_link=meet_link,
            meeting_type="sgm" if is_sgm else "1on1",
            status="scheduled"
        )
        if hasattr(m, "mentor_id"):
            m.mentor_id = int(mentor_id)
        if hasattr(m, "mentee_id"):
            m.mentee_id = int(mentee_id)

        try:
            db.session.add(m)
            db.session.flush()

            # Architecture parity with Flask: auto-assign SGM PersonalTask if SGM session
            if is_sgm and PersonalTask:
                target_mentee_ids = [int(x) for x in raw_mentee_ids if str(x).isdigit()] if raw_mentee_ids else [int(mentee_id)]
                task_due = m_date + timedelta(days=3)
                for eid in target_mentee_ids:
                    pt = PersonalTask(
                        mentee_id=eid,
                        mentor_id=int(mentor_id),
                        title=f"Learning & Feedback: {title}",
                        description=f"Reflect on discussion, summarize key learnings, and provide feedback for SGM session held on {m_date} with mentor: {mentor_obj.name if mentor_obj else 'Mentor'}.",
                        due_date=datetime.combine(task_due, datetime.min.time()),
                        priority="medium",
                        status="pending",
                        progress=0,
                        created_date=datetime.utcnow()
                    )
                    if hasattr(pt, "category"):
                        pt.category = "sgm"
                    if hasattr(pt, "sgm_meeting_id"):
                        pt.sgm_meeting_id = m.id
                    db.session.add(pt)

            db.session.commit()
            return jsonify({
                "success": True, 
                "message": f"{'SGM' if is_sgm else 'Mentorship'} meeting scheduled successfully", 
                "meeting_id": m.id,
                "meet_link": meet_link
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    @api_bp.route("/admin/metrics", methods=["GET"])
    def api_get_admin_metrics():
        total_mentors = User.query.filter_by(user_type="1").count()
        total_mentees = User.query.filter_by(user_type="2").count()
        total_sellers = User.query.filter(or_(User.user_type == "4", User.user_type == "seller", User.user_type == "partner")).count()
        active_pairs = MentorshipRequest.query.filter_by(final_status="approved").count()
        pending_requests = MentorshipRequest.query.filter_by(supervisor_status="pending").count()

        return jsonify({
            "success": True,
            "metrics": {
                "total_mentors": total_mentors,
                "total_mentees": total_mentees,
                "total_sellers": total_sellers,
                "unverified_sellers": 0,
                "active_mentorships": active_pairs,
                "pending_requests": pending_requests
            }
        })

    @api_bp.route("/admin/users", methods=["GET"])
    def api_get_admin_users():
        user_type_param = (request.args.get("type") or "").strip().lower()

        mentors = db.session.query(User, MentorProfile).outerjoin(
            MentorProfile, User.id == MentorProfile.user_id
        ).filter(or_(User.user_type == "1", User.user_type == "mentor")).all()

        mentees = db.session.query(User, MenteeProfile).outerjoin(
            MenteeProfile, User.id == MenteeProfile.user_id
        ).filter(or_(User.user_type == "2", User.user_type == "mentee")).all()

        sellers = []
        if SellerProfile:
            sellers = db.session.query(User, SellerProfile).outerjoin(
                SellerProfile, User.id == SellerProfile.user_id
            ).filter(or_(User.user_type == "4", User.user_type == "seller", User.user_type == "partner")).all()
        else:
            seller_users = User.query.filter(or_(User.user_type == "4", User.user_type == "seller", User.user_type == "partner")).all()
            sellers = [(u, None) for u in seller_users]

        m_list = []
        for u, mp in mentors:
            m_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "email": u.email,
                "profession": mp.profession if mp and mp.profession else "Mentor",
                "organisation": mp.organisation if mp and mp.organisation else "Organisation",
                "supervisor_rating": calc_mentor_rating_helper(u.id, mp, MenteeTask, db),
                "profile_picture": resolve_profile_pic(mp, u),
                "role": "Mentor",
                "created_at": u.created_at.isoformat() if u.created_at else None
            })

        me_list = []
        for u, mp in mentees:
            me_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "email": u.email,
                "institution_name": mp.institution_name if mp and mp.institution_name else "Student",
                "career_goal": mp.career_goal or mp.goal if mp else "Career Guidance",
                "profile_picture": resolve_profile_pic(mp, u),
                "role": "Mentee",
                "created_at": u.created_at.isoformat() if u.created_at else None
            })

        s_list = []
        for u, sp in sellers:
            s_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": u.name,
                "email": u.email,
                "partner_label": sp.partner_label if sp and sp.partner_label else "Partner",
                "shop_name": sp.shop_name if sp and sp.shop_name else "",
                "display_name": sp.display_name if sp else u.name,
                "is_verified": True,
                "profile_picture": resolve_profile_pic(sp, u),
                "role": "Partner",
                "created_at": u.created_at.isoformat() if u.created_at else None
            })

        institutions = []
        if Institution:
            institutions = db.session.query(User, Institution).outerjoin(
                Institution, User.id == Institution.user_id
            ).filter(or_(User.user_type == "3", User.user_type == "institution")).all()
        else:
            inst_users = User.query.filter(or_(User.user_type == "3", User.user_type == "institution")).all()
            institutions = [(u, None) for u in inst_users]

        i_list = []
        for u, inst in institutions:
            i_list.append({
                "id": u.id,
                "user_id": str(u.id),
                "name": (inst.name if inst and inst.name else None) or u.name,
                "email": u.email,
                "contact_person": inst.contact_person if inst else "",
                "contact_phone": inst.contact_phone if inst else "",
                "status": inst.status if inst else "active",
                "profile_picture": resolve_profile_pic(inst, u),
                "role": "Institution",
                "created_at": u.created_at.isoformat() if u.created_at else None
            })

        if user_type_param in ("mentors", "mentor"):
            return jsonify({"success": True, "users": m_list, "mentors": m_list, "mentees": [], "sellers": [], "institutions": []})
        elif user_type_param in ("mentees", "mentee"):
            return jsonify({"success": True, "users": me_list, "mentors": [], "mentees": me_list, "sellers": [], "institutions": []})
        elif user_type_param in ("sellers", "seller", "partner", "partners"):
            return jsonify({"success": True, "users": s_list, "mentors": [], "mentees": [], "sellers": s_list, "institutions": []})
        elif user_type_param in ("institutions", "institution"):
            return jsonify({"success": True, "users": i_list, "mentors": [], "mentees": [], "sellers": [], "institutions": i_list})

        return jsonify({
            "success": True,
            "users": m_list + me_list + s_list + i_list,
            "mentors": m_list,
            "mentees": me_list,
            "sellers": s_list,
            "institutions": i_list
        })

    @api_bp.route("/admin/requests", methods=["GET"])
    def api_get_admin_requests():
        reqs = MentorshipRequest.query.order_by(
            (MentorshipRequest.final_status == "pending").desc(),
            (MentorshipRequest.final_status == "approved").desc(),
            MentorshipRequest.created_at.desc()
        ).limit(100).all()
        result = []
        for r in reqs:
            me = User.query.get(r.mentee_id) if r.mentee_id else None
            mo = User.query.get(r.mentor_id) if r.mentor_id else None
            mp = MentorProfile.query.filter_by(user_id=r.mentor_id).first() if (MentorProfile and r.mentor_id) else None
            mep = MenteeProfile.query.filter_by(user_id=r.mentee_id).first() if (MenteeProfile and r.mentee_id) else None

            mentor_name = (mo.name if mo and mo.name else None) or f"Mentor #{r.mentor_id}"
            mentee_name = (me.name if me and me.name else None) or f"Mentee #{r.mentee_id}"

            tasks_total = MenteeTask.query.filter_by(mentee_id=r.mentee_id, mentor_id=r.mentor_id).count() if MenteeTask else 0
            tasks_completed = MenteeTask.query.filter_by(mentee_id=r.mentee_id, mentor_id=r.mentor_id, status="completed").count() if MenteeTask else 0
            meetings_total = MeetingRequest.query.filter(
                or_(
                    and_(MeetingRequest.requester_id == r.mentee_id, MeetingRequest.requested_to_id == r.mentor_id),
                    and_(MeetingRequest.requester_id == r.mentor_id, MeetingRequest.requested_to_id == r.mentee_id)
                )
            ).count() if MeetingRequest else 0
            meetings_completed = MeetingRequest.query.filter(
                or_(
                    and_(MeetingRequest.requester_id == r.mentee_id, MeetingRequest.requested_to_id == r.mentor_id),
                    and_(MeetingRequest.requester_id == r.mentor_id, MeetingRequest.requested_to_id == r.mentee_id)
                ),
                MeetingRequest.status == "approved"
            ).count() if MeetingRequest else 0

            result.append({
                "id": r.id,
                "mentee_id": r.mentee_id,
                "mentee_name": mentee_name,
                "mentee_email": me.email if me else None,
                "mentee_avatar": format_pic_url(mep.profile_picture if mep else (me.profile_picture_url if me else None)),
                "mentee_goal": getattr(mep, "goal", None) if mep else None,
                "mentee_scholarly": getattr(me, "scholarly", False) if me else False,
                "mentor_id": r.mentor_id,
                "mentor_name": mentor_name,
                "mentor_email": mo.email if mo else None,
                "mentor_avatar": format_pic_url(mp.profile_picture if mp else (mo.profile_picture_url if mo else None)),
                "mentor_profession": getattr(mp, "profession", None) if mp else None,
                "mentor_organisation": getattr(mp, "organisation", None) if mp else None,
                "mentor_premium": getattr(mo, "premium", False) if mo else False,
                "mentor_rating": getattr(r, "rating", 5.0) or 5.0,
                "purpose": r.purpose or "",
                "why_need_mentor": r.why_need_mentor or "",
                "mentor_type": r.mentor_type or "guidance",
                "duration_months": r.duration_months or 3,
                "mentor_status": r.mentor_status or "pending",
                "final_status": r.final_status or "pending",
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
                "completed_tasks": tasks_completed,
                "total_tasks": tasks_total,
                "completed_meetings": meetings_completed,
                "total_meetings": meetings_total
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

    @api_bp.route("/admin/analytics", methods=["GET"])
    def api_admin_analytics():
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        try:
            mentors = MentorProfile.query.all() if MentorProfile else []
            mentees = MenteeProfile.query.all() if MenteeProfile else []
            reqs = MentorshipRequest.query.all() if MentorshipRequest else []

            res_analytics = {}
            if get_supervisor_comparative_analytics:
                res_analytics = get_supervisor_comparative_analytics(mentors, mentees, reqs)
            else:
                try:
                    import app as app_mod
                    res_analytics = app_mod._get_supervisor_comparative_analytics(mentors, mentees, reqs)
                except Exception as e:
                    logger.error(f"Failed to compute comparative analytics: {e}")
                    res_analytics = {}

            return jsonify({
                "success": True,
                "metrics": res_analytics.get("metrics", {}),
                "lb_task_mentees": res_analytics.get("lb_task_mentees", []),
                "lb_task_mentors": res_analytics.get("lb_task_mentors", []),
                "lb_profile_mentors": res_analytics.get("lb_profile_mentors", []),
                "lb_profile_mentees": res_analytics.get("lb_profile_mentees", []),
                "lb_connected_mentors": res_analytics.get("lb_connected_mentors", []),
                "lb_mentor_ratings": res_analytics.get("lb_mentor_ratings", [])
            })
        except Exception as e:
            logger.error(f"api_admin_analytics error: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @api_bp.route("/admin/institutions", methods=["GET"])
    def api_admin_institutions():
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        if not Institution:
            return jsonify({"success": True, "institutions": []})

        institutions = Institution.query.order_by(Institution.id.asc()).all()
        users_data = db.session.query(User.user_type, User.institution_id, User.institution).filter(User.user_type.in_(["1", "2"])).all()
        active_req_data = db.session.query(User.institution_id, User.institution).join(
            MentorshipRequest, MentorshipRequest.mentee_id == User.id
        ).filter(MentorshipRequest.final_status == "approved").all()

        res_list = []
        for inst in institutions:
            inst_name_norm = (inst.name or "").strip().lower()
            mentors_count = sum(
                1 for ut, iid, iname in users_data
                if ut == "1" and (iid == inst.id or (iname and iname.strip().lower() == inst_name_norm))
            )
            mentees_count = sum(
                1 for ut, iid, iname in users_data
                if ut == "2" and (iid == inst.id or (iname and iname.strip().lower() == inst_name_norm))
            )
            active_mentorships = sum(
                1 for iid, iname in active_req_data
                if (iid == inst.id or (iname and iname.strip().lower() == inst_name_norm))
            )

            res_list.append({
                "id": inst.id,
                "user_id": inst.user_id,
                "name": inst.name or "Unnamed Institution",
                "contact_person": inst.contact_person or "",
                "contact_email": inst.contact_email or "",
                "contact_phone": inst.contact_phone or "",
                "city": inst.city or "",
                "country": inst.country or "",
                "status": inst.status or "active",
                "mentors_count": mentors_count,
                "mentees_count": mentees_count,
                "active_mentorships": active_mentorships,
                "profile_picture": format_pic_url(inst.profile_picture)
            })

        return jsonify({"success": True, "institutions": res_list})

    @api_bp.route("/admin/institutions/<int:inst_id>", methods=["GET"])
    def api_admin_institution_detail(inst_id):
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        inst = db.session.get(Institution, inst_id) if Institution else None
        if not inst:
            return jsonify({"success": False, "message": "Institution not found"}), 404

        inst_name_norm = (inst.name or "").strip().lower()
        users = User.query.filter(
            or_(
                User.institution_id == inst.id,
                func.lower(User.institution) == inst_name_norm
            )
        ).all()

        roster = []
        for u in users:
            mp = MenteeProfile.query.filter_by(user_id=u.id).first() if (MenteeProfile and u.user_type == "2") else None
            mop = MentorProfile.query.filter_by(user_id=u.id).first() if (MentorProfile and u.user_type == "1") else None
            roster.append({
                "id": u.id,
                "name": u.name or f"User #{u.id}",
                "email": u.email,
                "user_type": u.user_type,
                "role": "Mentee" if u.user_type == "2" else ("Mentor" if u.user_type == "1" else "Other"),
                "stream": getattr(mp, "stream", None) or getattr(mop, "profession", None) or "",
                "profile_picture": format_pic_url(u.profile_picture_url)
            })

        return jsonify({
            "success": True,
            "institution": {
                "id": inst.id,
                "user_id": inst.user_id,
                "name": inst.name,
                "contact_person": inst.contact_person,
                "contact_email": inst.contact_email,
                "contact_phone": inst.contact_phone,
                "city": inst.city,
                "country": inst.country,
                "status": inst.status,
                "profile_picture": format_pic_url(inst.profile_picture)
            },
            "roster": roster
        })

    @api_bp.route("/admin/special_requests", methods=["GET"])
    def api_admin_special_requests():
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        premium_list = []
        if PremiumApplication:
            p_apps = PremiumApplication.query.order_by(PremiumApplication.created_at.desc()).limit(100).all()
            for p in p_apps:
                mo = User.query.get(p.mentor_id) if p.mentor_id else None
                premium_list.append({
                    "id": p.id,
                    "mentor_id": p.mentor_id,
                    "user_id": p.mentor_id,
                    "name": mo.name if mo else f"Mentor #{p.mentor_id}",
                    "email": mo.email if mo else "",
                    "reason": p.reason or "No reason provided",
                    "status": p.status or "pending",
                    "created_at": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else ""
                })

        scholarly_list = []
        if ScholarlyApplication:
            s_apps = ScholarlyApplication.query.order_by(ScholarlyApplication.created_at.desc()).limit(100).all()
            for s in s_apps:
                me = User.query.get(s.mentee_id) if s.mentee_id else None
                scholarly_list.append({
                    "id": s.id,
                    "mentee_id": s.mentee_id,
                    "user_id": s.mentee_id,
                    "name": me.name if me else f"Mentee #{s.mentee_id}",
                    "email": me.email if me else "",
                    "reason": s.reason or "No reason provided",
                    "status": s.status or "pending",
                    "created_at": s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else ""
                })

        return jsonify({
            "success": True,
            "premium_requests": premium_list,
            "scholarly_requests": scholarly_list
        })

    @api_bp.route("/admin/special_requests/<string:req_type>/<int:req_id>/action", methods=["POST"])
    def api_admin_special_request_action(req_type, req_id):
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        data = request.get_json(silent=True) or request.form or {}
        new_status = data.get("status") or data.get("action")
        if new_status in ("accept", "accepted"):
            new_status = "approved"
        elif new_status in ("decline", "declined"):
            new_status = "rejected"

        if new_status not in ("approved", "rejected"):
            return jsonify({"success": False, "message": "Invalid status (must be approved or rejected)"}), 400

        try:
            if req_type == "premium":
                if not PremiumApplication:
                    return jsonify({"success": False, "message": "Premium application model not available"}), 503
                record = db.session.get(PremiumApplication, req_id)
                if not record:
                    return jsonify({"success": False, "message": "Premium application not found"}), 404
                record.status = new_status
                record.reviewed_at = datetime.utcnow()
                mo = User.query.get(record.mentor_id) if record.mentor_id else None
                if mo:
                    mo.premium = (new_status == "approved")
                db.session.commit()
                return jsonify({"success": True, "message": f"Premium application {new_status} successfully"})

            elif req_type == "scholarly":
                if not ScholarlyApplication:
                    return jsonify({"success": False, "message": "Scholarly application model not available"}), 503
                record = db.session.get(ScholarlyApplication, req_id)
                if not record:
                    return jsonify({"success": False, "message": "Scholarly application not found"}), 404
                record.status = new_status
                record.reviewed_at = datetime.utcnow()
                me = User.query.get(record.mentee_id) if record.mentee_id else None
                if me:
                    me.scholarly = (new_status == "approved")
                db.session.commit()
                return jsonify({"success": True, "message": f"Scholarly application {new_status} successfully"})
            else:
                return jsonify({"success": False, "message": f"Unknown request type '{req_type}'"}), 400

        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    # -------------------------------------------------------------
    # 7. NOTIFICATIONS & RESOURCE NOTES
    # -------------------------------------------------------------
    @api_bp.route("/notifications", methods=["GET"])
    def api_get_notifications():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": True, "notifications": [], "unread_count": 0})

        notifications = Notification.query.filter_by(user_id=user.id).order_by(
            Notification.created_at.desc()
        ).limit(50).all()

        unread_count = Notification.query.filter_by(user_id=user.id, is_read=False).count()

        result = []
        for n in notifications:
            result.append({
                "id": n.id,
                "message": n.message,
                "link": n.link or "",
                "is_read": bool(n.is_read),
                "created_at": n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else ""
            })
        return jsonify({"success": True, "notifications": result, "unread_count": unread_count})

    @api_bp.route("/notifications/unread_count", methods=["GET"])
    def api_get_unread_notifications_count():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": True, "unread_count": 0})
        unread_count = Notification.query.filter_by(user_id=user.id, is_read=False).count()
        return jsonify({"success": True, "unread_count": unread_count})

    @api_bp.route("/notifications/mark_all_read", methods=["POST"])
    @api_bp.route("/notifications/read_all", methods=["POST"])
    def api_mark_all_notifications_read():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404

        try:
            Notification.query.filter_by(user_id=user.id, is_read=False).update({"is_read": True})
            db.session.commit()
            return jsonify({"success": True, "message": "All notifications marked as read", "unread_count": 0})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error marking notifications as read: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @api_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
    def api_mark_notification_read(notification_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404

        try:
            notif = Notification.query.filter_by(id=notification_id, user_id=user.id).first()
            if notif:
                notif.is_read = True
                db.session.commit()
            unread_count = Notification.query.filter_by(user_id=user.id, is_read=False).count()
            return jsonify({"success": True, "unread_count": unread_count})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error marking single notification read: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @api_bp.route("/resources", methods=["GET"])
    def api_get_resources():
        """Returns standard mentor and mentee guidebook notes."""
        resource_items = [
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
        return jsonify({
            "success": True,
            "notes": resource_items,
            "resources": resource_items
        })

    # -------------------------------------------------------------
    # 10. SELLER, QR CODE & COUPON ENDPOINTS
    # -------------------------------------------------------------
    COUPON_CODE_ALPHABET = "ABCDEFGHJKLMNPQRTUVWXYZ23456789"
    COUPON_CODE_GROUPS = 2
    COUPON_CODE_GROUP_LEN = 6
    COUPON_CODE_PREFIX = "WES"
    PARTNER_LABELS = [
        "Partner", "Outreach Partner", "Retail Partner",
        "Vendor", "Shop Owner", "Market Partner"
    ]
    BUSINESS_CATEGORIES = [
        "Retail", "Food & Beverage", "Education & Books", "Services", "Wholesale / Market stall",
        "Technology", "Health & Wellness", "Other",
    ]

    def _api_seller_completion(profile):
        if profile is None:
            return 0, []
        shop_count = getattr(profile, "shop_count", None)
        shops = []
        if SellerShop and getattr(profile, "user_id", None):
            shops = SellerShop.query.filter_by(seller_user_id=profile.user_id).order_by(SellerShop.id.asc()).all()
        shops_complete = False
        if shop_count and shop_count >= 1:
            if shop_count > 1:
                shops_complete = len(shops) >= shop_count
            else:
                shops_complete = True

        checks = [
            ("Profile picture", bool(getattr(profile, "profile_picture", None))),
            ("Partner type", bool(getattr(profile, "partner_label", None))),
            ("Shop name", bool((getattr(profile, "shop_name", None) or "").strip())),
            ("Description", bool((getattr(profile, "description", None) or "").strip())),
            ("Business category", bool(getattr(profile, "business_category", None))),
            ("Number of shops", bool(shop_count and shop_count >= 1)),
            ("All shop names", shops_complete),
            ("Contact phone", bool((getattr(profile, "contact_phone", None) or "").strip())),
            ("Address", bool((getattr(profile, "address", None) or "").strip())),
            ("City", bool((getattr(profile, "city", None) or "").strip())),
            ("Country", bool((getattr(profile, "country", None) or "").strip())),
        ]
        done = sum(1 for _, ok in checks if ok)
        return int(round(done * 100 / len(checks))), [label for label, ok in checks if not ok]


    def _api_generate_coupon_code():
        if not MentorCoupon:
            return f"{COUPON_CODE_PREFIX}-{secrets.token_hex(8).upper()}"
        for _ in range(20):
            groups = [
                ''.join(secrets.choice(COUPON_CODE_ALPHABET) for _ in range(COUPON_CODE_GROUP_LEN))
                for _ in range(COUPON_CODE_GROUPS)
            ]
            suffix = ''.join(secrets.choice(COUPON_CODE_ALPHABET) for _ in range(3))
            code = f"{COUPON_CODE_PREFIX}-" + "-".join(groups) + f"-{suffix}"
            if not MentorCoupon.query.filter_by(code=code).first():
                return code
        return f"{COUPON_CODE_PREFIX}-{secrets.token_hex(8).upper()}-{secrets.token_hex(2).upper()[:3]}"

    def _api_public_base_url():
        configured = os.environ.get("COUPON_PUBLIC_BASE_URL", "").strip()
        if configured:
            return configured.rstrip("/")
        if os.environ.get("PRODUCTION"):
            return "https://mentorship.weslux.lu"
        try:
            return request.host_url.rstrip("/")
        except Exception:
            return "https://mentorship.weslux.lu"

    def _api_coupon_qr_png(target_url, box_size=8, border=4):
        try:
            import qrcode as _qrcode_lib
            qr = _qrcode_lib.QRCode(
                version=1,
                error_correction=_qrcode_lib.constants.ERROR_CORRECT_M,
                box_size=box_size,
                border=border,
            )
            qr.add_data(target_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#1e40af", back_color="#ffffff")
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            return buf
        except Exception as e:
            try:
                from qr_code_lib import QRCode as LocalQRCode
                png_bytes = LocalQRCode(target_url, error_correction='M').to_png(
                    box_size=box_size, border=border)
                buf = io.BytesIO(png_bytes)
                buf.seek(0)
                return buf
            except Exception as e2:
                logger.error(f"Failed to generate QR: {e2}")
                return None

    def _ensure_seller_profile_obj(user):
        if not user or not SellerProfile:
            return None
        sp = SellerProfile.query.filter_by(user_id=user.id).first()
        if not sp:
            sp = SellerProfile(
                user_id=user.id,
                partner_label="Partner",
                shop_name=user.name,
                is_verified=True
            )
            db.session.add(sp)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                sp = SellerProfile.query.filter_by(user_id=user.id).first()
        return sp

    @api_bp.route("/sellers/verified", methods=["GET"])
    @api_bp.route("/sellers", methods=["GET"])
    def api_get_verified_sellers():
        if not SellerProfile:
            return jsonify({"success": True, "sellers": []})
        seller_users = User.query.filter(or_(User.user_type == "4", User.user_type == "seller", User.user_type == "partner")).all()
        for u in seller_users:
            if not SellerProfile.query.filter_by(user_id=u.id).first():
                sp = SellerProfile(user_id=u.id, partner_label="Partner", shop_name=u.name, is_verified=True)
                db.session.add(sp)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        profiles = SellerProfile.query.all()
        result = []
        for sp in profiles:
            result.append({
                "id": sp.id,
                "user_id": sp.user_id,
                "display_name": sp.display_name,
                "partner_label": sp.partner_label or "Partner",
                "shop_name": sp.shop_name or "",
                "market_name": sp.market_name or "",
                "contact_phone": sp.contact_phone or "",
                "address": sp.address or "",
                "is_verified": True,
                "user_name": sp.user.name if sp.user else "",
                "user_email": sp.user.email if sp.user else ""
            })
        return jsonify({"success": True, "sellers": result})

    @api_bp.route("/admin/sellers", methods=["GET"])
    def api_get_admin_sellers():
        user = get_current_user_from_req(User)
        if not user or str(getattr(user, "user_type", "")) != "0":
            return jsonify({"success": False, "message": "Admin privileges required"}), 403
        if not SellerProfile:
            return jsonify({"success": True, "sellers": []})
        seller_users = User.query.filter(or_(User.user_type == "4", User.user_type == "seller", User.user_type == "partner")).all()
        for u in seller_users:
            if not SellerProfile.query.filter_by(user_id=u.id).first():
                sp = SellerProfile(user_id=u.id, partner_label="Partner", shop_name=u.name, is_verified=True)
                db.session.add(sp)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        profiles = SellerProfile.query.all()
        result = []
        for sp in profiles:
            u = sp.user or User.query.get(sp.user_id)
            redeemed_count = 0
            if MentorCoupon:
                redeemed_count = MentorCoupon.query.filter_by(seller_id=sp.user_id).filter(MentorCoupon.used_at.isnot(None)).count()
            result.append({
                "id": sp.id,
                "user_id": sp.user_id,
                "name": u.name if u else "",
                "email": u.email if u else "",
                "display_name": sp.display_name,
                "partner_label": sp.partner_label or "Partner",
                "shop_name": sp.shop_name or "",
                "market_name": sp.market_name or "",
                "contact_phone": sp.contact_phone or "",
                "address": sp.address or "",
                "is_verified": True,
                "verified_at": sp.verified_at.isoformat() if getattr(sp, "verified_at", None) else None,
                "redeemed_count": redeemed_count
            })
        return jsonify({"success": True, "sellers": result})

    @api_bp.route("/seller/profile", methods=["GET", "POST"])
    def api_seller_profile():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Authentication required"}), 401

        if str(getattr(user, "user_type", "")) not in ("4", "0"):
            return jsonify({"success": False, "message": "Partner privileges required"}), 403

        seller_id_param = request.args.get("seller_id") or (request.is_json and request.json.get("seller_id"))
        if seller_id_param and str(seller_id_param).isdigit():
            target_id = int(seller_id_param)
            if target_id != user.id and str(getattr(user, "user_type", "")) != "0":
                return jsonify({"success": False, "message": "Permission denied"}), 403
            seller = User.query.get(target_id)
        else:
            seller = user

        if not seller:
            return jsonify({"success": False, "message": "Partner account not found"}), 404

        sp = _ensure_seller_profile_obj(seller)

        if request.method == "POST":
            data = request.get_json(silent=True) or request.form or {}
            label = (data.get("partner_label") or "Partner").strip()
            if label in PARTNER_LABELS:
                sp.partner_label = label

            sp.shop_name = (data.get("shop_name") or "").strip() or None
            sp.market_name = (data.get("market_name") or "").strip() or None
            sp.contact_phone = (data.get("contact_phone") or "").strip() or None
            sp.address = (data.get("address") or "").strip() or None

            # Parity fields from Flask seller_profile.html
            if "description" in data:
                sp.description = (data.get("description") or "").strip()[:1000] or None
            if "business_category" in data:
                cat = (data.get("business_category") or "").strip()
                sp.business_category = cat if cat in BUSINESS_CATEGORIES else None
            if "country" in data or "state" in data or "city" in data:
                c_val = (data.get("country") or sp.country or "").strip()
                s_val = (data.get("state") or getattr(sp, "state", None) or "").strip()
                ci_val = (data.get("city") or sp.city or "").strip()
                if resolve_loc_func:
                    c_res, s_res, ci_res, _, _ = resolve_loc_func(country=c_val, state=s_val, city=ci_val)
                    sp.country = c_res or c_val or None
                    sp.state = s_res or s_val or None
                    sp.city = ci_res or ci_val or None
                else:
                    sp.country = c_val or None
                    sp.state = s_val or None
                    sp.city = ci_val or None
            if "website" in data:
                sp.website = (data.get("website") or "").strip()[:255] or None

            if "shop_count" in data:
                try:
                    sc = int(data.get("shop_count") or 1)
                    sp.shop_count = max(1, min(sc, 50))
                except (ValueError, TypeError):
                    pass

            if "profile_picture" in data:
                pic_val = data.get("profile_picture")
                if pic_val and isinstance(pic_val, str) and pic_val.strip():
                    sp.profile_picture = pic_val.strip()

            # Handle file upload if multipart
            if request.files.get("profile_picture") or request.files.get("file"):
                pic_file = request.files.get("profile_picture") or request.files.get("file")
                if pic_file and pic_file.filename:
                    url, stored_name = storage_service.upload_file(pic_file, folder_prefix=f"sellers/{seller.id}")
                    if stored_name:
                        sp.profile_picture = stored_name

            # Synchronize multiple shops (SellerShop)
            shops_input = data.get("shops")
            shop_names = data.get("shop_names") or request.form.getlist("shop_names")
            shop_addresses = data.get("shop_addresses") or request.form.getlist("shop_addresses")

            if SellerShop:
                if shops_input and isinstance(shops_input, list):
                    existing = {sh.name.lower(): sh for sh in SellerShop.query.filter_by(seller_user_id=seller.id).all()}
                    keep = set()
                    for item in shops_input:
                        if isinstance(item, dict):
                            nm = (item.get("name") or "").strip()[:200]
                            addr = (item.get("address") or "").strip() or None
                            if not nm:
                                continue
                            if nm.lower() in existing:
                                existing[nm.lower()].address = addr
                            else:
                                sh = SellerShop(seller_user_id=seller.id, name=nm, address=addr)
                                db.session.add(sh)
                            keep.add(nm.lower())
                    for k, sh in existing.items():
                        if k not in keep:
                            if MentorCoupon and MentorCoupon.query.filter_by(used_shop_id=sh.id).first():
                                continue
                            db.session.delete(sh)
                elif shop_names and isinstance(shop_names, list):
                    existing = {sh.name.lower(): sh for sh in SellerShop.query.filter_by(seller_user_id=seller.id).all()}
                    keep = set()
                    for i, nm in enumerate(shop_names):
                        nm = (nm or "").strip()[:200]
                        if not nm:
                            continue
                        addr = (shop_addresses[i] or "").strip() if i < len(shop_addresses) else None
                        if nm.lower() in existing:
                            existing[nm.lower()].address = addr
                        else:
                            sh = SellerShop(seller_user_id=seller.id, name=nm, address=addr)
                            db.session.add(sh)
                        keep.add(nm.lower())
                    for k, sh in existing.items():
                        if k not in keep:
                            if MentorCoupon and MentorCoupon.query.filter_by(used_shop_id=sh.id).first():
                                continue
                            db.session.delete(sh)

            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return jsonify({"success": False, "message": f"Update failed: {str(e)}"}), 500

            completion, missing = _api_seller_completion(sp)
            shops_list = []
            if SellerShop:
                s_rows = SellerShop.query.filter_by(seller_user_id=seller.id).order_by(SellerShop.id.asc()).all()
                shops_list = [{"id": s.id, "name": s.name, "address": s.address or ""} for s in s_rows]

            prof_dict = sp.to_dict() if sp else {}
            prof_dict["completion"] = completion
            prof_dict["missing"] = missing
            prof_dict["shops"] = shops_list
            prof_dict["profile_picture"] = format_pic_url(sp.profile_picture) if sp and sp.profile_picture else ""

            return jsonify({
                "success": True,
                "message": "Partner profile updated successfully.",
                "profile": prof_dict,
                "completion": completion,
                "missing": missing,
                "shops": shops_list
            })

        completion, missing = _api_seller_completion(sp)
        shops_list = []
        if SellerShop and sp:
            s_rows = SellerShop.query.filter_by(seller_user_id=seller.id).order_by(SellerShop.id.asc()).all()
            shops_list = [{"id": s.id, "name": s.name, "address": s.address or ""} for s in s_rows]

        prof_dict = sp.to_dict() if sp else {}
        prof_dict["completion"] = completion
        prof_dict["missing"] = missing
        prof_dict["shops"] = shops_list
        prof_dict["profile_picture"] = format_pic_url(sp.profile_picture) if sp and sp.profile_picture else ""

        return jsonify({
            "success": True,
            "profile": prof_dict,
            "partner_labels": PARTNER_LABELS,
            "business_categories": BUSINESS_CATEGORIES,
            "completion": completion,
            "missing": missing,
            "shops": shops_list
        })

    @api_bp.route("/seller/dashboard", methods=["GET"])
    def api_get_seller_dashboard():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Authentication required"}), 401

        if str(getattr(user, "user_type", "")) not in ("4", "0"):
            return jsonify({"success": False, "message": "Partner privileges required"}), 403

        seller_id_param = request.args.get("seller_id")
        if seller_id_param and str(seller_id_param).isdigit():
            target_id = int(seller_id_param)
            if target_id != user.id and str(getattr(user, "user_type", "")) != "0":
                return jsonify({"success": False, "message": "Permission denied"}), 403
            seller = User.query.get(target_id)
        else:
            seller = user

        if not seller:
            return jsonify({"success": False, "message": "Partner not identified"}), 404

        sp = _ensure_seller_profile_obj(seller)

        window = (request.args.get("window") or "all").lower()
        since_param = request.args.get("since")
        now = datetime.utcnow()
        cutoff = None
        if since_param:
            try:
                cutoff = datetime.strptime(since_param.strip(), "%Y-%m-%d")
            except Exception:
                cutoff = None

        if cutoff is None:
            if window in ("today", "day", "1d"):
                cutoff = datetime(now.year, now.month, now.day)
            elif window in ("week", "7d"):
                from datetime import timedelta
                cutoff = now - timedelta(days=7)
            elif window in ("month", "30d"):
                from datetime import timedelta
                cutoff = now - timedelta(days=30)
            elif window in ("90d", "quarter", "3m"):
                from datetime import timedelta
                cutoff = now - timedelta(days=90)

        query = MentorCoupon.query.filter(MentorCoupon.seller_id == seller.id, MentorCoupon.used_at.isnot(None)) if MentorCoupon else None
        if query is not None and cutoff is not None:
            query = query.filter(MentorCoupon.used_at >= cutoff)

        rows = query.order_by(MentorCoupon.used_at.desc()).all() if query is not None else []
        lifetime = MentorCoupon.query.filter(MentorCoupon.seller_id == seller.id, MentorCoupon.used_at.isnot(None)).count() if MentorCoupon else 0

        entries = []
        by_discount = {}
        for c in rows:
            r_user = db.session.get(User, c.redeemed_by_user_id) if c.redeemed_by_user_id else None
            role = "Mentor" if r_user and str(r_user.user_type) == "1" else "Mentee"
            label = c.discount_label or "Standard Discount"
            by_discount[label] = by_discount.get(label, 0) + 1
            is_gen = True
            if hasattr(c, "partner_user_id") and c.partner_user_id:
                is_gen = False
            entries.append({
                "id": c.id,
                "code": c.code,
                "title": c.title,
                "description": c.description or "",
                "discount_label": label,
                "used_at": c.used_at.isoformat() if c.used_at else None,
                "redeemer_name": r_user.name if r_user else "Member",
                "redeemer_email": r_user.email if r_user else "",
                "redeemer_role": role,
                "is_general": is_gen,
                "shop_name": getattr(c, "used_shop_name", ""),
                "issued_by": (c.mentor.name if getattr(c, "mentor", None) else "WES Supervisor"),
                "expires_at": c.expires_at.isoformat() if getattr(c, "expires_at", None) else None
            })

        referral_rows = []
        if SellerReferral:
            refs = SellerReferral.query.filter_by(seller_id=seller.id).order_by(SellerReferral.created_at.desc()).all()
            for r in refs:
                person = r.user
                if not person:
                    continue
                pct = 100
                if compute_profile_completeness:
                    try:
                        pct = int(compute_profile_completeness(person.id, str(person.user_type)) or 0)
                    except Exception:
                        pct = 0
                role = "Mentor" if str(person.user_type) == "1" else "Mentee"
                referral_rows.append({
                    "id": r.id,
                    "name": person.name,
                    "email": person.email,
                    "role": role,
                    "status": r.status,
                    "account_created": person.created_at.isoformat() if person.created_at else None,
                    "completion": pct,
                    "eligible": r.status == "confirmed" and pct >= 90
                })

        return jsonify({
            "success": True,
            "seller": {
                "id": seller.id,
                "name": seller.name,
                "email": seller.email,
                "display_name": sp.display_name if sp else seller.name,
                "is_verified": True,
                "partner_label": sp.partner_label if sp else "Partner"
            },
            "stats": {
                "redeemed": len(entries),
                "lifetime": lifetime,
                "filter_window": window,
                "filter_label": "All time" if window == "all" else window,
                "distinct_offers": len(by_discount),
                "referrals_total": len(referral_rows),
                "referrals_pending": sum(1 for r in referral_rows if r["status"] == "pending"),
                "completion": _api_seller_completion(sp)[0],
                "missing": _api_seller_completion(sp)[1],
                "profile_complete": _api_seller_completion(sp)[0] >= 90
            },
            "by_discount": [{"label": k, "count": v} for k, v in by_discount.items()],
            "entries": entries,
            "referrals": referral_rows
        })

    @api_bp.route("/seller/referrals/<int:referral_id>/respond", methods=["POST"])
    def api_seller_respond_referral(referral_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Authentication required"}), 401
        if not SellerReferral:
            return jsonify({"success": False, "message": "Referral service unavailable"}), 503

        referral = SellerReferral.query.filter_by(id=referral_id, seller_id=user.id).first()
        if not referral:
            return jsonify({"success": False, "message": "Referral record not found"}), 404

        data = request.get_json(silent=True) or request.form or {}
        decision = (data.get("decision") or "").strip().lower()
        if decision not in ("confirm", "deny"):
            return jsonify({"success": False, "message": "Decision must be 'confirm' or 'deny'"}), 400

        if referral.status != "pending":
            return jsonify({"success": False, "message": "You have already responded to this referral."}), 409

        referral.status = "confirmed" if decision == "confirm" else "denied"
        referral.responded_at = datetime.utcnow()
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": f"Database error: {str(e)}"}), 500

        # Send admin notification if email helper available
        import sys
        send_fn = getattr(sys.modules.get('__main__'), 'send_email_reminder', None) or getattr(sys.modules.get('app'), 'send_email_reminder', None)
        if send_fn:
            try:
                person = referral.user
                role = "Mentor" if str(person.user_type) == "1" else "Mentee"
                verb = "confirmed" if decision == "confirm" else "denied"
                for admin in User.query.filter_by(user_type="0").all():
                    if admin.email:
                        send_fn(
                            admin.email,
                            f"Referral {verb}: {person.name}",
                            f"<p>Partner <strong>{user.name}</strong> {verb} that {role} <strong>{person.name}</strong> was referred by them.</p>"
                        )
            except Exception as e:
                logger.warning(f"Failed to send referral email: {e}")

        return jsonify({
            "success": True,
            "message": f"Referral successfully {referral.status}.",
            "referral": {
                "id": referral.id,
                "status": referral.status,
                "responded_at": referral.responded_at.isoformat() if referral.responded_at else None
            }
        })

    @api_bp.route("/coupons/my_coupons", methods=["GET"])
    def api_get_my_coupons():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        coupons = []
        seen_ids = set()
        if CouponAssignment:
            assignments = CouponAssignment.query.filter_by(user_id=user.id).order_by(CouponAssignment.id.desc()).all()
            for a in assignments:
                if a.coupon and a.coupon.id not in seen_ids:
                    coupons.append(a.coupon)
                    seen_ids.add(a.coupon.id)

        if MentorCoupon:
            legacy = MentorCoupon.query.filter_by(mentor_id=user.id).order_by(MentorCoupon.id.desc()).all()
            for c in legacy:
                if c.id not in seen_ids:
                    coupons.append(c)
                    seen_ids.add(c.id)

        all_coupons = []
        active_coupons = []
        redeemed_coupons = []
        inactive_coupons = []

        base_url = _api_public_base_url()

        for c in coupons:
            if c.status == "active" and getattr(c, "is_expired", False):
                c.status = "expired"
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        for c in coupons:
            c_dict = {
                "id": c.id,
                "code": c.code,
                "title": c.title,
                "description": c.description or "",
                "discount_label": c.discount_label or "",
                "status": c.status,
                "is_usable": getattr(c, "is_usable", c.status == "active" and not getattr(c, "is_expired", False)),
                "is_expired": getattr(c, "is_expired", False),
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "expires_at": c.expires_at.isoformat() if c.expires_at else None,
                "used_at": c.used_at.isoformat() if c.used_at else None,
                "used_by": c.used_by or "",
                "seller_name": getattr(c, "seller_display_name", c.used_by or ""),
                "redeemed_by_name": c.redeemed_by.name if getattr(c, "redeemed_by", None) else "",
                "verification_count": c.verification_count or 0,
                "verify_url": f"{base_url}/coupon/verify/{c.code}",
                "qr_url": f"/api/coupons/{c.code}/qr"
            }
            all_coupons.append(c_dict)
            if c.status == "used":
                redeemed_coupons.append(c_dict)
            elif c.status == "active" and not getattr(c, "is_expired", False):
                active_coupons.append(c_dict)
            else:
                inactive_coupons.append(c_dict)

        my_requests = []
        if CouponRequest:
            req_rows = CouponRequest.query.filter_by(user_id=user.id).order_by(CouponRequest.created_at.desc()).all()
            my_requests = [r.to_dict() for r in req_rows]

        stats = {
            "total": len(all_coupons),
            "active": len(active_coupons),
            "redeemed": len(redeemed_coupons),
            "inactive": len(inactive_coupons),
            "pending_requests": sum(1 for r in my_requests if r["status"] == "pending")
        }

        return jsonify({
            "success": True,
            "coupons": all_coupons,
            "active_coupons": active_coupons,
            "redeemed_coupons": redeemed_coupons,
            "inactive_coupons": inactive_coupons,
            "requests": my_requests,
            "stats": stats
        })

    @api_bp.route("/coupons/request", methods=["POST"])
    def api_post_coupon_request():
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) not in ("1", "2"):
            return jsonify({"success": False, "message": "Only mentors and mentees can request coupons."}), 403

        if not CouponRequest:
            return jsonify({"success": False, "message": "Coupon request service unavailable"}), 503

        data = request.get_json(silent=True) or request.form or {}
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"success": False, "message": "Please give your request a title."}), 400

        quantity = 1
        try:
            quantity = max(1, min(200, int(data.get("quantity") or 1)))
        except (TypeError, ValueError):
            quantity = 1

        req_obj = CouponRequest(
            user_id=user.id,
            title=title,
            description=(data.get("description") or "").strip() or None,
            discount_label=(data.get("discount_label") or "").strip() or None,
            quantity=quantity,
            status="pending"
        )
        db.session.add(req_obj)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

        return jsonify({
            "success": True,
            "message": "Your coupon request has been submitted to the administration.",
            "request": req_obj.to_dict()
        })

    @api_bp.route("/coupons/<string:code>/qr", methods=["GET"])
    def api_get_coupon_qr(code):
        code = (code or "").strip().upper()
        if not MentorCoupon:
            return jsonify({"success": False, "message": "Coupon service unavailable"}), 503

        coupon = MentorCoupon.query.filter_by(code=code).first()
        if not coupon:
            return jsonify({"success": False, "message": "Coupon not found"}), 404

        target_url = f"{_api_public_base_url()}/coupon/verify/{coupon.code}"
        box_size = 10 if request.args.get("size") == "large" else 7
        buf = _api_coupon_qr_png(target_url, box_size=box_size)
        if not buf:
            return jsonify({"success": False, "message": "Failed to generate QR code"}), 500

        response = send_file(buf, mimetype="image/png")
        response.headers['Cache-Control'] = 'no-store'
        return response

    @api_bp.route("/coupons/verify/<string:code>", methods=["GET"])
    def api_get_coupon_verify_details(code):
        code = (code or "").strip().upper()
        if not MentorCoupon:
            return jsonify({"success": False, "message": "Coupon service unavailable"}), 503

        coupon = MentorCoupon.query.filter_by(code=code).first()
        if not coupon:
            return jsonify({"success": False, "message": "Coupon not found"}), 404

        if coupon.status == "active" and getattr(coupon, "is_expired", False):
            coupon.status = "expired"
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        verified_sellers = []
        if SellerProfile:
            vs_list = SellerProfile.query.all()
            for sp in vs_list:
                verified_sellers.append({
                    "id": sp.id,
                    "user_id": sp.user_id,
                    "display_name": sp.display_name,
                    "partner_label": sp.partner_label or "Partner",
                    "shop_name": sp.shop_name or ""
                })

        candidates = []
        assignees = getattr(coupon, "assignees", [])
        if not assignees and coupon.mentor:
            assignees = [coupon.mentor]
        for u in assignees:
            candidates.append({
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "role": "Mentor" if str(u.user_type) == "1" else "Mentee"
            })

        current_user = get_current_user_from_req(User)
        my_profile = None
        shops = []
        can_redeem = False
        reserved_for_other = False

        if current_user and str(getattr(current_user, "user_type", "")) == "4" and SellerProfile:
            sp = SellerProfile.query.filter_by(user_id=current_user.id).first()
            if sp:
                my_profile = {
                    "id": sp.id,
                    "user_id": sp.user_id,
                    "display_name": sp.display_name,
                    "partner_label": sp.partner_label or "Partner",
                    "shop_count": sp.shop_count or 1
                }
                if SellerShop:
                    s_rows = SellerShop.query.filter_by(seller_user_id=sp.user_id).order_by(SellerShop.id.asc()).all()
                    shops = [{"id": s.id, "name": s.name, "address": s.address or ""} for s in s_rows]

                if getattr(coupon, "partner_user_id", None) and coupon.partner_user_id != current_user.id:
                    reserved_for_other = True
                    can_redeem = False
                elif coupon.status == "active" and not getattr(coupon, "is_expired", False):
                    can_redeem = True

        return jsonify({
            "success": True,
            "coupon": {
                "id": coupon.id,
                "code": coupon.code,
                "title": coupon.title,
                "description": coupon.description or "",
                "discount_label": coupon.discount_label or "",
                "status": coupon.status,
                "is_usable": getattr(coupon, "is_usable", coupon.status == "active"),
                "is_expired": getattr(coupon, "is_expired", False),
                "used_at": coupon.used_at.isoformat() if coupon.used_at else None,
                "used_by": coupon.used_by or "",
                "seller_name": getattr(coupon, "seller_display_name", coupon.used_by or ""),
                "redeemed_by_name": coupon.redeemed_by.name if getattr(coupon, "redeemed_by", None) else "",
                "expires_at": coupon.expires_at.isoformat() if getattr(coupon, "expires_at", None) else None,
                "partner_user_id": getattr(coupon, "partner_user_id", None)
            },
            "verified_sellers": verified_sellers,
            "candidates": candidates,
            "my_profile": my_profile,
            "shops": shops,
            "can_redeem": can_redeem,
            "reserved_for_other": reserved_for_other
        })

    @api_bp.route("/coupons/verify/<string:code>", methods=["POST"])
    def api_post_coupon_verify(code):
        code = (code or "").strip().upper()
        if not MentorCoupon:
            return jsonify({"success": False, "message": "Coupon service unavailable"}), 503

        coupon = MentorCoupon.query.filter_by(code=code).first()
        if not coupon:
            return jsonify({"success": False, "message": "Coupon not found"}), 404

        if coupon.status == "used":
            return jsonify({"success": False, "message": "This coupon has already been used."}), 409
        if coupon.status == "revoked":
            return jsonify({"success": False, "message": "This coupon has been withdrawn."}), 409
        if getattr(coupon, "is_expired", False):
            coupon.status = "expired"
            db.session.commit()
            return jsonify({"success": False, "message": "This coupon has expired."}), 410

        data = request.get_json(silent=True) or {}
        # Only a signed-in partner can redeem. Anyone else can only view the coupon.
        api_user = get_current_user_from_req(User)
        if not api_user or str(api_user.user_type) != "4":
            return jsonify({"success": False,
                            "message": "Only the partner can redeem this coupon. "
                                       "Please sign in with a partner account."}), 403
        seller_profile = SellerProfile.query.filter_by(user_id=api_user.id).first() if SellerProfile else None
        if not seller_profile:
            return jsonify({"success": False, "message": "Partner profile not found."}), 400

        assignees = getattr(coupon, "assignees", [])
        if not assignees and coupon.mentor:
            assignees = [coupon.mentor]

        # Coupons reserved for one Outreach Partner can only be redeemed by them.
        if getattr(coupon, "partner_user_id", None) and seller_profile.user_id != coupon.partner_user_id:
            return jsonify({"success": False, "message": "This coupon is reserved for a different partner."}), 403

        # Partners with several shops must say which one the coupon was used at.
        used_shop_id = None
        if (getattr(seller_profile, "shop_count", None) or 1) > 1:
            from sqlalchemy import text as _sqltext
            shop_rows = db.session.execute(
                _sqltext("SELECT id FROM seller_shops WHERE seller_user_id = :u"),
                {"u": seller_profile.user_id}).fetchall()
            shop_ids = {r[0] for r in shop_rows}
            raw_shop = str(data.get("shop_id") or "").strip()
            if not shop_ids:
                return jsonify({"success": False, "message": "This partner has not finished setting up their shops yet."}), 400
            if not raw_shop.isdigit() or int(raw_shop) not in shop_ids:
                return jsonify({"success": False, "message": "Please choose which shop the coupon is being used at."}), 400
            used_shop_id = int(raw_shop)

        # Each key belongs to one person, so the redeemer is that holder.
        redeemer = assignees[0] if assignees else User.query.get(coupon.mentor_id)
        if not redeemer:
            return jsonify({"success": False, "message": "This coupon has not been assigned to anyone yet."}), 400

        # Purchase total -> the coupon value WES owes the partner (same maths as the web page).
        import sys as _sys
        _app_mod = _sys.modules.get('__main__') if hasattr(_sys.modules.get('__main__'), '_money') else _sys.modules.get('app')
        _money_fn = getattr(_app_mod, '_money', None)
        _calc_fn = getattr(_app_mod, '_compute_coupon_discount', None)
        _cur_fn = getattr(_app_mod, '_currency_code_from_label', None)
        if _money_fn:
            goods = _money_fn(data.get("goods_total"))
            if goods is None or goods <= 0:
                return jsonify({"success": False, "message": "Please enter the total amount of goods purchased."}), 400
            coupon.goods_total = goods
            coupon.goods_currency = (str(data.get("goods_currency") or (_cur_fn(coupon.discount_label) if _cur_fn else None) or "EUR")).upper()[:8]
            coupon.discount_amount = _calc_fn(coupon.discount_label, goods) if _calc_fn else None
            coupon.refunded = False

        coupon.status = "used"
        coupon.used_at = datetime.utcnow()
        coupon.seller_id = seller_profile.user_id
        coupon.redeemed_by_user_id = redeemer.id
        coupon.used_by = seller_profile.display_name
        if used_shop_id:
            coupon.used_shop_id = used_shop_id
        coupon.verification_count = (coupon.verification_count or 0) + 1

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": f"Verification error: {str(e)}"}), 500

        import sys
        send_fn = getattr(sys.modules.get('__main__'), 'send_email_reminder', None) or getattr(sys.modules.get('app'), 'send_email_reminder', None)
        if send_fn:
            role = "Mentor" if str(redeemer.user_type) == "1" else "Mentee"
            when = coupon.used_at.strftime("%d %B %Y at %H:%M UTC") if coupon.used_at else "just now"
            html = f"""
            <div style="font-family:sans-serif;max-width:560px;margin:auto;">
                <h2 style="color:#0f172a;">Coupon Successfully Redeemed</h2>
                <p>The following coupon has been verified and used:</p>
                <ul>
                    <li><strong>Code:</strong> {coupon.code}</li>
                    <li><strong>Offer:</strong> {coupon.title}</li>
                    <li><strong>Discount:</strong> {coupon.discount_label or '-'}</li>
                    <li><strong>Redeemed by:</strong> {redeemer.name} ({role})</li>
                    <li><strong>Redeemed at:</strong> {seller_profile.display_name}</li>
                    <li><strong>Date/Time:</strong> {when}</li>
                </ul>
            </div>
            """
            try:
                if redeemer.email:
                    send_fn(redeemer.email, f"Coupon Redeemed: {coupon.code}", html)
                seller_user = User.query.get(seller_profile.user_id)
                if seller_user and seller_user.email:
                    send_fn(seller_user.email, f"Coupon Verification Confirmation: {coupon.code}", html)
            except Exception as e:
                logger.warning("Failed to send coupon redemption email: %s", e)

        return jsonify({
            "success": True,
            "message": "Coupon successfully verified and marked as redeemed.",
            "coupon": {
                "id": coupon.id,
                "code": coupon.code,
                "title": coupon.title,
                "discount_label": coupon.discount_label or "",
                "status": coupon.status,
                "used_at": coupon.used_at.isoformat() if coupon.used_at else None,
                "used_by": coupon.used_by,
                "redeemed_by_name": redeemer.name,
                "seller_name": seller_profile.display_name
            }
        })

    # -------------------------------------------------------------
    # ADMIN / SUPERVISOR COUPON & REQUEST MANAGEMENT
    # -------------------------------------------------------------
    @api_bp.route("/admin/coupons", methods=["GET"])
    def api_admin_get_coupons():
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        if not MentorCoupon:
            return jsonify({"success": True, "coupons": [], "stats": {}})

        coupons = MentorCoupon.query.order_by(MentorCoupon.created_at.desc()).limit(500).all()
        for c in coupons:
            if c.status == "active" and getattr(c, "is_expired", False):
                c.status = "expired"
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        rows = []
        for c in coupons:
            holders = getattr(c, "assignees", [])
            rows.append({
                "id": c.id,
                "code": c.code,
                "title": c.title,
                "description": c.description or "",
                "discount_label": c.discount_label or "",
                "status": c.status,
                "is_usable": getattr(c, "is_usable", c.status == "active"),
                "is_expired": getattr(c, "is_expired", False),
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "expires_at": c.expires_at.isoformat() if c.expires_at else None,
                "used_at": c.used_at.isoformat() if c.used_at else None,
                "seller_name": getattr(c, "seller_display_name", c.used_by or ""),
                "redeemed_by_name": (c.redeemed_by.name if getattr(c, "redeemed_by", None) else ""),
                "holders": [
                    {
                        "id": h.id,
                        "name": h.name,
                        "email": h.email,
                        "role": "Mentor" if str(h.user_type) == "1" else "Mentee"
                    }
                    for h in holders
                ]
            })

        mentors = User.query.filter_by(user_type="1").order_by(User.name).all()
        mentees = User.query.filter_by(user_type="2").order_by(User.name).all()

        requests_list = []
        if CouponRequest:
            reqs = CouponRequest.query.order_by(CouponRequest.created_at.desc()).limit(200).all()
            requests_list = [r.to_dict() for r in reqs]

        stats = {
            "total": len(coupons),
            "active": sum(1 for c in coupons if c.status == "active"),
            "used": sum(1 for c in coupons if c.status == "used"),
            "revoked": sum(1 for c in coupons if c.status in ("revoked", "expired")),
            "pending_requests": sum(1 for r in requests_list if r.get("status") == "pending")
        }

        return jsonify({
            "success": True,
            "coupons": rows,
            "mentors": [{"id": m.id, "name": m.name, "email": m.email} for m in mentors],
            "mentees": [{"id": m.id, "name": m.name, "email": m.email} for m in mentees],
            "requests": requests_list,
            "stats": stats
        })

    @api_bp.route("/admin/coupons/create", methods=["POST"])
    def api_admin_create_coupon():
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        if not MentorCoupon:
            return jsonify({"success": False, "message": "Coupon service unavailable"}), 503

        data = request.get_json(silent=True) or request.form or {}
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"success": False, "message": "Please provide a coupon title."}), 400

        assignee_ids = []
        for raw in (data.get("assignee_ids") or []):
            try:
                assignee_ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        assignee_ids = list(dict.fromkeys(assignee_ids))

        holders = []
        if assignee_ids:
            holders = User.query.filter(User.id.in_(assignee_ids), User.user_type.in_(["1", "2"])).all()

        quantity = 1
        try:
            quantity = max(1, min(200, int(data.get("quantity") or 1)))
        except (TypeError, ValueError):
            quantity = 1

        expires_at = None
        raw_expiry = (data.get("expires_at") or "").strip()
        if raw_expiry:
            for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    expires_at = datetime.strptime(raw_expiry, fmt)
                    break
                except ValueError:
                    continue

        created = []
        try:
            # One unique key per holder per unit of quantity.
            for holder in (holders or [None]):
                for _ in range(quantity):
                    coupon = MentorCoupon(
                        code=_api_generate_coupon_code(),
                        mentor_id=(holder.id if holder is not None and str(holder.user_type) == "1" else user.id),
                        issued_by_user_id=user.id,
                        title=title,
                        description=(data.get("description") or "").strip() or None,
                        discount_label=(data.get("discount_label") or "").strip() or None,
                        status="active",
                        expires_at=expires_at
                    )
                    db.session.add(coupon)
                    db.session.flush()
                    if holder is not None and CouponAssignment:
                        db.session.add(CouponAssignment(
                            coupon_id=coupon.id,
                            user_id=holder.id,
                            assigned_by=user.id
                        ))
                    created.append(coupon)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": f"Creation failed: {str(e)}"}), 500

        return jsonify({
            "success": True,
            "message": f"{len(created)} coupon(s) issued" + (f" and assigned to {len(holders)} user(s)." if holders else "."),
            "coupons": [c.to_dict() for c in created]
        }), 201

    @api_bp.route("/admin/coupons/<int:coupon_id>/status", methods=["POST"])
    def api_admin_coupon_status(coupon_id):
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        if not MentorCoupon:
            return jsonify({"success": False, "message": "Coupon service unavailable"}), 503

        coupon = db.session.get(MentorCoupon, coupon_id)
        if not coupon:
            return jsonify({"success": False, "message": "Coupon not found"}), 404

        data = request.get_json(silent=True) or request.form or {}
        action = (data.get("action") or "").strip().lower()

        if action == "revoke":
            if coupon.status == "used":
                return jsonify({"success": False, "message": "A redeemed coupon cannot be revoked."}), 400
            coupon.status = "revoked"
        elif action == "reinstate":
            if coupon.status == "used":
                return jsonify({"success": False, "message": "A redeemed coupon cannot be reinstated."}), 400
            coupon.status = "active"
        elif action == "reset":
            coupon.status = "active"
            coupon.used_at = None
            coupon.used_by = None
            coupon.seller_id = None
            coupon.redeemed_by_user_id = None
        elif action == "expire":
            coupon.status = "expired"
        else:
            return jsonify({"success": False, "message": "Invalid action. Use revoke, reinstate, reset, or expire."}), 400

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

        return jsonify({"success": True, "message": f"Coupon marked as {coupon.status}.", "coupon": coupon.to_dict()})

    @api_bp.route("/admin/coupons/assign", methods=["POST"])
    def api_admin_coupon_assign():
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        if not CouponAssignment or not MentorCoupon:
            return jsonify({"success": False, "message": "Assignment service unavailable"}), 503

        data = request.get_json(silent=True) or request.form or {}
        coupon_id = int(data.get("coupon_id") or 0)
        coupon = db.session.get(MentorCoupon, coupon_id)
        if not coupon:
            return jsonify({"success": False, "message": "Coupon not found"}), 404

        action = (data.get("action") or "add").strip().lower()
        try:
            uid = int(data.get("user_id") or 0)
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Valid user ID required"}), 400

        target_user = db.session.get(User, uid)
        if not target_user or str(target_user.user_type) not in ("1", "2"):
            return jsonify({"success": False, "message": "Only mentors and mentees can hold coupons."}), 400

        existing = CouponAssignment.query.filter_by(coupon_id=coupon.id, user_id=uid).first()
        try:
            if action == "remove":
                if existing:
                    db.session.delete(existing)
                    db.session.commit()
                return jsonify({"success": True, "action": "remove", "user_id": uid, "coupon_id": coupon.id})
            elif action == "add":
                if not existing:
                    db.session.add(CouponAssignment(coupon_id=coupon.id, user_id=uid, assigned_by=user.id))
                    db.session.commit()
                return jsonify({"success": True, "action": "add", "user_id": uid, "coupon_id": coupon.id})
            else:
                return jsonify({"success": False, "message": "Invalid action"}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

    @api_bp.route("/admin/coupon_requests", methods=["GET"])
    def api_admin_get_coupon_requests():
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        if not CouponRequest:
            return jsonify({"success": True, "requests": []})

        reqs = CouponRequest.query.order_by(CouponRequest.created_at.desc()).limit(200).all()
        return jsonify({"success": True, "requests": [r.to_dict() for r in reqs]})

    @api_bp.route("/admin/coupon_requests/<int:request_id>/status", methods=["POST"])
    def api_admin_coupon_request_status(request_id):
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        if not CouponRequest:
            return jsonify({"success": False, "message": "Coupon request service unavailable"}), 503

        req_obj = db.session.get(CouponRequest, request_id)
        if not req_obj:
            return jsonify({"success": False, "message": "Request not found"}), 404

        data = request.get_json(silent=True) or request.form or {}
        decision = (data.get("decision") or "").strip().lower()
        if decision not in ("approve", "reject"):
            return jsonify({"success": False, "message": "Decision must be 'approve' or 'reject'"}), 400

        req_obj.status = "approved" if decision == "approve" else "rejected"
        req_obj.handled_by = user.id
        req_obj.handled_at = datetime.utcnow()
        req_obj.admin_note = (data.get("note") or data.get("admin_note") or "").strip() or None

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

        import sys
        send_fn = getattr(sys.modules.get('__main__'), 'send_email_reminder', None) or getattr(sys.modules.get('app'), 'send_email_reminder', None)
        if send_fn and req_obj.user and req_obj.user.email:
            try:
                send_fn(
                    req_obj.user.email,
                    f"Coupon request {req_obj.status}",
                    f"<p>Hello {req_obj.user.name},</p><p>Your coupon request <strong>{req_obj.title}</strong> was <strong>{req_obj.status}</strong>."
                    + (f"<br/>Note: {req_obj.admin_note}" if req_obj.admin_note else "")
                    + "</p>"
                )
            except Exception as e:
                logger.warning(f"Failed to email user about request status: {e}")

        return jsonify({"success": True, "message": f"Request {req_obj.status} successfully."})

    # -------------------------------------------------------------
    # 10B. COUPON LEDGER & REFUND ENDPOINTS (Admin & Partner)
    # -------------------------------------------------------------
    @api_bp.route("/coupons/ledger", methods=["GET"])
    def api_get_coupon_ledger():
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) not in ("0", "4"):
            return jsonify({"success": False, "message": "Partner or Administrator privileges required"}), 403

        import sys as _sys
        _app_mod = _sys.modules.get('__main__') if hasattr(_sys.modules.get('__main__'), '_ledger_rows') else _sys.modules.get('app')
        _rows_fn = getattr(_app_mod, '_ledger_rows', None)
        _totals_fn = getattr(_app_mod, '_ledger_totals', None)
        _currencies = getattr(_app_mod, 'LEDGER_CURRENCIES', {"EUR": "€", "USD": "$", "GBP": "£", "INR": "₹"})

        seller_id = user.id if str(user.user_type) == "4" else None
        if _rows_fn and _totals_fn:
            f, raw_rows = _rows_fn(request.args, seller_id=seller_id)
            raw_totals = _totals_fn(raw_rows)
        else:
            raw_rows = []
            raw_totals = {}

        serialized_rows = []
        for r in raw_rows:
            serialized_rows.append({
                "id": r["id"],
                "code": r["code"],
                "title": r["title"],
                "discount_label": r["discount_label"] or "",
                "used_at": r["used_at"].isoformat() if r.get("used_at") else None,
                "partner_id": r.get("partner_id"),
                "partner": r.get("partner") or "",
                "shop": r.get("shop") or "",
                "redeemer": r.get("redeemer") or "",
                "redeemer_email": r.get("redeemer_email") or "",
                "goods_total": float(r["goods_total"]) if r.get("goods_total") is not None else None,
                "currency": r.get("currency") or "EUR",
                "discount_amount": float(r["discount_amount"]) if r.get("discount_amount") is not None else None,
                "refunded": bool(r.get("refunded")),
                "refunded_at": r["refunded_at"].isoformat() if r.get("refunded_at") else None,
                "refunded_by": r.get("refunded_by") or "",
                "recovered": float(r["recovered"]) if r.get("recovered") is not None else None,
                "note": r.get("note") or "",
                "manual": bool(r.get("manual")),
                "edited_at": r["edited_at"].isoformat() if r.get("edited_at") else None,
                "edit_role": r.get("edit_role") or "",
                "edited_by": r.get("edited_by") or ""
            })

        serialized_totals = {}
        for cur, t in raw_totals.items():
            serialized_totals[cur] = {
                "count": t["count"],
                "goods": float(t["goods"]),
                "owed": float(t["owed"]),
                "recovered": float(t["recovered"]),
                "outstanding": float(t["outstanding"]),
            }

        return jsonify({
            "success": True,
            "rows": serialized_rows,
            "totals": serialized_totals,
            "currencies": _currencies
        })

    @api_bp.route("/coupons/<int:coupon_id>/refund", methods=["POST"])
    def api_coupon_refund(coupon_id):
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        if not MentorCoupon:
            return jsonify({"success": False, "message": "Coupon service unavailable"}), 503

        c = db.session.get(MentorCoupon, coupon_id)
        if not c or c.status != "used":
            return jsonify({"success": False, "message": "Coupon not found or not redeemed"}), 404

        data = request.get_json(silent=True) or request.form or {}
        refunded = str(data.get("refunded")).lower() in ("1", "true", "yes", "on")

        import sys as _sys
        _app_mod = _sys.modules.get('__main__') if hasattr(_sys.modules.get('__main__'), '_money') else _sys.modules.get('app')
        _money_fn = getattr(_app_mod, '_money', None)

        if refunded:
            raw_rec = data.get("recovered_amount")
            amount = _money_fn(raw_rec) if _money_fn and raw_rec not in (None, "") else c.discount_amount
            if amount is None:
                return jsonify({"success": False, "message": "Set the coupon value first, then mark it refunded."}), 400
            c.refunded = True
            c.refunded_at = datetime.utcnow()
            c.refunded_by = user.id
            c.recovered_amount = amount
        else:
            c.refunded = False
            c.refunded_at = None
            c.refunded_by = None
            c.recovered_amount = None

        c.refund_note = (data.get("note") or "").strip()[:300] or None
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

        return jsonify({
            "success": True,
            "refunded": c.refunded,
            "recovered_amount": float(c.recovered_amount) if c.recovered_amount is not None else None,
            "message": f"Coupon marked as {'refunded' if c.refunded else 'unrefunded'}."
        })

    @api_bp.route("/coupons/<int:coupon_id>/ledger", methods=["POST"])
    def api_coupon_ledger_update(coupon_id):
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) not in ("0", "4"):
            return jsonify({"success": False, "message": "Unauthorized"}), 403

        if not MentorCoupon:
            return jsonify({"success": False, "message": "Coupon service unavailable"}), 503

        c = db.session.get(MentorCoupon, coupon_id)
        if not c or c.status != "used":
            return jsonify({"success": False, "message": "Coupon not found or not redeemed"}), 404

        data = request.get_json(silent=True) or request.form or {}
        import sys as _sys
        _app_mod = _sys.modules.get('__main__') if hasattr(_sys.modules.get('__main__'), '_money') else _sys.modules.get('app')
        _money_fn = getattr(_app_mod, '_money', None)
        _calc_fn = getattr(_app_mod, '_compute_coupon_discount', None)

        if str(user.user_type) == "4":
            if c.seller_id != user.id:
                return jsonify({"success": False, "message": "This coupon was redeemed at another partner's shop."}), 403
            if c.refunded:
                return jsonify({
                    "success": False, "locked": True,
                    "message": "This coupon has already been refunded, so the bill can no longer be changed. Contact admin for adjustments."
                }), 409
            g = _money_fn(data.get("goods_total")) if _money_fn else None
            if g is None or g <= 0:
                return jsonify({"success": False, "message": "Enter total bill amount (more than 0)."}), 400
            c.goods_total = g
            cur = (data.get("goods_currency") or "").strip().upper()
            if cur:
                c.goods_currency = cur
            if not c.discount_manual and _calc_fn:
                calc = _calc_fn(c.discount_label, g)
                if calc is not None:
                    c.discount_amount = calc
            c.ledger_edited_by = user.id
            c.ledger_edited_at = datetime.utcnow()
            c.ledger_edit_role = "partner"
        else:
            if "goods_total" in data:
                g = _money_fn(data.get("goods_total")) if _money_fn else None
                if g is None or g < 0:
                    return jsonify({"success": False, "message": "Enter a valid goods total."}), 400
                c.goods_total = g
                if "discount_amount" not in data and not c.discount_manual and _calc_fn:
                    calc = _calc_fn(c.discount_label, g)
                    if calc is not None:
                        c.discount_amount = calc
            if "discount_amount" in data:
                d = _money_fn(data.get("discount_amount")) if _money_fn else None
                if d is None or d < 0:
                    return jsonify({"success": False, "message": "Enter a valid coupon value."}), 400
                c.discount_amount = d
                c.discount_manual = True
            cur = (data.get("goods_currency") or "").strip().upper()
            if cur:
                c.goods_currency = cur
            if c.refunded and c.discount_amount is not None:
                c.recovered_amount = c.discount_amount
            c.ledger_edited_by = user.id
            c.ledger_edited_at = datetime.utcnow()
            c.ledger_edit_role = "admin"
            note = (data.get("note") or "").strip()[:300]
            if note:
                c.refund_note = note

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": str(e)}), 500

        return jsonify({
            "success": True,
            "goods_total": float(c.goods_total) if c.goods_total is not None else None,
            "discount_amount": float(c.discount_amount) if c.discount_amount is not None else None,
            "refunded": bool(c.refunded),
            "message": "Ledger entry updated successfully."
        })

    # -------------------------------------------------------------
    # 10C. ADMIN USER PROFILE SUMMARY & ACCOUNT MANAGEMENT
    # -------------------------------------------------------------
    @api_bp.route("/admin/user_summary/<int:user_id>", methods=["GET"])
    def api_admin_user_summary(user_id):
        admin = get_current_user_from_req(User)
        if not admin or str(admin.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        target_user = db.session.get(User, user_id)
        if not target_user:
            return jsonify({"success": False, "message": "User not found"}), 404

        logger.info(f"ADMIN_PROFILE_VIEW admin_id={admin.id} target_id={target_user.id} target_type={target_user.user_type}")

        ut = str(target_user.user_type or "")
        role = {"0": "Admin", "1": "Mentor", "2": "Mentee", "3": "Institution", "4": "Partner"}.get(ut, "User")
        rows = []
        pic = target_user.profile_picture_url or ""
        completion = None

        def add(label, value):
            if value not in (None, "", []):
                rows.append([label, str(value)])

        add("Email", target_user.email)
        if target_user.work_email and target_user.work_email != target_user.email:
            add("Work email", target_user.work_email)
        if target_user.personal_email and target_user.personal_email != target_user.email:
            add("Personal email", target_user.personal_email)
        add("Joined", target_user.created_at.strftime("%d %b %Y") if target_user.created_at else "")

        if ut == "1":
            mp = MentorProfile.query.filter_by(user_id=target_user.id).first() if MentorProfile else None
            if mp:
                pic = mp.profile_picture or pic
                add("Profession", mp.profession)
                add("Organisation", mp.organisation)
                add("Experience", (mp.years_of_experience + " yrs") if mp.years_of_experience else "")
                loc_parts = [getattr(mp, "city", None), getattr(mp, "state", None), getattr(mp, "country", None)]
                add("Location", ", ".join(x for x in loc_parts if x))
                add("WhatsApp", mp.whatsapp)
                add("Skills", mp.skills)
                add("LinkedIn", getattr(mp, "linkedin_link", ""))
        elif ut == "2":
            mp = MenteeProfile.query.filter_by(user_id=target_user.id).first() if MenteeProfile else None
            if mp:
                pic = mp.profile_picture or pic
                add("School / college", mp.school_college_name)
                add("Stream", mp.stream)
                add("Goal", (mp.goal or "")[:200])
                add("Location", ", ".join(x for x in (mp.city, mp.state, mp.country) if x))
                add("Mobile", mp.mobile_number)
        elif ut == "3":
            inst = Institution.query.filter_by(user_id=target_user.id).first() if Institution else None
            if inst:
                pic = inst.profile_picture or pic
                add("Contact person", inst.contact_person)
                add("Contact email", inst.contact_email)
                add("Phone", inst.contact_phone)
                add("Location", ", ".join(x for x in (inst.city, inst.country) if x))
                add("Status", inst.status)
            if target_user.institution_id:
                add("Mentors", User.query.filter_by(user_type="1", institution_id=target_user.institution_id).count())
        elif ut == "4":
            sp = SellerProfile.query.filter_by(user_id=target_user.id).first() if SellerProfile else None
            if sp:
                pic = sp.profile_picture or pic
                add("Business", sp.display_name)
                add("Type", sp.partner_label)
                add("Category", sp.business_category)
                add("Location", ", ".join(x for x in (sp.city, sp.state, sp.country) if x))
                add("Phone", sp.contact_phone)
                add("Shops owned", getattr(sp, "shop_count", 1))
                if MentorCoupon:
                    add("Coupons redeemed", MentorCoupon.query.filter(MentorCoupon.seller_id == target_user.id, MentorCoupon.used_at.isnot(None)).count())
                if SellerReferral:
                    add("People referred", SellerReferral.query.filter_by(seller_id=target_user.id).count())

        if ut in ("1", "2"):
            compute_fn = kwargs.get("compute_profile_completeness")
            if compute_fn:
                try:
                    completion = int(compute_fn(target_user.id, ut) or 0)
                except Exception:
                    completion = None
            if SellerReferral:
                ref = SellerReferral.query.filter_by(user_id=target_user.id).first()
                if ref:
                    sp = SellerProfile.query.filter_by(user_id=ref.seller_id).first() if SellerProfile else None
                    add("Referred by", f"{sp.display_name if sp else (ref.seller.name if hasattr(ref, 'seller') and ref.seller else 'Partner')} ({ref.status})")
            add("Institution", target_user.institution)

        return jsonify({
            "success": True,
            "id": target_user.id,
            "name": target_user.name,
            "role": role,
            "picture": pic,
            "completion": completion,
            "rows": rows,
        })

    @api_bp.route("/admin/users/<int:user_id>", methods=["DELETE", "POST"])
    @api_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
    def api_admin_delete_user(user_id):
        admin = get_current_user_from_req(User)
        if not admin or str(admin.user_type) != "0":
            return jsonify({"success": False, "message": "Administrator privileges required"}), 403

        target_user = db.session.get(User, user_id)
        if not target_user:
            return jsonify({"success": False, "message": "User not found"}), 404

        user_name = target_user.name
        user_email = target_user.email

        try:
            from sqlalchemy import text as _text

            # 1. Nullify references where target user is a secondary participant/actor
            nullable_fk_cleanups = [
                ("meeting_requests", "rescheduled_by_id"),
                ("mentorship_requests", "rated_by"),
                ("mentor_profile", "referred_by_seller_id"),
                ("seller_profiles", "verified_by"),
                ("coupon_assignments", "assigned_by"),
                ("coupon_requests", "handled_by"),
                ("resource_notes", "mentor_id"),
                ("personal_tasks", "mentor_id"),
            ]
            for table, col in nullable_fk_cleanups:
                try:
                    with db.session.begin_nested():
                        db.session.execute(_text(f"UPDATE {table} SET {col} = NULL WHERE {col} = :uid"), {"uid": user_id})
                except Exception as null_err:
                    logger.warning(f"api_admin_delete_user: nullify {table}.{col}: {null_err}")

            # Unlink institutions owned by this user
            try:
                with db.session.begin_nested():
                    db.session.execute(_text("UPDATE signup_details SET institution_id = NULL WHERE institution_id IN (SELECT id FROM institutions WHERE user_id = :uid)"), {"uid": user_id})
                    db.session.execute(_text("UPDATE resource_notes SET institution_id = NULL WHERE institution_id IN (SELECT id FROM institutions WHERE user_id = :uid)"), {"uid": user_id})
            except Exception as inst_err:
                logger.warning(f"api_admin_delete_user: unlink institution: {inst_err}")

            # 2. Delete related records first (due to foreign key constraints)
            tables_to_clean = [
                ("profile_completion_reminders", "user_id"),
                ("mentor_profile", "user_id"),
                ("mentee_profile", "user_id"),
                ("supervisor_profile", "user_id"),
                ("institutions", "user_id"),
                ("mentorship_requests", "mentee_id"),
                ("mentorship_requests", "mentor_id"),
                ("meeting_requests", "requester_id"),
                ("meeting_requests", "requested_to_id"),
                ("mentee_tasks", "mentee_id"),
                ("mentee_tasks", "mentor_id"),
                ("personal_tasks", "mentee_id"),
                ("personal_tasks", "mentor_id"),
                ("task_ratings", "mentee_id"),
                ("task_ratings", "mentor_id"),
                ("mentee_feedbacks", "mentee_id"),
                ("mentor_reflections", "mentor_id"),
                ("resource_notes", "mentee_id"),
                ("mentor_sourcing_requests", "mentee_id"),
                ("scholarly_applications", "mentee_id"),
                ("premium_applications", "mentor_id"),
                ("seller_profiles", "user_id"),
                ("seller_shops", "seller_user_id"),
                ("seller_referrals", "user_id"),
                ("seller_referrals", "seller_id"),
                ("coupon_requests", "user_id"),
                ("account_verifications", "user_id"),
                ("notifications", "user_id"),
                ("coupon_assignments", "user_id"),
                ("chat_messages", "sender_id"),
                ("chat_conversations", "participant1_id"),
                ("chat_conversations", "participant2_id"),
            ]

            for table, column in tables_to_clean:
                try:
                    with db.session.begin_nested():
                        db.session.execute(_text(f"DELETE FROM {table} WHERE {column} = :uid"), {"uid": user_id})
                except Exception as clean_err:
                    logger.warning(f"api_admin_delete_user: skipped {table}.{column}: {clean_err}")

            keeper = admin.id
            if MentorCoupon:
                for col, val in (("seller_id", None), ("redeemed_by_user_id", None), ("partner_user_id", None),
                                 ("issued_by_user_id", None), ("refunded_by", None), ("mentor_id", keeper)):
                    try:
                        with db.session.begin_nested():
                            db.session.execute(_text(f"UPDATE mentor_coupons SET {col} = :v WHERE {col} = :uid"), {"v": val, "uid": user_id})
                    except Exception as ce:
                        logger.warning(f"api_admin_delete_user: coupon unlink {col}: {ce}")

            db.session.expire_all()
            user_to_delete = db.session.get(User, user_id)
            if user_to_delete:
                db.session.delete(user_to_delete)
            db.session.commit()
            logger.info(f"ADMIN_USER_ERASED admin_id={admin.id} erased_user_id={user_id}")

            return jsonify({"success": True, "message": f"{user_name} ({user_email}) has been permanently deleted."})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": f"Error deleting user: {str(e)}"}), 500

    # -------------------------------------------------------------
    # 11. IN-APP CHAT REST ENDPOINTS
    # -------------------------------------------------------------
    @api_bp.route("/chat/conversations", methods=["GET"])
    def api_chat_conversations():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if not ChatConversation:
            return jsonify({"success": False, "conversations": []})

        conversations = ChatConversation.query.filter(
            or_(
                ChatConversation.participant1_id == user.id,
                ChatConversation.participant2_id == user.id
            )
        ).order_by(ChatConversation.updated_at.desc()).all()

        res = []
        for conv in conversations:
            other_id = conv.participant2_id if conv.participant1_id == user.id else conv.participant1_id
            other_u = User.query.get(other_id)
            if not other_u:
                continue

            last_msg = None
            if ChatMessage:
                last_msg = ChatMessage.query.filter_by(conversation_id=conv.id).order_by(ChatMessage.created_at.desc()).first()

            unread = 0
            if ChatMessage:
                unread = ChatMessage.query.filter_by(conversation_id=conv.id, is_read=False).filter(ChatMessage.sender_id != user.id).count()

            other_pic = getattr(other_u, 'profile_picture_url', None)
            res.append({
                "id": conv.id,
                "other_user_id": other_id,
                "other_user_name": other_u.name,
                "other_user_type": other_u.user_type,
                "other_user_avatar": format_pic_url(other_pic),
                "last_message": last_msg.content if last_msg else "",
                "last_message_time": last_msg.created_at.isoformat() + "Z" if last_msg and last_msg.created_at else None,
                "unread_count": unread,
                "updated_at": conv.updated_at.isoformat() + "Z" if conv.updated_at else datetime.utcnow().isoformat() + "Z"
            })
        return jsonify({"success": True, "conversations": res})

    @api_bp.route("/chat/messages/<int:conversation_id>", methods=["GET"])
    def api_chat_messages(conversation_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if not ChatConversation or not ChatMessage:
            return jsonify({"success": False, "messages": []})

        conv = db.session.get(ChatConversation, conversation_id)
        if not conv or (conv.participant1_id != user.id and conv.participant2_id != user.id):
            return jsonify({"success": False, "message": "Conversation not found"}), 404

        # Mark incoming unread messages as read
        ChatMessage.query.filter_by(conversation_id=conv.id, is_read=False).filter(ChatMessage.sender_id != user.id).update({"is_read": True})
        db.session.commit()

        messages = ChatMessage.query.filter_by(conversation_id=conv.id).order_by(ChatMessage.created_at.asc()).all()
        return jsonify({
            "success": True,
            "messages": [
                {
                    "id": m.id,
                    "conversation_id": m.conversation_id,
                    "sender_id": m.sender_id,
                    "is_me": m.sender_id == user.id,
                    "content": m.content,
                    "is_read": bool(m.is_read),
                    "created_at": m.created_at.isoformat() + "Z" if m.created_at else None
                } for m in messages
            ]
        })

    @api_bp.route("/chat/send", methods=["POST"])
    def api_chat_send():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if not ChatConversation or not ChatMessage:
            return jsonify({"success": False, "message": "Chat service unavailable"}), 503

        data = request.get_json(silent=True) or request.form or {}
        content = (data.get("content") or data.get("message") or "").strip()
        if not content:
            return jsonify({"success": False, "message": "Message content cannot be empty"}), 400

        conv_id = data.get("conversation_id")
        conv = None
        if conv_id:
            conv = db.session.get(ChatConversation, int(conv_id))
        
        if not conv:
            other_id = data.get("other_user_id") or data.get("recipient_id")
            if not other_id:
                return jsonify({"success": False, "message": "Recipient or conversation ID required"}), 400
            other_id = int(other_id)
            p1, p2 = min(user.id, other_id), max(user.id, other_id)
            conv = ChatConversation.query.filter_by(participant1_id=p1, participant2_id=p2).first()
            if not conv:
                conv = ChatConversation(participant1_id=p1, participant2_id=p2, conversation_type="direct", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
                db.session.add(conv)
                db.session.flush()

        msg = ChatMessage(
            conversation_id=conv.id,
            sender_id=user.id,
            content=content,
            is_read=False,
            created_at=datetime.utcnow()
        )
        conv.updated_at = datetime.utcnow()
        db.session.add(msg)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": {
                "id": msg.id,
                "conversation_id": conv.id,
                "sender_id": user.id,
                "is_me": True,
                "content": msg.content,
                "is_read": False,
                "created_at": msg.created_at.isoformat() + "Z"
            }
        })

    @api_bp.route("/chat/mark-read/<int:conversation_id>", methods=["POST"])
    def api_chat_mark_read(conversation_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if ChatMessage:
            ChatMessage.query.filter_by(conversation_id=conversation_id, is_read=False).filter(ChatMessage.sender_id != user.id).update({"is_read": True})
            db.session.commit()
        return jsonify({"success": True})

    @api_bp.route("/chat/start/<int:other_user_id>", methods=["POST"])
    def api_chat_start(other_user_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if not ChatConversation:
            return jsonify({"success": False, "message": "Chat service unavailable"}), 503

        p1, p2 = min(user.id, other_user_id), max(user.id, other_user_id)
        conv = ChatConversation.query.filter_by(participant1_id=p1, participant2_id=p2).first()
        if not conv:
            conv = ChatConversation(participant1_id=p1, participant2_id=p2, conversation_type="direct", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            db.session.add(conv)
            db.session.commit()
        return jsonify({"success": True, "conversation_id": conv.id})

    # -------------------------------------------------------------
    # 12. MENTORSHIP RATING & REVIEW ENDPOINTS
    # -------------------------------------------------------------
    @api_bp.route("/mentorship_completion_status/<int:mentorship_id>", methods=["GET"])
    def api_mentorship_completion_status_mobile(mentorship_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        mr = db.session.get(MentorshipRequest, mentorship_id)
        if not mr:
            return jsonify({"success": False, "message": "Mentorship not found"}), 404
        
        tasks = MenteeTask.query.filter_by(mentee_id=mr.mentee_id, mentor_id=mr.mentor_id).all() if MenteeTask else []
        if tasks:
            done_cnt = sum(1 for t in tasks if (t.status or "").lower() in ("done", "completed") or (t.progress or 0) >= 100)
            pct = round((done_cnt / len(tasks)) * 100, 1)
            is_done = pct >= 80.0
        else:
            is_done = False
            pct = 0.0

        return jsonify({
            "success": True,
            "completed": is_done,
            "completion_pct": pct,
            "mentorship_id": mentorship_id
        })

    @api_bp.route("/mentorship_rating/<int:mentorship_id>", methods=["GET"])
    def api_mentorship_rating_mobile(mentorship_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        mr = db.session.get(MentorshipRequest, mentorship_id)
        if not mr:
            return jsonify({"success": False, "message": "Mentorship not found"}), 404

        import sys
        calc_fn = getattr(sys.modules.get('__main__'), 'compute_mentorship_composite_rating', None) or getattr(sys.modules.get('app'), 'compute_mentorship_composite_rating', None)
        if calc_fn:
            rating_data = calc_fn(mr.mentee_id, mr.mentor_id)
        else:
            rating_data = {"overall_rating": 5.0, "total_reviews": 0}

        return jsonify({"success": True, "rating": rating_data})

    @api_bp.route("/submit_mentorship_rating", methods=["POST"])
    def api_submit_mentorship_rating_mobile():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        data = request.get_json(silent=True) or request.form or {}
        mentorship_id = data.get("mentorship_id")
        if not mentorship_id:
            return jsonify({"success": False, "message": "mentorship_id required"}), 400

        over = int(data.get("overall") or data.get("rating") or 5)
        feedback_text = (data.get("feedback") or "").strip()

        mr = db.session.get(MentorshipRequest, int(mentorship_id))
        if not mr:
            return jsonify({"success": False, "message": "Mentorship not found"}), 404

        if MenteeFeedback:
            fb = MenteeFeedback(
                mentee_id=mr.mentee_id,
                mentor_id=mr.mentor_id,
                task_id=0,
                task_type="mentorship",
                rating=over,
                feedback=feedback_text,
                created_at=datetime.utcnow()
            )
            db.session.add(fb)
            db.session.commit()

        return jsonify({"success": True, "message": "Mentorship rating submitted successfully."})

    # -------------------------------------------------------------
    # 13. NOTE MANAGEMENT ENDPOINTS
    # -------------------------------------------------------------
    @api_bp.route("/notes", methods=["GET"])
    def api_get_notes():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if not ResourceNote:
            return jsonify({"success": True, "notes": []})

        notes = ResourceNote.query.filter(
            or_(
                ResourceNote.mentee_id == user.id,
                ResourceNote.mentor_id == user.id,
                ResourceNote.institution_id == user.institution_id
            )
        ).order_by(ResourceNote.updated_at.desc()).all()

        return jsonify({
            "success": True,
            "notes": [
                {
                    "id": n.id,
                    "title": n.title,
                    "content": n.content,
                    "created_at": n.created_at.strftime("%Y-%m-%d") if n.created_at else "",
                    "updated_at": n.updated_at.strftime("%Y-%m-%d") if n.updated_at else ""
                } for n in notes
            ]
        })

    @api_bp.route("/notes/create", methods=["POST"])
    def api_create_note():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if not ResourceNote:
            return jsonify({"success": False, "message": "Notes service unavailable"}), 503

        data = request.get_json(silent=True) or request.form or {}
        title = (data.get("title") or "").strip()
        content = (data.get("content") or "").strip()
        if not title or not content:
            return jsonify({"success": False, "message": "Title and content required"}), 400

        note = ResourceNote(
            mentee_id=user.id if str(user.user_type) == "2" else None,
            mentor_id=user.id if str(user.user_type) == "1" else None,
            institution_id=user.institution_id,
            title=title,
            content=content,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.session.add(note)
        db.session.commit()
        return jsonify({"success": True, "note_id": note.id, "message": "Note created"})

    @api_bp.route("/notes/<int:note_id>", methods=["PUT", "POST"])
    def api_update_note(note_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if not ResourceNote:
            return jsonify({"success": False, "message": "Notes service unavailable"}), 503

        note = db.session.get(ResourceNote, note_id)
        if not note:
            return jsonify({"success": False, "message": "Note not found"}), 404

        data = request.get_json(silent=True) or request.form or {}
        if "title" in data:
            note.title = data["title"].strip()
        if "content" in data:
            note.content = data["content"].strip()
        note.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"success": True, "message": "Note updated"})

    @api_bp.route("/notes/<int:note_id>", methods=["DELETE"])
    def api_delete_note(note_id):
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if not ResourceNote:
            return jsonify({"success": False, "message": "Notes service unavailable"}), 503

        note = db.session.get(ResourceNote, note_id)
        if not note:
            return jsonify({"success": False, "message": "Note not found"}), 404
        db.session.delete(note)
        db.session.commit()
        return jsonify({"success": True, "message": "Note deleted"})

    # -------------------------------------------------------------
    # 14. REMINDERS & SETTINGS ENDPOINTS
    # -------------------------------------------------------------
    @api_bp.route("/admin/reminders/settings", methods=["GET", "POST"])
    def api_admin_reminder_settings():
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) not in ("0", "4"):
            return jsonify({"success": False, "message": "Admin privileges required"}), 403

        if not ReminderSettings:
            return jsonify({"success": True, "settings": {}})

        settings = ReminderSettings.query.first()
        if request.method == "POST":
            data = request.get_json(silent=True) or request.form or {}
            if not settings:
                settings = ReminderSettings()
                db.session.add(settings)
            if "is_enabled" in data:
                settings.is_enabled = bool(data["is_enabled"])
            db.session.commit()
            return jsonify({"success": True, "message": "Settings updated"})

        return jsonify({
            "success": True,
            "settings": {
                "id": getattr(settings, 'id', 1),
                "is_enabled": getattr(settings, 'is_enabled', True),
                "days_after_creation": getattr(settings, 'days_after_creation', 7)
            } if settings else {"is_enabled": True}
        })

    @api_bp.route("/admin/reminders/logs", methods=["GET"])
    def api_admin_reminder_logs():
        user = get_current_user_from_req(User)
        if not user:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        if not ProfileCompletionReminder:
            return jsonify({"success": True, "logs": []})

        query = ProfileCompletionReminder.query
        if str(user.user_type) not in ("0", "4"):
            query = query.filter_by(user_id=user.id)
        
        logs = query.order_by(ProfileCompletionReminder.sent_at.desc()).limit(50).all()
        return jsonify({
            "success": True,
            "logs": [
                {
                    "id": l.id,
                    "user_id": l.user_id,
                    "user_type": l.user_type,
                    "sent_at": l.sent_at.strftime("%Y-%m-%d %H:%M") if l.sent_at else ""
                } for l in logs
            ]
        })

    # -------------------------------------------------------------
    # 15. MENTOR COUPON ENDPOINTS
    # -------------------------------------------------------------
    @api_bp.route("/mentor/coupons/create", methods=["POST"])
    def api_mentor_create_coupon():
        user = get_current_user_from_req(User)
        if not user or str(user.user_type) != "1":
            return jsonify({"success": False, "message": "Mentor privileges required"}), 403
        if not MentorCoupon:
            return jsonify({"success": False, "message": "Coupon service unavailable"}), 503

        data = request.get_json(silent=True) or request.form or {}
        title = (data.get("title") or "").strip()
        discount = (data.get("discount_value") or data.get("discount") or "10%").strip()
        if not title:
            return jsonify({"success": False, "message": "Title required"}), 400

        code = _api_generate_coupon_code()
        coupon = MentorCoupon(
            mentor_id=user.id,
            title=title,
            code=code,
            discount_value=discount,
            is_active=True,
            created_at=datetime.utcnow()
        )
        db.session.add(coupon)
        db.session.commit()
        return jsonify({"success": True, "message": "Coupon created", "coupon": coupon.to_dict() if hasattr(coupon, 'to_dict') else {"id": coupon.id, "code": code}})

    @api_bp.errorhandler(Exception)
    def handle_api_exception(e):
        logger.error(f"Unhandled API error: {e}", exc_info=True)
        try:
            db.session.rollback()
        except Exception:
            pass
        code = getattr(e, "code", 500)
        return jsonify({
            "success": False,
            "message": str(getattr(e, "description", e)) or "Internal server error",
            "error": str(e)
        }), code if isinstance(code, int) and 100 <= code <= 599 else 500

    app.register_blueprint(api_bp)
    logger.info("Mobile REST API endpoints successfully registered under /api/*")
