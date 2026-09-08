from flask import Flask, redirect, url_for, render_template, request, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, login_user, LoginManager, login_required, logout_user, current_user
from sqlalchemy import cast, Integer, or_, and_, text, func
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy.orm import Session
import os
import json 
import time
from urllib.parse import urlencode
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime as dt
from flask_migrate import Migrate
import random
import secrets
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys
import requests as http_requests

# Force UTF-8 output so emoji-heavy logs do not crash on Windows consoles (cp1252).
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# Load the local .env file into the environment (if present).
# Never overrides variables already set in the real environment.
# DATABASE_URL from .env is intentionally ignored here so local
# development keeps using the existing SQLite database.
def load_env_file():
    try:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if not os.path.exists(env_path):
            return
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if not key:
                    continue
                if key in ("DATABASE_URL",):
                    continue
                if key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        print(f"Warning: could not load .env: {e}")

load_env_file()

# ============================================================
# PRODUCTION CONFIGURATION
# ============================================================
# Set to True for production, False for local development
# Can be overridden via env var: PRODUCTION=false python app.py
PRODUCTION = os.environ.get("PRODUCTION", "false").lower() in ("1", "true", "yes")

from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Secret key - USE A STRONG RANDOM KEY IN PRODUCTION!
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
if PRODUCTION:
    app.secret_key = os.environ.get("SECRET_KEY", "your-production-secret-key-change-this")
else:
    app.secret_key = "1234"  # Only for local development

app.permanent_session_lifetime = timedelta(days=10)

# Image upload configuration
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf"}  # Added PDF for criminal certificate

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Ensure folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Helper function to calculate age from date of birth
def calculate_age(dob_string):
    """
    Calculate age from date of birth string.
    Args:
        dob_string: Date string in format 'YYYY-MM-DD' or None
    Returns:
        String like "22 years" or None if dob_string is None/empty
    """
    if not dob_string:
        return None
    
    try:
        # Parse the date string
        dob = datetime.strptime(dob_string, '%Y-%m-%d').date()
        today = datetime.now().date()
        
        # Calculate age
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        
        return f"{age} years"
    except (ValueError, AttributeError):
        return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_under_18(dob_string):
    """
    Check if person is under 18 years old based on date of birth.
    Returns True if under 18, False otherwise.
    """
    if not dob_string:
        return False
    
    try:
        # Try multiple date formats
        for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]:
            try:
                dob = datetime.strptime(dob_string, fmt)
                today = datetime.today()
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                return age < 18
            except ValueError:
                continue
        return False
    except Exception as e:
        print(f"Error calculating age: {e}")
        return False

def generate_consent_token():
    """Generate a unique token for parent consent link"""
    import secrets
    return secrets.token_urlsafe(32)

def send_parent_consent_email(parent_email, parent_name, mentee_name, consent_token):
    """Send parent consent email with approval link"""
    try:
        print(f"📧 Starting email send process...")
        print(f"   SMTP Server: {SMTP_SERVER}:{SMTP_PORT}")
        print(f"   From: {SMTP_EMAIL}")
        print(f"   To: {parent_email}")
        
        # Build approval link manually based on environment
        if PRODUCTION:
            base_url = "https://mentorship.weslux.lu"
        else:
            base_url = "http://127.0.0.1:5000"
        
        approval_link = f"{base_url}/parent_consent/{consent_token}"
        print(f"   Approval Link: {approval_link}")
        
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = parent_email
        msg['Subject'] = f"Parent Consent Required for {mentee_name}'s Mentorship Program"
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; border-radius: 10px;">
                <h2 style="color: #2563eb; text-align: center;">Parent Consent Required</h2>
                
                <p>Dear {parent_name},</p>
                
                <p>Your child, <strong>{mentee_name}</strong>, has registered for our Mentorship Connect program.</p>
                
                <p>Since {mentee_name} is under 18 years old, we require your consent before they can participate in the mentorship program.</p>
                
                <div style="background-color: #fff; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #2563eb;">What happens next?</h3>
                    <ul>
                        <li>Review your child's profile details</li>
                        <li>Approve or reject their participation</li>
                        <li>Once approved, they can connect with mentors</li>
                    </ul>
                </div>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{approval_link}" 
                       style="background-color: #2563eb; color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; display: inline-block; font-weight: bold;">
                        Review & Approve
                    </a>
                </div>
                
                <p style="color: #666; font-size: 14px; margin-top: 30px;">
                    If you did not expect this email, please ignore it or contact us at support@mentorsconnect.com
                </p>
                
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                
                <p style="text-align: center; color: #999; font-size: 12px;">
                    © 2026 Mentors Connect. All rights reserved.
                </p>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html_body, 'html'))
        
        print(f"📤 Connecting to SMTP server...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        print(f"🔐 Starting TLS...")
        server.starttls()
        print(f"🔑 Logging in...")
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        print(f"📨 Sending message...")
        server.send_message(msg)
        print(f"👋 Closing connection...")
        server.quit()
        
        print(f"✅ Email sent successfully to {parent_email}")
        return True
    except Exception as e:
        print(f"❌ Error sending parent consent email: {e}")
        print(f"   Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "signin" 

# --- User Loader ---
@login_manager.user_loader
def load_user(user_id):
    if not user_id:
        return None
    try:
        return User.query.options(
            joinedload(User.mentor_profile),
            joinedload(User.mentee_profile)
        ).filter_by(id=int(user_id)).first()
    except Exception:
        return None


# ============================================================
# GOOGLE OAUTH CONFIGURATION
# ============================================================
if PRODUCTION:
    # Production settings - HTTPS required
    # Remove OAUTHLIB_INSECURE_TRANSPORT in production
    CLIENT_SECRETS_FILE = "client_secret.json"
    REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://mentorship.weslux.lu/callback")
else:
    # Development settings - HTTP allowed
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # ONLY for local dev (http)
    CLIENT_SECRETS_FILE = "client_secret.json"
    REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://127.0.0.1:5000/callback")

def get_current_redirect_uri():
    """Dynamically construct redirect URI matching the current host/domain"""
    if os.environ.get("REDIRECT_URI"):
        return os.environ.get("REDIRECT_URI")
    try:
        host = request.host.split(":")[0]  # strip port if present
        # Google OAuth requires HTTPS scheme for all non-localhost domains
        if host not in ("127.0.0.1", "localhost", "0.0.0.0"):
            scheme = "https"
        else:
            scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
        uri = url_for("callback", _external=True, _scheme=scheme)
        print(f"🔗 Dynamically generated Redirect URI: {uri}")
        return uri
    except Exception as e:
        print(f"⚠️ Dynamic URI fallback used ({e}): {REDIRECT_URI}")
        return REDIRECT_URI

# Scopes for Google OAuth Login (user info only)
LOGIN_SCOPES = [
    "openid", 
    "https://www.googleapis.com/auth/userinfo.email", 
    "https://www.googleapis.com/auth/userinfo.profile"
]

# Scopes for Google Calendar (meetings)
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar"
]

# Combined scopes (for backward compatibility)
SCOPES = LOGIN_SCOPES

def get_google_flow(scopes, redirect_uri, state=None):
    """Create Google OAuth Flow using client_secret.json or env vars"""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    
    if os.path.exists(CLIENT_SECRETS_FILE):
        return Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=scopes,
            state=state,
            redirect_uri=redirect_uri
        )
    elif client_id and client_secret:
        client_config = {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri]
            }
        }
        return Flow.from_client_config(
            client_config,
            scopes=scopes,
            state=state,
            redirect_uri=redirect_uri
        )
    else:
        raise FileNotFoundError(f"Neither {CLIENT_SECRETS_FILE} file nor GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET environment variables were found.")

# ============================================================
# DATABASE CONFIGURATION
# ============================================================
db_url = os.environ.get("DATABASE_URL", "").strip()
if db_url:
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    if "?pgbouncer=true" in db_url:
        db_url = db_url.replace("?pgbouncer=true", "")
    if "&pgbouncer=true" in db_url:
        db_url = db_url.replace("&pgbouncer=true", "")
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    print(f"🟢 Database Mode: Connected to External Database ({app.config['SQLALCHEMY_DATABASE_URI']})")
else:
    instance_db_path = os.path.join(app.instance_path, "mentors_connect.db")
    root_db_path = os.path.join(app.root_path, "mentors_connect.db")

    if os.path.exists(instance_db_path):
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{instance_db_path}"
    elif os.path.exists(root_db_path):
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{root_db_path}"
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{instance_db_path}"
    print(f"🟢 Database Mode: Connected to SQLite ({app.config['SQLALCHEMY_DATABASE_URI']})")

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Background Supabase Cloud Backup Sync (Disabled by request)
# try:
#     import supabase_sync
#     supabase_sync.start_periodic_sync(interval_seconds=60)
# except Exception as sync_err:
#     print("Background Supabase backup notice:", sync_err)

# Configure Flask-Caching in memory (SimpleCache for 0ms RAM caching)
from flask_caching import Cache
from sqlalchemy.orm import joinedload

cache = Cache(app, config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300})

# ============================================================
# JINJA2 CUSTOM FILTERS
# ============================================================

@app.template_filter('from_json')
def from_json(value):
    """Convert JSON string to Python object"""
    try:
        if isinstance(value, str):
            return json.loads(value)
        return value
    except (json.JSONDecodeError, TypeError):
        return []

@app.template_filter('to_json')
def to_json(value):
    """Convert Python object to JSON string"""
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return ""

# ============================================================
# EMAIL CONFIGURATION FOR OTP
# ============================================================
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "mentorship@wazireducationsociety.com")  # Change this
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "kmbiechgqjxtfoef")  # Gmail App Password

# ------------------------------------------------------------
# EXTERNAL EXPORT API CONFIG
# ------------------------------------------------------------
# Key used to authenticate external callers of POST /api/export_mentee_work.
# Set EXPORT_API_KEY in .env (or environment). A secure default is provided
# so the API works out of the box, but you should change it for production.
EXPORT_API_KEY = os.environ.get("EXPORT_API_KEY", "b579c3db0781ce16211911ccc806bd6ba0db1092cba48c539b8e1429ea109a4e")

def send_otp_email(to_email, otp):
    """Send OTP to user's email"""
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = to_email
        msg['Subject'] = "Password Reset OTP - Mentor Connect"
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #2563eb;">Password Reset Request</h2>
            <p>You have requested to reset your password for Mentor Connect.</p>
            <p>Your OTP code is:</p>
            <h1 style="color: #2563eb; font-size: 32px; letter-spacing: 5px;">{otp}</h1>
            <p>This OTP will expire in <strong>10 minutes</strong>.</p>
            <p>If you did not request this, please ignore this email.</p>
            <hr>
            <p style="color: #666; font-size: 12px;">Mentor Connect - Wazir Education Society</p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def send_signup_otp_email(to_email, otp):
    """Send account-verification OTP during Google sign-up"""
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = to_email
        msg['Subject'] = "Verify your email - Mentor Connect Sign Up"

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #2563eb;">Verify your Mentor Connect account</h2>
            <p>You are creating a Mentor Connect account with this email via Google.</p>
            <p>Your verification code is:</p>
            <h1 style="color: #2563eb; font-size: 32px; letter-spacing: 5px;">{otp}</h1>
            <p>This code will expire in <strong>10 minutes</strong>.</p>
            <p>If you did not start this sign-up, please ignore this email.</p>
            <hr>
            <p style="color: #666; font-size: 12px;">Mentor Connect - Wazir Education Society</p>
        </body>
        </html>
        """

        msg.attach(MIMEText(body, 'html'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()

        return True
    except Exception as e:
        print(f"Error sending signup OTP email: {e}")
        return False

def send_welcome_email(to_email, user_name, signup_method="traditional"):
    """Send welcome email to new users after signup"""
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = to_email
        msg['Subject'] = "Welcome to Mentor Connect! 🎉"
        
        # Determine signup method text
        signup_text = "signing up" if signup_method == "traditional" else "signing up with Google"
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f8fafc;">
            <div style="max-width: 600px; margin: 0 auto; background-color: white; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                <!-- Header -->
                <div style="background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%); padding: 40px 20px; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 32px;">Welcome to Mentor Connect! 🎉</h1>
                    <p style="color: #e0e7ff; margin: 10px 0 0 0; font-size: 16px;">Your journey to growth begins here</p>
                </div>
                
                <!-- Content -->
                <div style="padding: 40px 30px;">
                    <h2 style="color: #1e293b; margin-top: 0;">Hi {user_name},</h2>
                    
                    <p style="color: #475569; font-size: 16px; line-height: 1.6;">
                        Thank you for {signup_text} with <strong>Mentor Connect</strong>! We're thrilled to have you join our community of mentors and mentees dedicated to personal and professional growth.
                    </p>
                    
                    <div style="background-color: #f1f5f9; border-left: 4px solid #2563eb; padding: 20px; margin: 30px 0; border-radius: 8px;">
                        <h3 style="color: #1e293b; margin-top: 0; font-size: 18px;">🚀 Next Steps:</h3>
                        <ol style="color: #475569; line-height: 1.8; margin: 10px 0;">
                            <li><strong>Complete Your Profile</strong> - Add your details to help others connect with you</li>
                            <li><strong>Explore the Platform</strong> - Discover mentors or mentees that match your goals</li>
                            <li><strong>Start Connecting</strong> - Send mentorship requests and begin your journey</li>
                        </ol>
                    </div>
                    
                    <div style="background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%); padding: 25px; border-radius: 12px; margin: 30px 0;">
                        <h3 style="color: #1e40af; margin-top: 0; font-size: 18px;">✨ What You Can Do:</h3>
                        <ul style="color: #1e40af; line-height: 1.8; margin: 10px 0;">
                            <li>Connect with experienced mentors or eager mentees</li>
                            <li>Schedule meetings and track your progress</li>
                            <li>Manage tasks and receive feedback</li>
                            <li>Chat in real-time with your connections</li>
                            <li>Access resources and guidance for your journey</li>
                        </ul>
                    </div>
                    
                    <div style="text-align: center; margin: 40px 0;">
                        <a href="https://mentorship.weslux.lu" style="display: inline-block; background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%); color: white; padding: 16px 40px; text-decoration: none; border-radius: 12px; font-weight: bold; font-size: 16px; box-shadow: 0 4px 6px rgba(37, 99, 235, 0.3);">
                            Get Started Now →
                        </a>
                    </div>
                    
                    <p style="color: #64748b; font-size: 14px; line-height: 1.6; margin-top: 30px;">
                        Need help getting started? Our support team is here for you. Simply click the support button in the application or reply to this email.
                    </p>
                    
                    <p style="color: #475569; font-size: 16px; margin-top: 30px;">
                        Best regards,<br>
                        <strong style="color: #2563eb;">The Mentor Connect Team</strong><br>
                        <span style="color: #64748b; font-size: 14px;">Wazir Education Society</span>
                    </p>
                </div>
                
                <!-- Footer -->
                <div style="background-color: #f8fafc; padding: 30px; text-align: center; border-top: 1px solid #e2e8f0;">
                    <p style="color: #64748b; font-size: 12px; margin: 0;">
                        © 2024 Mentor Connect - Wazir Education Society. All rights reserved.
                    </p>
                    <p style="color: #94a3b8; font-size: 11px; margin: 10px 0 0 0;">
                        This email was sent to {to_email} because you signed up for Mentor Connect.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Welcome email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Error sending welcome email: {e}")
        return False

def mentor_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_type") != "1":
            flash("Please login as mentor first!", "error")
            return redirect(url_for("signin"))
        return f(*args, **kwargs)
    return decorated_function

#-------------- signup details ----------------
class User(db.Model):
    __tablename__ = "signup_details"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=True)   # nullable for OAuth users
    user_type = db.Column(db.String(10), nullable=True)  # nullable until user selects type
    institution = db.Column(db.String(150), nullable=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=True)

    # OAuth fields
    google_id = db.Column(db.String(200), unique=True, nullable=True)
    oauth_provider = db.Column(db.String(50), nullable=True)  # 'google', 'facebook', etc.
    profile_picture_url = db.Column(db.Text, nullable=True)  # OAuth profile picture
    oauth_created_at = db.Column(db.DateTime, nullable=True)
    
    # Registration timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    #connect form another table
    mentor_profile = db.relationship("MentorProfile", backref="user", uselist=False)
    mentee_profile = db.relationship("MenteeProfile", backref="user_ref", uselist=False, foreign_keys="MenteeProfile.user_id", overlaps="mentee_profile_ref,user")
    institution_ref = db.relationship("Institution", backref="users", foreign_keys="User.institution_id")

    def __repr__(self):
        return f"<user {self.name}>"

#-------------- OTP for password reset ----------------
class PasswordResetOTP(db.Model):
    __tablename__ = "password_reset_otp"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), nullable=False)
    otp = db.Column(db.String(6), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    
    def is_expired(self):
        return datetime.utcnow() > self.expires_at

#------------table mentors details-------------------
class MentorProfile(db.Model):
    __tablename__="mentor_profile"

    id = db.Column(db.Integer, primary_key=True)

    # foregin key link to User table
    user_id= db.Column(db.Integer, db.ForeignKey("signup_details.id"),nullable=False)

    # Personal & Professional Details
    profession = db.Column(db.String(100))
    skills = db.Column(db.Text)  # New field - comma separated skills
    role = db.Column(db.String(100))  # New field - job role/position
    industry_sector = db.Column(db.String(100))  # New field - industry/sector
    organisation = db.Column(db.String(150))
    years_of_experience = db.Column(db.String(100))     
    
    # Contact Information
    whatsapp = db.Column(db.String(20))
    location = db.Column(db.String(100))  # New field - country
    
    # Education & Background
    education = db.Column(db.String(150))
    language = db.Column(db.String(100))  # Can store multiple languages comma separated
    
    # Educational Information (New)
    highest_qualification = db.Column(db.String(100))  # Bachelor's, Master's, PhD, etc.
    degree_name = db.Column(db.String(150))  # B.Tech, MBA, M.Sc, etc.
    field_of_study = db.Column(db.String(150))  # Specialization/Major
    university_name = db.Column(db.String(200))  # University or Institution name
    graduation_year = db.Column(db.String(10))  # Year of graduation
    academic_status = db.Column(db.String(50))  # Completed / Pursuing
    certifications = db.Column(db.Text)  # Professional certifications (comma separated)
    research_work = db.Column(db.Text)  # Research work or thesis title
    
    # Social Links
    linkedin_link = db.Column(db.String(200))  # New field
    github_link = db.Column(db.String(200))  # New field
    portfolio_link = db.Column(db.String(200))  # New field
    other_social_link = db.Column(db.String(200))
    
    # Mentorship Preferences
    mentorship_topics = db.Column(db.Text)  # New field - topics they can mentor on
    mentorship_type_preference = db.Column(db.String(200))  # New field - school, women, etc.
    preferred_communication = db.Column(db.String(100))  # online, offline, hybrid
    availability = db.Column(db.String(100))
    connect_frequency = db.Column(db.String(100))
    preferred_duration = db.Column(db.String(100))  # New field - 1 month, 6 months, etc.
    
    # Mentor Philosophy
    why_mentor = db.Column(db.Text)  # Changed from "why become mentor" to "why mentor"
    mentorship_philosophy = db.Column(db.Text)  # New field
    mentorship_motto = db.Column(db.String(300))  # New field
    
    # Additional Information
    additional_info = db.Column(db.Text)
    profile_picture = db.Column(db.String(100))
    criminal_certificate = db.Column(db.String(100))  # PDF file for criminal certificate (mandatory for Luxembourg)
    status = db.Column(db.String(20), default="pending")

#------------ table mentee details-------------------
class MenteeProfile(db.Model):
    __tablename__ = "mentee_profile"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)

    # Who am I? field
    who_am_i = db.Column(db.String(50))  # student, professional, entrepreneur, freelancer, career_break

    # STUDENT fields
    education_level = db.Column(db.String(50))
    institution_name = db.Column(db.String(150))
    board_university = db.Column(db.String(100))
    course_stream = db.Column(db.String(100))
    school_name = db.Column(db.String(150))
    school_board = db.Column(db.String(100))
    school_passing_year = db.Column(db.String(10))
    career_interest = db.Column(db.String(100))

    # PROFESSIONAL fields
    current_role = db.Column(db.String(100))
    industry = db.Column(db.String(100))
    years_experience = db.Column(db.String(10))
    current_organization = db.Column(db.String(150))
    key_skills = db.Column(db.Text)
    career_goal = db.Column(db.String(100))

    # ENTREPRENEUR fields
    startup_stage = db.Column(db.String(50))
    startup_name = db.Column(db.String(150))
    startup_industry = db.Column(db.String(150))
    team_size = db.Column(db.String(10))
    main_challenge = db.Column(db.Text)
    mentorship_type = db.Column(db.String(100))

    # FREELANCER fields
    freelance_skill = db.Column(db.String(150))
    freelance_experience = db.Column(db.String(50))
    freelance_platforms = db.Column(db.String(200))
    freelance_challenge = db.Column(db.String(100))

    # CAREER BREAK fields
    last_role = db.Column(db.String(150))
    career_break_reason = db.Column(db.String(200))
    restart_field = db.Column(db.String(150))
    support_expected = db.Column(db.String(100))

    # Common fields (existing)
    dob = db.Column(db.String(20))
    
    # General Details fields
    father_name = db.Column(db.String(150))
    address_line1 = db.Column(db.String(200))
    address_line2 = db.Column(db.String(200))
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    postal_code = db.Column(db.String(20))
    country = db.Column(db.String(100))
    institution = db.Column(db.String(150))
    institution_other = db.Column(db.String(150))
    
    school_college_name = db.Column(db.String(150))
    mobile_number = db.Column(db.String(20))
    mobile_country_code = db.Column(db.String(10), default="+1")
    whatsapp_number = db.Column(db.String(20))
    whatsapp_country_code = db.Column(db.String(10), default="+1")
    govt_private = db.Column(db.String(50))
    stream = db.Column(db.String(100))
    class_year = db.Column(db.String(50))
    favourite_subject = db.Column(db.String(100))
    goal = db.Column(db.Text)

    # parent info
    parent_name = db.Column(db.String(150))
    parent_mobile = db.Column(db.String(20))
    parent_mobile_country_code = db.Column(db.String(10), default="+1")
    parent_email = db.Column(db.String(150))  # Parent's email for consent
    parent_consent_status = db.Column(db.String(20), default="pending")  # pending, approved, rejected
    parent_consent_token = db.Column(db.String(200))  # Unique token for approval link
    parent_consent_date = db.Column(db.DateTime)  # Date when parent approved/rejected

    # other
    comments = db.Column(db.Text)
    mentorship_expectations = db.Column(db.Text)
    linkedin_link = db.Column(db.String(200))  # LinkedIn profile URL
    terms_agreement = db.Column(db.String(10))  # Yes / No
    profile_picture = db.Column(db.String(100))  # store image filename
    status = db.Column(db.String(20), default="pending")
    user = db.relationship("User", backref=db.backref("mentee_profile_ref", uselist=False, overlaps="user_ref"), uselist=False, overlaps="mentee_profile,user_ref")

#------------ table supervisor details-------------------
class SupervisorProfile(db.Model):
    __tablename__ = "supervisor_profile"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False, unique=True)

    organisation = db.Column(db.String(150))
    whatsapp = db.Column(db.String(20))
    location = db.Column(db.String(100))
    role = db.Column(db.String(100))
    additional_info = db.Column(db.Text)
    profile_picture = db.Column(db.String(100))

    # One-to-one relationship with User
    user = db.relationship("User", backref="supervisor_profile", uselist=False)

#------------Institution Table-------------------
class Institution(db.Model):
    __tablename__ = "institutions"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False, unique=True)  # Required - institution must be linked to user
    
    # Core institution information (linked to User signup data)
    # name and contact_email are derived from User.name and User.email and should not be editable
    
    # Profile-specific fields (editable)
    email_domain = db.Column(db.String(100), nullable=True)  # For auto-detection
    contact_person = db.Column(db.String(100))  # Can be different from institution name
    contact_phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    country = db.Column(db.String(100))
    website = db.Column(db.String(200))
    institution_type = db.Column(db.String(50), default="other")  # university, college, school, other
    status = db.Column(db.String(20), default="active")  # active, inactive
    profile_picture = db.Column(db.String(100), nullable=True)  # Store image filename
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship with User (institution admin) - via user_id
    user = db.relationship("User", backref="institution_profile", uselist=False, foreign_keys="Institution.user_id")
    
    @property
    def name(self):
        """Institution name comes from linked User.name"""
        return self.user.name if self.user else None
    
    @property
    def contact_email(self):
        """Institution email comes from linked User.email"""
        return self.user.email if self.user else None
    
    def __repr__(self):
        return f"<Institution {self.name}>"

#-------------- Profile Completion Reminder System-------------------

class ProfileCompletionReminder(db.Model):
    __tablename__ = "profile_completion_reminders"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    user_type = db.Column(db.String(20), nullable=False)  # "1" for mentor, "2" for mentee
    completion_percentage = db.Column(db.Integer)  # Percentage at time of sending
    missing_fields = db.Column(db.Text)  # JSON string of missing fields
    completed_fields = db.Column(db.Integer)  # Count of completed fields
    total_fields = db.Column(db.Integer)  # Total trackable fields
    email_subject = db.Column(db.String(200))
    email_style = db.Column(db.String(50))  # friendly, professional, motivational, achievement, community
    email_content = db.Column(db.Text)  # Full email HTML content
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)  # Track if user opened/engaged
    previous_percentage = db.Column(db.Integer, nullable=True)  # For showing improvement
    
    # Relationships
    user = db.relationship("User", backref="completion_reminders", foreign_keys="ProfileCompletionReminder.user_id")
    
    def __repr__(self):
        return f"<ProfileCompletionReminder {self.user_id} - {self.completion_percentage}%>"

#-------------- Admin Settings for Reminders -------------------

class ReminderSettings(db.Model):
    __tablename__ = "reminder_settings"
    
    id = db.Column(db.Integer, primary_key=True)
    is_enabled = db.Column(db.Boolean, default=True)  # Enable/disable reminders globally
    frequency_hours = db.Column(db.Integer, default=24)  # How often to send reminders (hours)
    min_completion_for_reminder = db.Column(db.Integer, default=0)  # Min completion % to get reminders
    max_reminders_per_user = db.Column(db.Integer, default=7)  # Max reminders before stopping
    last_run = db.Column(db.DateTime)  # Last time the scheduled job ran
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<ReminderSettings - Enabled: {self.is_enabled}, Frequency: {self.frequency_hours}h>"

#------------------mentorship request table-------------------
class MentorshipRequest(db.Model):
    __tablename__ = "mentorship_requests"
    id = db.Column(db.Integer, primary_key=True)
    mentee_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    mentor_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    
    # Details from the form
    purpose = db.Column(db.String(1000))  # career guidance / interview prep / skill development / others
    mentor_type = db.Column(db.String(20))   # anchor / special
    term = db.Column(db.String(20))          # short / long
    duration_months = db.Column(db.Integer)  # auto set depending on rules
    why_need_mentor = db.Column(db.Text, nullable=False)
    linkedin_profile = db.Column(db.String(500), nullable=True)  # optional LinkedIn or similar reference profile
    
    # Request status tracking
    mentor_status = db.Column(db.String(20), default="pending") # 'pending', 'accepted', 'rejected'
    supervisor_status = db.Column(db.String(20), default="pending") # 'pending', 'approved', 'rejected'
    final_status = db.Column(db.String(20), default="pending") # 'pending', 'approved', 'rejected'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Relationships for easy access
    mentee = db.relationship("User", foreign_keys=[mentee_id], backref="sent_requests")
    mentor = db.relationship("User", foreign_keys=[mentor_id], backref="received_requests")

#------------Notification table-------------------
class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(300))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id], backref="notifications")

def create_notification(user_id, message, link=None):
    """Persist an in-app notification for a user. Never throws."""
    try:
        notification = Notification(user_id=user_id, message=message, link=link)
        db.session.add(notification)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print("Notification Error:", e)
        return False

def notify_mentorship_connection(req):
    """Notify both mentor and mentee when a mentorship is fully connected.
    Fully connected = supervisor approved AND final approved.
    Returns True if notifications were created."""
    if not req:
        return False
    is_connected = (
        req.supervisor_status == "approved"
        and req.final_status == "approved"
    )
    if not is_connected:
        return False

    mentor = req.mentor
    mentee = req.mentee
    sent = False

    if mentee:
        mentor_name = mentor.name if mentor else "your mentor"
        mentee_link = url_for("my_mentors")
        if create_notification(
            mentee.id,
            f"Your mentorship with {mentor_name} is now connected and active.",
            mentee_link
        ):
            sent = True

    if mentor:
        mentee_name = mentee.name if mentee else "your mentee"
        mentor_link = url_for("my_mentees")
        if create_notification(
            mentor.id,
            f"You are now connected with mentee {mentee_name}.",
            mentor_link
        ):
            sent = True

    return sent

def send_mentorship_connected_email(req):
    """Send a connection email to both the mentee and mentor when a mentorship
    is fully established (supervisor approved AND final approved).

    Uses the standard SMTP configuration already present in the app.
    Never throws -- logs and returns True/False per recipient.
    """
    if not req:
        return False

    mentor = req.mentor
    mentee = req.mentee
    sent = False

    mentee_name = mentee.name if mentee else "Mentee"
    mentor_name = mentor.name if mentor else "Mentor"
    purpose = req.purpose or "career guidance"
    duration = req.duration_months if req.duration_months else "short-term"

    def build_mentee_email():
        return (
            f"<p style=\"color: #475569; font-size: 16px; line-height: 1.6;\">"
            f"Your mentorship with <strong>{mentor_name}</strong> is now <strong>active</strong>!"
            f" This partnership will focus on <strong>{purpose}</strong> for a {duration}-month journey.</p>"
        )

    def build_mentor_email():
        return (
            f"<p style=\"color: #475569; font-size: 16px; line-height: 1.6;\">"
            f"You are now connected with mentee <strong>{mentee_name}</strong>."
            f" Your mentorship will focus on <strong>{purpose}</strong> for a {duration}-month journey.</p>"
        )

    def build_shell(subject, greeting, highlight_block, dashboard_link, dashboard_label):
        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f8fafc;">
            <div style="max-width: 600px; margin: 0 auto; background-color: white; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                <div style="background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%); padding: 40px 20px; text-align: center;">
                    <h1 style="color: white; margin: 0; font-size: 28px;">{subject}</h1>
                    <p style="color: #e0e7ff; margin: 10px 0 0 0; font-size: 16px;">Mentorship Connected</p>
                </div>
                <div style="padding: 40px 30px;">
                    <h2 style="color: #1e293b; margin-top: 0;">{greeting}</h2>
                    {highlight_block}
                    <div style="background-color: #f1f5f9; border-left: 4px solid #2563eb; padding: 20px; margin: 30px 0; border-radius: 8px;">
                        <h3 style="color: #1e293b; margin-top: 0; font-size: 18px;">🚀 Your Mentorship Details</h3>
                        <ul style="color: #475569; line-height: 1.8; margin: 10px 0; padding-left: 20px;">
                            <li><strong>Purpose:</strong> {purpose}</li>
                            <li><strong>Duration:</strong> {duration} months</li>
                        </ul>
                    </div>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{dashboard_link}" style="display: inline-block; background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%); color: white; padding: 16px 40px; text-decoration: none; border-radius: 12px; font-weight: bold; font-size: 16px;">
                            {dashboard_label} →
                        </a>
                    </div>
                    <p style="color: #475569; font-size: 16px; margin-top: 30px;">
                        Best regards,<br>
                        <strong style="color: #2563eb;">The Mentor Connect Team</strong><br>
                        <span style="color: #64748b; font-size: 14px;">Wazir Education Society</span>
                    </p>
                </div>
                <div style="background-color: #f8fafc; padding: 30px; text-align: center; border-top: 1px solid #e2e8f0;">
                    <p style="color: #64748b; font-size: 12px; margin: 0;">
                        © 2026 Mentor Connect - Wazir Education Society. All rights reserved.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

    # Email to the mentee
    if mentee and mentee.email:
        try:
            mentee_subject = f"Your Mentorship is Now Connected! 🎉"
            mentee_html = build_shell(
                mentee_subject,
                f"Hi {mentee.name},",
                build_mentee_email(),
                url_for("my_mentors", _external=True),
                "View My Mentor",
            )
            if send_email_reminder(mentee.email, mentee_subject, mentee_html):
                sent = True
        except Exception as e:
            print(f"Mentee connection email error: {e}")

    # Email to the mentor
    if mentor and mentor.email:
        try:
            mentor_subject = f"You're Now Connected with a New Mentee! 🎉"
            mentor_html = build_shell(
                mentor_subject,
                f"Hi {mentor.name},",
                build_mentor_email(),
                url_for("my_mentees", _external=True),
                "View My Mentee",
            )
            if send_email_reminder(mentor.email, mentor_subject, mentor_html):
                sent = True
        except Exception as e:
            print(f"Mentor connection email error: {e}")

    return sent

#------------Meeting Request table-------------------
class MeetingRequest(db.Model):
    __tablename__ = "meeting_requests"
    id = db.Column(db.Integer, primary_key=True)

    # Who created the request (requester) and who it's for
    requester_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    requested_to_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)

    # Meeting details
    meeting_title = db.Column(db.String(200), nullable=False)
    meeting_description = db.Column(db.Text)
    meeting_date = db.Column(db.Date, nullable=False)
    meeting_time = db.Column(db.Time, nullable=False)   # start time
    meeting_duration = db.Column(db.Integer, default=60)  # in minutes

    # Google Calendar info
    meet_link = db.Column(db.String(500), nullable=True)
    gcal_event_id = db.Column(db.String(200), nullable=True)

    # Status tracking
    status = db.Column(db.String(20), default="pending")  # 'pending', 'approved', 'rejected', 'rescheduled'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Reschedule fields
    is_rescheduled = db.Column(db.Boolean, default=False)
    reschedule_reason = db.Column(db.Text, nullable=True)  # Required if rescheduling within 8 hours
    original_date = db.Column(db.Date, nullable=True)  # Store original date before reschedule
    original_time = db.Column(db.Time, nullable=True)  # Store original time before reschedule
    rescheduled_at = db.Column(db.DateTime, nullable=True)  # When was it rescheduled
    rescheduled_by_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=True)

    # Relationships
    requester = db.relationship("User", foreign_keys=[requester_id], backref="sent_meeting_requests")
    requested_to = db.relationship("User", foreign_keys=[requested_to_id], backref="received_meeting_requests")
    rescheduled_by = db.relationship("User", foreign_keys=[rescheduled_by_id])


#------------Master Task Table-------------------
class MasterTask(db.Model):
    __tablename__ = "MasterTask"
    
    id = db.Column(db.Integer, primary_key=True)
    meeting_number = db.Column(db.Integer, nullable=False, unique=True)
    month = db.Column(db.String(50), nullable=False)
    journey_phase = db.Column(db.String(200), nullable=False)
    purpose_of_call = db.Column(db.Text, nullable=False)
    mentor_focus = db.Column(db.Text, nullable=False)
    mentee_focus = db.Column(db.Text, nullable=False)
    program_incharge_actions = db.Column(db.Text, nullable=False)
    meeting_plan_overview = db.Column(db.Text, nullable=False)
    
    def __repr__(self):
        return f"<MeetingStructure {self.meeting_number}: {self.month}>"

class MenteeTask(db.Model):
    __tablename__ = "mentee_tasks"
    
    id = db.Column(db.Integer, primary_key=True)
    mentee_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    mentor_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey("MasterTask.id"), nullable=False)
    meeting_number = db.Column(db.Integer, nullable=False)
    month = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default="pending")
    progress = db.Column(db.Integer, default=0)
    assigned_date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime)
    completed_date = db.Column(db.DateTime)
    
    # Relationships
    mentee = db.relationship("User", foreign_keys=[mentee_id])
    mentor = db.relationship("User", foreign_keys=[mentor_id])
    master_task = db.relationship("MasterTask")

class PersonalTask(db.Model):
    __tablename__ = "personal_tasks"
    
    id = db.Column(db.Integer, primary_key=True)
    mentee_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    mentor_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    due_date = db.Column(db.DateTime)
    priority = db.Column(db.String(20), default="medium")  # low, medium, high
    status = db.Column(db.String(20), default="pending")  # pending, in-progress, completed
    progress = db.Column(db.Integer, default=0)  # 0-100%
    created_date = db.Column(db.DateTime, default=datetime.utcnow)
    completed_date = db.Column(db.DateTime)
    
    # Relationship
    mentee = db.relationship("User", foreign_keys=[mentee_id])
    mentor = db.relationship("User", foreign_keys=[mentor_id])


#------------Task feedback Table-------------------
class TaskRating(db.Model):
    __tablename__ = "task_ratings"
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, nullable=False)  # Can be from MenteeTask or PersonalTask
    task_type = db.Column(db.String(20), nullable=False)  # 'master' or 'personal'
    mentee_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    mentor_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    
    # Rating (1-5 stars)
    rating = db.Column(db.Integer, nullable=False)  # 1 to 5
    
    # Feedback
    feedback = db.Column(db.Text)
    strengths = db.Column(db.Text)  # What mentee did well
    improvements = db.Column(db.Text)  # Areas for improvement
    
    # Timestamps
    rated_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    mentee = db.relationship("User", foreign_keys=[mentee_id])
    mentor = db.relationship("User", foreign_keys=[mentor_id])
    
    def __repr__(self):
        return f"<TaskRating {self.rating}/5 for task {self.task_id}>"


#------------Mentee Feedback Table-------------------
class MenteeFeedback(db.Model):
    __tablename__ = "mentee_feedbacks"

    id = db.Column(db.Integer, primary_key=True)
    mentee_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    task_id = db.Column(db.Integer, nullable=False)
    task_type = db.Column(db.String(20), nullable=False)  # 'master' or 'personal'
    rating = db.Column(db.Integer)  # 1 to 5
    mentor_rating = db.Column(db.Integer)  # 1 to 5
    text = db.Column(db.Text)
    challenges = db.Column(db.Text)
    next_steps = db.Column(db.Text)
    extra = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    mentee = db.relationship("User", foreign_keys=[mentee_id])

    def to_dict(self):
        return {
            'id': self.id,
            'mentee_id': self.mentee_id,
            'mentee_name': self.mentee.name if self.mentee else '',
            'task_type': self.task_type,
            'task_id': self.task_id,
            'rating': str(self.rating) if self.rating is not None else '',
            'mentor_rating': str(self.mentor_rating) if self.mentor_rating is not None else '',
            'text': self.text or '',
            'challenges': self.challenges or '',
            'nextSteps': self.next_steps or '',
            'extra': self.extra or '',
            'date': self.created_at.isoformat() if self.created_at else ''
        }


#------------Mentor Reflection Table-------------------
class MentorReflection(db.Model):
    __tablename__ = "mentor_reflections"

    id = db.Column(db.Integer, primary_key=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    task_id = db.Column(db.Integer, nullable=False)
    task_type = db.Column(db.String(20), nullable=False)  # 'master' or 'personal'
    text = db.Column(db.Text)
    extra = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    mentor = db.relationship("User", foreign_keys=[mentor_id])

    def to_dict(self):
        return {
            'id': self.id,
            'mentor_id': self.mentor_id,
            'mentor_name': self.mentor.name if self.mentor else '',
            'task_type': self.task_type,
            'task_id': self.task_id,
            'text': self.text or '',
            'extra': self.extra or '',
            'date': self.created_at.isoformat() if self.created_at else ''
        }


#------------Institution Reflection Table-------------------
class InstitutionReflection(db.Model):
    __tablename__ = "institution_reflections"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, nullable=False)
    task_id = db.Column(db.Integer, nullable=False)
    task_type = db.Column(db.String(20), nullable=False)  # 'master' or 'personal'
    text = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'institution_id': self.institution_id,
            'task_type': self.task_type,
            'task_id': self.task_id,
            'text': self.text or '',
            'notes': self.notes or '',
            'date': self.created_at.isoformat() if self.created_at else ''
        }


#------------Chat System Tables-------------------
class ChatConversation(db.Model):
    """
    Represents a conversation between two users.
    """
    __tablename__ = "chat_conversations"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Conversation type: 'direct' (1-to-1)
    conversation_type = db.Column(db.String(20), default="direct", nullable=False)
    
    # For direct conversations: participant IDs (always stored in order: smaller ID first)
    participant1_id = db.Column(db.Integer, db.ForeignKey("signup_details.id", ondelete="CASCADE"), nullable=False)
    participant2_id = db.Column(db.Integer, db.ForeignKey("signup_details.id", ondelete="CASCADE"), nullable=False)
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    participant1 = db.relationship("User", foreign_keys=[participant1_id], backref="conversations_as_p1")
    participant2 = db.relationship("User", foreign_keys=[participant2_id], backref="conversations_as_p2")
    messages = db.relationship("ChatMessage", backref="conversation", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<ChatConversation {self.id}>"


class ChatMessage(db.Model):
    """
    Represents a single message in a conversation.
    """
    __tablename__ = "chat_messages"
    
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("signup_details.id", ondelete="CASCADE"), nullable=False)
    
    # Message content
    content = db.Column(db.Text, nullable=False)
    
    # Message metadata
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    sender = db.relationship("User", backref="sent_messages")
    
    def __repr__(self):
        return f"<ChatMessage {self.id}>"


#------------Resources Hub - Notes Table-------------------
_TAG_PREFIX = "@@TAGS@@"

def _parse_tags_from_content(content):
    """Extract tag metadata from content prefix. Returns (tags_dict, clean_content)."""
    if content and content.startswith(_TAG_PREFIX):
        line_end = content.find("\n")
        if line_end == -1:
            line_end = len(content)
        json_str = content[len(_TAG_PREFIX):line_end].strip()
        clean = content[line_end + 1:] if line_end < len(content) else ""
        try:
            import json as _json
            tags = _json.loads(json_str)
            return tags, clean.strip()
        except Exception:
            return {}, content
    return {}, content or ""


class ResourceNote(db.Model):
    """
    Notes written in the Resources Hub.
    Can tag a mentor, mentee, supervisor, or institution on a note.
    """
    __tablename__ = "resource_notes"

    id = db.Column(db.Integer, primary_key=True)

    # Who wrote the note (user id of creator)
    mentee_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)

    # Called/tagged mentor
    mentor_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=True)

    # Tagged institution
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=True)

    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    mentee = db.relationship("User", foreign_keys=[mentee_id], backref="note_about_me")
    mentor = db.relationship("User", foreign_keys=[mentor_id], backref="tagged_notes")
    institution = db.relationship("Institution", foreign_keys=[institution_id], backref="tagged_notes")

    @property
    def tags_dict(self):
        tags, _ = _parse_tags_from_content(self.content)
        return tags

    @property
    def clean_content(self):
        _, clean = _parse_tags_from_content(self.content)
        return clean

    def __repr__(self):
        return f"<ResourceNote {self.id}: {self.title}>"


class MentorSourcingRequest(db.Model):
    """
    Mentor sourcing request or contact/feedback submitted by a mentee when they cannot find the mentor they need.
    """
    __tablename__ = "mentor_sourcing_requests"

    id = db.Column(db.Integer, primary_key=True)
    mentee_id = db.Column(db.Integer, db.ForeignKey("signup_details.id"), nullable=False)
    name = db.Column(db.String(150), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    target_role = db.Column(db.String(200), nullable=True)
    target_industry = db.Column(db.String(200), nullable=True)
    skills_needed = db.Column(db.String(300), nullable=True)
    preferred_experience = db.Column(db.String(100), nullable=True)
    linkedin_profile = db.Column(db.String(500), nullable=True)  # optional LinkedIn or similar reference profile
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default="pending")  # pending, sourcing, resolved
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    mentee = db.relationship("User", foreign_keys=[mentee_id], backref="mentor_sourcing_requests")

    def __repr__(self):
        return f"<MentorSourcingRequest {self.id}: {self.target_role} - {self.target_industry}>"


# ============================================================
# AUTOMATIC SCHEMA MIGRATION / SELF-HEALING
# ============================================================
_schema_migrated = False

def auto_migrate_schema():
    """Safely ensure newly added columns and tables exist in the database upon startup."""
    global _schema_migrated
    if _schema_migrated:
        return
    try:
        from sqlalchemy import inspect, text
        with app.app_context():
            inspector = inspect(db.engine)
            existing_tables = set(inspector.get_table_names())

            # 1. Ensure any missing tables in metadata are created
            db.create_all()

            # 2. Add missing columns for any declared models
            for table_name, table in db.metadata.tables.items():
                if table_name in existing_tables:
                    existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
                    for col in table.columns:
                        if col.name not in existing_cols:
                            try:
                                col_type = col.type.compile(db.engine.dialect)
                                with db.engine.connect() as conn:
                                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}"))
                                    conn.commit()
                                print(f"✅ Auto-migrated column: {table_name}.{col.name} ({col_type})")
                            except Exception as col_err:
                                print(f"⚠️ Notice adding column {table_name}.{col.name}: {col_err}")
            _schema_migrated = True
    except Exception as e:
        print(f"⚠️ Auto-migrate schema notice: {e}")

try:
    auto_migrate_schema()
except Exception:
    pass

@app.before_request
def ensure_schema_on_request():
    global _schema_migrated
    if not _schema_migrated:
        auto_migrate_schema()


def assign_master_tasks_to_mentorship(mentorship_request):
    print("🔧 assign_master_tasks_to_mentorship function called")
    
    try:
        # Check mentorship request data
        print(f"📋 Mentorship Details:")
        print(f"   - Mentee ID: {mentorship_request.mentee_id}")
        print(f"   - Mentor ID: {mentorship_request.mentor_id}") 
        print(f"   - Duration: {mentorship_request.duration_months} months")
        
        # ✅ Use current time since created_at doesn't exist or is None
        start_date = datetime.utcnow()
        print(f"   - Start Date (Current Time): {start_date}")
        
        # Get master tasks
        master_tasks = MasterTask.query\
            .order_by(MasterTask.meeting_number)\
            .limit(20)\
            .all()
        
        print(f"📁 Top {len(master_tasks)} master tasks found (limited to 20)")
        
        if not master_tasks:
            print("❌ NO MASTER TASKS IN DATABASE!")
            return []
        
        assigned_tasks = []
        start_date = datetime.utcnow()

        
        for i, master_task in enumerate(master_tasks):
            print(f"\n🎯 Processing Task {i+1}:")
            print(f"   Month: {master_task.month}")
            print(f"   Meeting Number: {master_task.meeting_number}")
            print(f"   Purpose: {master_task.purpose_of_call[:50]}...")  # ✅ Use existing field
            
            due_date = calculate_due_date(start_date, master_task.month)
            print(f"   Final Due Date: {due_date}")
            
            # Create mentee task
            mentee_task = MenteeTask(
                mentee_id=mentorship_request.mentee_id,
                mentor_id=mentorship_request.mentor_id,
                task_id=master_task.id,
                meeting_number=master_task.meeting_number,
                month=master_task.month,
                due_date=due_date
            )
            
            db.session.add(mentee_task)
            assigned_tasks.append(mentee_task)
        
        # Flush se pehle - let outer function handle commit
        print(f"\n💾 Flushing {len(assigned_tasks)} tasks to database...")
        db.session.flush()
        print("✅ Database flush successful!")
        
        return assigned_tasks
        
    except Exception as e:
        print(f"❌ ERROR in task assignment: {str(e)}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return []

def calculate_due_date(start_date, month_string):
    """
    Month string (e.g., "Month 1", "Month 2") ko due date mein convert kare
    """
    try:
        print(f"📅 CALCULATION STARTED:")
        print(f"   Start Date: {start_date}")
        print(f"   Month String: {month_string}")
        
        # ✅ Ensure start_date is not None
        if start_date is None:
            start_date = datetime.utcnow()
            print(f"   ⚠️  Start date was None, using current time: {start_date}")
        
        # Month string se number nikalne ka logic
        if "Month" in month_string:
            month_num = int(month_string.split(" ")[1])
        else:
            # Try to extract any number from string
            import re
            numbers = re.findall(r'\d+', month_string)
            month_num = int(numbers[0]) if numbers else 1
        
        print(f"   Extracted month number: {month_num}")
        
        # Start date se days add karo (30 days per month)
        days_to_add = 30 * month_num
        print(f"   Days to add: {days_to_add}")
        
        due_date = start_date + timedelta(days=days_to_add)
        
        print(f"   Calculated due date: {due_date}")
        print("📅 CALCULATION COMPLETED\n")
        
        return due_date
        
    except Exception as e:
        print(f"❌ Error in calculate_due_date: {str(e)}")
        import traceback
        traceback.print_exc()
        # Fallback: 30 days from current time
        return datetime.utcnow() + timedelta(days=30)

def calculate_due_date(start_date, month_string):
    """
    Month string (e.g., "Month 1", "Month 2") ko due date mein convert kare
    """
    try:
        print(f"📅 CALCULATION STARTED:")
        print(f"   Start Date: {start_date}")
        print(f"   Month String: {month_string}")
        print(f"   Start Date Type: {type(start_date)}")
        
        # Month string se number nikalne ka logic
        if "Month" in month_string:
            month_num = int(month_string.split(" ")[1])
        else:
            # Try to extract any number from string
            import re
            numbers = re.findall(r'\d+', month_string)
            month_num = int(numbers[0]) if numbers else 1
        
        print(f"   Extracted month number: {month_num}")
        
        # Start date se days add karo (30 days per month)
        days_to_add = 30 * month_num
        print(f"   Days to add: {days_to_add}")
        
        due_date = start_date + timedelta(days=days_to_add)
        
        print(f"   Calculated due date: {due_date}")
        print(f"   Due Date Type: {type(due_date)}")
        print("📅 CALCULATION COMPLETED\n")
        
        return due_date
        
    except Exception as e:
        print(f"❌ Error in calculate_due_date: {str(e)}")
        import traceback
        traceback.print_exc()
        # Fallback: 30 days from start
        return start_date + timedelta(days=30)

# Context processor to make profile_complete available in all templates
@app.context_processor
def inject_profile_complete():
    profile_complete = True  # Default to True (no popup)
    
    if "email" in session and session.get("user_type") in ["1", "2"]:
        user = User.query.filter_by(email=session["email"]).first()
        if user:
            profile_complete = check_profile_complete(user.id, session.get("user_type"))    
    return dict(profile_complete=profile_complete)


# ---------- Profile Completion Check Function ----------
def check_profile_complete(user_id, user_type, profile_obj=None):
    """
    Check if user profile is FULLY complete with ALL mandatory fields
    Returns True only if ALL required fields are filled, False otherwise
    """
    if user_type == "1":  # Mentor
        profile = profile_obj if profile_obj is not None else MentorProfile.query.filter_by(user_id=user_id).first()
        if profile:
            # Check if ALL mandatory fields are filled (including profile picture)
            # Use 'or' with empty string to handle None values gracefully
            has_all_required = all([
                profile.profession, 
                profile.organisation, 
                profile.whatsapp,
                profile.location,
                (profile.education or "Not specified"),  # Handle None gracefully
                profile.years_of_experience,
                profile.skills,
                profile.role,
                profile.industry_sector,
                profile.language,
                profile.linkedin_link,
                profile.mentorship_topics,
                profile.mentorship_type_preference,
                profile.preferred_communication,
                profile.availability,
                profile.connect_frequency,
                profile.preferred_duration,
                profile.why_mentor,
                profile.mentorship_philosophy,
                profile.mentorship_motto,
                profile.profile_picture  # Profile picture is now mandatory
            ])
            return has_all_required
        return False
    
    elif user_type == "2":  # Mentee
        profile = profile_obj if profile_obj is not None else MenteeProfile.query.filter_by(user_id=user_id).first()
        print(f"📊 Mentee profile found: {profile is not None}")
        if profile:
            # Check if ALL mandatory fields are filled (including profile picture)
            # General Details mandatory fields
            has_all_required = all([
                profile.city,
                profile.state,
                profile.country,
                # Common mandatory fields
                profile.mobile_number,
                profile.mentorship_expectations,
                profile.terms_agreement,
                profile.profile_picture,  # Profile picture is now mandatory
                # Who am I must be selected
                profile.who_am_i
            ])
            print(f"✅ Mentee profile complete: {has_all_required}")
            return has_all_required
        print("❌ No mentee profile found")
        return False
    
    elif user_type == "0":  # Supervisor
        profile = SupervisorProfile.query.filter_by(user_id=user_id).first()
        print(f"📊 Supervisor profile found: {profile is not None}")
        if profile:
            has_all_required = all([
                profile.organisation,
                profile.whatsapp,
                profile.location,
                profile.role,
                profile.additional_info,
                profile.profile_picture  # Profile picture is now mandatory
            ])
            print(f"✅ Supervisor profile complete: {has_all_required}")
            return has_all_required
        print("❌ No supervisor profile found")
        return False
    
    elif user_type == "3":  # Institution
        institution = Institution.query.filter_by(user_id=user_id).first()
        print(f"📊 Institution profile found: {institution is not None}")
        if institution:
            has_all_required = all([
                institution.name,
                institution.contact_person,
                institution.contact_email,
                institution.contact_phone,
                institution.address,
                institution.city,
                institution.state,
                institution.country,
                institution.profile_picture  # Profile picture is now mandatory
            ])
            print(f"✅ Institution profile complete: {has_all_required}")
            return has_all_required
        print("❌ No institution profile found")
        return False
    
    print(f"⚠️ Unknown user type: {user_type}")
    return True  # Default to True for unknown types (no popup)

# Decorator to enforce profile completion
def profile_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "email" not in session:
            return redirect(url_for("signin"))
        
        user = User.query.filter_by(email=session["email"]).first()
        user_type = session.get("user_type")
        
        if not user:
            return redirect(url_for("signin"))
        
        # Check if profile is complete
        if not check_profile_complete(user.id, user_type):
            flash("Please complete your profile first before accessing this section.", "warning")
            # Redirect to appropriate profile edit page
            if user_type == "1":
                return redirect(url_for("editmentorprofile"))
            elif user_type == "2":
                return redirect(url_for("editmenteeprofile"))
            elif user_type == "0":
                return redirect(url_for("editsupervisorprofile"))
            elif user_type == "3":
                return redirect(url_for("editinstitutionprofile"))
        
        return f(*args, **kwargs)
    return decorated_function

#-------------HOME----------------
@app.route("/")
def home():
    # Redirect to signin as the direct entry point
    return redirect(url_for("signin"))

#--------------SIGNUP----------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Account creation page: renders the signup page featuring Google Sign-Up."""
    if request.method == "POST":
        return redirect(url_for("google_login"))

    return render_template("auth/signup.html")

#--------------SIGNIN----------------
@app.route("/signin", methods=["GET", "POST"])
def signin():
    if request.method == "POST":
        session.permanent = True
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        # fetch user from "database"
        user = User.query.filter(db.func.lower(User.email) == email).first()

        # Check if user exists
        if not user:
            flash("User not found! Please check your email or sign up first.", "error")
            return render_template("auth/signin.html")

        # Check password
        if not check_password_hash(user.password, password):
            flash("Incorrect password! Please try again.", "error")
            return render_template("auth/signin.html")

        # Save session
        user_type_str = str(user.user_type).strip() if user.user_type is not None else ""
        session["email"] = user.email
        session["user_type"] = user_type_str
        session["user_id"] = user.id
        session["user_name"] = user.name

        # Redirect based on role
        if user_type_str == "1":
            return redirect(url_for("mentordashboard"))
        elif user_type_str == "2":
            return redirect(url_for("menteedashboard"))
        elif user_type_str == "0":
            return redirect(url_for("supervisordashboard"))
        elif user_type_str == "3":
            return redirect(url_for("institutiondashboard"))
        
        return redirect(url_for("home"))

   
    return render_template("auth/signin.html")

# ------------------- FORGOT PASSWORD -------------------
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    """Step 1: Request OTP"""
    if request.method == "POST":
        email = request.form.get("email")
        
        # Check if user exists
        user = User.query.filter_by(email=email).first()
        if not user:
            flash("Email not found. Please check and try again.", "error")
            return redirect(url_for("forgot_password"))
        
        # Generate 6-digit OTP
        otp = str(random.randint(100000, 999999))
        
        # Delete any existing OTP for this email
        PasswordResetOTP.query.filter_by(email=email).delete()
        
        # Save OTP to database with 10-minute expiry
        otp_record = PasswordResetOTP(
            email=email,
            otp=otp,
            expires_at=datetime.utcnow() + timedelta(minutes=10)
        )
        db.session.add(otp_record)
        db.session.commit()
        
        # Send OTP via email
        if send_otp_email(email, otp):
            flash("OTP sent to your email. Please check your inbox.", "success")
            return redirect(url_for("verify_otp", email=email))
        else:
            flash("Failed to send OTP. Please try again later.", "error")
            return redirect(url_for("forgot_password"))
    
    return render_template("auth/forgot_password.html")

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    """Step 2: Verify OTP"""
    email = request.args.get("email") or request.form.get("email")
    
    if not email:
        flash("Invalid request", "error")
        return redirect(url_for("forgot_password"))
    
    if request.method == "POST":
        otp_entered = request.form.get("otp")
        
        # Find OTP record
        otp_record = PasswordResetOTP.query.filter_by(email=email).first()
        
        if not otp_record:
            flash("OTP not found. Please request a new one.", "error")
            return redirect(url_for("forgot_password"))
        
        # Check if OTP is expired
        if otp_record.is_expired():
            db.session.delete(otp_record)
            db.session.commit()
            flash("OTP has expired. Please request a new one.", "error")
            return redirect(url_for("forgot_password"))
        
        # Verify OTP
        if otp_record.otp != otp_entered:
            flash("Invalid OTP. Please try again.", "error")
            return render_template("auth/verify_otp.html", email=email)
        
        # OTP verified - redirect to reset password
        flash("OTP verified successfully!", "success")
        return redirect(url_for("reset_password", email=email, token=otp_record.otp))
    
    return render_template("auth/verify_otp.html", email=email)

@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    """Step 3: Reset Password"""
    email = request.args.get("email") or request.form.get("email")
    token = request.args.get("token") or request.form.get("token")
    
    if not email or not token:
        flash("Invalid request", "error")
        return redirect(url_for("forgot_password"))
    
    # Verify token still exists and is valid
    otp_record = PasswordResetOTP.query.filter_by(email=email, otp=token).first()
    if not otp_record or otp_record.is_expired():
        flash("Session expired. Please start again.", "error")
        return redirect(url_for("forgot_password"))
    
    if request.method == "POST":
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        
        # Validate passwords
        if not new_password or not confirm_password:
            flash("Please fill all fields", "error")
            return render_template("auth/reset_password.html", email=email, token=token)
        
        if new_password != confirm_password:
            flash("Passwords do not match", "error")
            return render_template("auth/reset_password.html", email=email, token=token)
        
        if len(new_password) < 6:
            flash("Password must be at least 6 characters long", "error")
            return render_template("auth/reset_password.html", email=email, token=token)
        
        # Update user password
        user = User.query.filter_by(email=email).first()
        if not user:
            flash("User not found", "error")
            return redirect(url_for("forgot_password"))
        
        # Hash and save new password
        user.password = generate_password_hash(new_password)
        
        # Delete OTP record
        db.session.delete(otp_record)
        db.session.commit()
        
        flash("Password reset successfully! You can now login with your new password.", "success")
        return redirect(url_for("signin"))
    
    return render_template("auth/reset_password.html", email=email, token=token)

# ------------------- PARENT CONSENT FOR UNDER 18 MENTEES -------------------
@app.route("/parent_consent/<token>", methods=["GET", "POST"])
def parent_consent_approval(token):
    """Parent approval page for under-18 mentees"""
    # Find mentee profile by consent token
    profile = MenteeProfile.query.filter_by(parent_consent_token=token).first()
    
    if not profile:
        flash("Invalid or expired consent link.", "error")
        return redirect(url_for("home"))
    
    # Get mentee user details
    mentee = User.query.get(profile.user_id)
    if not mentee:
        flash("Mentee not found.", "error")
        return redirect(url_for("home"))
    
    # Check if already approved/rejected
    if profile.parent_consent_status in ["approved", "rejected"]:
        status_message = "approved" if profile.parent_consent_status == "approved" else "rejected"
        return render_template("parent_consent_status.html", 
                             status=profile.parent_consent_status,
                             mentee_name=mentee.name,
                             consent_date=profile.parent_consent_date)
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "approve":
            profile.parent_consent_status = "approved"
            profile.parent_consent_date = datetime.now()
            db.session.commit()
            
            flash(f"You have approved {mentee.name}'s participation in the mentorship program!", "success")
            return render_template("parent_consent_status.html", 
                                 status="approved",
                                 mentee_name=mentee.name,
                                 consent_date=profile.parent_consent_date)
        
        elif action == "reject":
            profile.parent_consent_status = "rejected"
            profile.parent_consent_date = datetime.now()
            db.session.commit()
            
            flash(f"You have rejected {mentee.name}'s participation in the mentorship program.", "info")
            return render_template("parent_consent_status.html", 
                                 status="rejected",
                                 mentee_name=mentee.name,
                                 consent_date=profile.parent_consent_date)
    
    # Calculate age
    age = calculate_age(profile.dob) if profile.dob else None
    
    # GET request - show approval form
    return render_template("parent_consent_approval.html",
                         mentee=mentee,
                         profile=profile,
                         age=age,
                         parent_email=profile.parent_email)

# ------------------- GOOGLE OAUTH LOGIN -------------------
@app.route("/google_login")
def google_login():
    """Redirect to Google OAuth consent screen for login"""
    # Check if user is already logged in
    if "email" in session and "user_id" in session:
        user = User.query.get(session["user_id"])
        if user:
            # User already logged in, redirect to dashboard
            if user.user_type == "1":
                return redirect(url_for("mentordashboard"))
            elif user.user_type == "2":
                return redirect(url_for("menteedashboard"))
            elif user.user_type == "0":
                return redirect(url_for("supervisordashboard"))
            elif user.user_type == "3":
                return redirect(url_for("institutiondashboard"))
            else:
                return redirect(url_for("select_user_type"))
    
    redirect_uri = get_current_redirect_uri()
    flow = get_google_flow(LOGIN_SCOPES, redirect_uri)
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='select_account'  # Allow user to select account but skip consent if already authorized
    )
    session['state'] = state
    session['oauth_type'] = 'login'  # Mark this as login flow
    return redirect(authorization_url)

@app.route("/callback")
def callback():
    """Handle Google OAuth callback"""
    print("\n" + "="*60)
    print("🔄 CALLBACK ROUTE CALLED")
    print("="*60)
    
    try:
        print(f"📍 Step 1: Getting state from session")
        state = session.get('state')
        print(f"   State: {state}")
        
        print(f"📍 Step 2: Creating Flow from client secrets or env vars")
        redirect_uri = get_current_redirect_uri()
        flow = get_google_flow(LOGIN_SCOPES, redirect_uri, state=state)
        print(f"   ✅ Flow created")
        
        print(f"📍 Step 3: Getting authorization response")
        authorization_response = request.url
        print(f"   URL: {authorization_response}")
        
        print(f"📍 Step 4: Fetching token")
        # Set environment variable to allow scope changes
        os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
        flow.fetch_token(authorization_response=authorization_response)
        print(f"   ✅ Token fetched")
        
        print(f"📍 Step 5: Getting credentials")
        credentials = flow.credentials
        access_token = credentials.token
        print(f"   ✅ Credentials obtained")
        print(f"   Token: {access_token[:30]}..." if access_token else "   No token")
        
        print(f"📍 Step 6: Getting user info via HTTP request")
        # Use requests library to get user info directly with access token
        import requests as http_requests
        
        headers = {'Authorization': f'Bearer {access_token}'}
        user_info_response = http_requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers=headers
        )
        
        print(f"   Response status: {user_info_response.status_code}")
        
        if user_info_response.status_code != 200:
            print(f"   ❌ Error response: {user_info_response.text}")
            flash("Error getting user info from Google. Please try again.", "error")
            return redirect(url_for("signin"))
        
        user_info = user_info_response.json()
        print(f"   ✅ User info retrieved")
        
        google_id = user_info.get('id')
        email = (user_info.get('email') or "").strip().lower()
        name = user_info.get('name', email.split('@')[0] if email else 'User')
        picture_url = user_info.get('picture')
        
        print(f"\n📊 Google User Data:")
        print(f"   Name: {name}")
        print(f"   Email: {email}")
        print(f"   Google ID: {google_id}")
        print(f"   Picture: {picture_url}")
        
        if not email:
            print(f"   ❌ ERROR: No email in response!")
            flash("Could not get email from Google. Please try again.", "error")
            return redirect(url_for("signin"))
        
        print(f"\n📍 Step 7: Checking if user exists in database")
        user = User.query.filter(db.func.lower(User.email) == email).first()
        
        # Duplicate-identity guard: Gmail ignores dots and '+tag' suffixes, so
        # 'nida.p+x@gmail.com' is the SAME mailbox as 'nidap@gmail.com'. Match
        # variants too so nobody can create a second account for one email.
        if not user:
            canonical = _canonical_email(email)
            for candidate in User.query.all():
                if _canonical_email(candidate.email) == canonical:
                    user = candidate
                    break
        
        if user:
            # Case-insensitive check: same canonical email = same person
            if _canonical_email(user.email) != _canonical_email(email):
                print(f"   ⛔ Duplicate blocked: '{email}' is a variant of existing account '{user.email}'")
                flash("An account already exists with this email address. Please sign in with your existing Mentor Connect account instead of creating a new one.", "error")
                return redirect(url_for("signin"))
            print(f"   ✅ Existing user found: {user.email}")
            print(f"   User ID: {user.id}")
            print(f"   User Type: {user.user_type}")
            
            # Normalize stored email to lowercase + update Google ID
            needs_commit = False
            if user.email != email:
                print(f"   🔄 Normalizing email: '{user.email}' → '{email}'")
                user.email = email
                needs_commit = True
            if not user.google_id:
                user.google_id = google_id
                user.oauth_provider = 'google'
                user.profile_picture_url = picture_url
                needs_commit = True
            if needs_commit:
                db.session.commit()
                print(f"   ✅ Updated user record")
            
            print(f"\n📍 Step 8: Setting session for existing user")
            session.permanent = True
            session["email"] = user.email
            session["user_type"] = user.user_type
            session["user_id"] = user.id
            session["user_name"] = user.name
            print(f"   ✅ Session set")
            print(f"      Email: {session.get('email')}")
            print(f"      Type: {session.get('user_type')}")
            print(f"      ID: {session.get('user_id')}")
            
            print(f"\n📍 Step 9: Redirecting based on user type")
            if user.user_type == "1":
                print(f"   ➡️ Redirecting to mentordashboard")
                return redirect(url_for("mentordashboard"))
            elif user.user_type == "2":
                print(f"   ➡️ Redirecting to menteedashboard")
                return redirect(url_for("menteedashboard"))
            elif user.user_type == "0":
                print(f"   ➡️ Redirecting to supervisordashboard")
                return redirect(url_for("supervisordashboard"))
            elif user.user_type == "3":
                print(f"   ➡️ Redirecting to institutiondashboard")
                return redirect(url_for("institutiondashboard"))
            else:
                print(f"   ➡️ No user type set, redirecting to select_user_type")
                return redirect(url_for("select_user_type"))
        else:
            print(f"   ❌ User not found — Google verified identity, proceeding to role selection")
            
            # Store the Google-verified identity in the session.
            session.permanent = True
            session["pending_google"] = {
                "google_id": google_id,
                "email": email,
                "name": name,
                "picture": picture_url or ""
            }
            # Clear any stale login values so the visitor is NOT logged in yet
            for key in ("email", "user_id", "user_type", "user_name"):
                session.pop(key, None)
            
            # Google OAuth is inherently email-verified by Google's servers
            session["otp_verified"] = True
            print("   ✅ Direct Google Sign-Up approved — redirecting to select_user_type")
            return redirect(url_for("select_user_type"))
    
    except Exception as e:
        print(f"\n❌ ERROR in callback: {str(e)}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()
        print("="*60 + "\n")
        flash("Error during Google login. Please try again.", "error")
        return redirect(url_for("signin"))

# ------------------- GOOGLE SIGNUP OTP VERIFICATION -------------------
SIGNUP_OTP_MAX_ATTEMPTS = 5

def _signup_otp_hash(otp):
    """Hash the OTP together with the Flask secret key so a readable session
    cookie never exposes the usable code."""
    return hashlib.sha256((str(otp) + app.config.get("SECRET_KEY", "")).encode()).hexdigest()

def _issue_signup_otp():
    """Generate a fresh OTP, store only its hash + expiry in the session and
    return the plaintext code (for emailing)."""
    otp = f"{secrets.randbelow(1000000):06d}"
    session["signup_otp_hash"] = _signup_otp_hash(otp)
    session["signup_otp_expiry"] = (
        dt.datetime.utcnow() + dt.timedelta(minutes=10)
    ).isoformat()
    session["signup_otp_attempts"] = 0
    return otp

def _canonical_email(email):
    """Canonical identity of an email for duplicate detection.

    Lowercases the address; for Gmail/Googlemail mailboxes it removes dots and
    anything after a '+', because Gmail delivers 'first.last+tag@gmail.com',
    'firstlast@gmail.com' etc. to the same inbox. Two different-looking
    addresses that resolve to the same canonical value are treated as ONE
    email, so only one Mentor Connect account can exist for them.
    """
    email = (email or "").strip().lower()
    local, sep, domain = email.partition("@")
    if not sep:
        return email
    if domain in ("gmail.com", "googlemail.com"):
        local = local.split("+")[0].replace(".", "")
        return f"{local}@gmail.com"
    return email

def _mask_email(email):
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        shown = local[:1] + "*"
    else:
        shown = local[:2] + "*" * max(len(local) - 2, 2)
    return f"{shown}@{domain}"

@app.route("/signup/verify", methods=["GET", "POST"])
def verify_signup_otp():
    """Verify the OTP sent to the user's Gmail before the account is created."""
    pending = session.get("pending_google")
    if not pending:
        flash("Please start sign-up with your Google account first.", "info")
        return redirect(url_for("signin"))

    masked = _mask_email(pending["email"])

    if request.method == "POST":
        # Support both a single input and six separate digit boxes
        code = (request.form.get("otp") or "").strip()
        if not code:
            code = "".join((request.form.get(f"otp_{i}") or "").strip() for i in range(6))

        expiry = session.get("signup_otp_expiry")
        expired = (
            not expiry
            or "signup_otp_hash" not in session
            or dt.datetime.fromisoformat(expiry) < dt.datetime.utcnow()
        )
        if expired:
            otp = _issue_signup_otp()
            send_signup_otp_email(pending["email"], otp)
            flash("Your code expired. A fresh code has been sent to your email.", "warning")
            return redirect(url_for("verify_signup_otp"))

        attempts = session.get("signup_otp_attempts", 0)
        if attempts >= SIGNUP_OTP_MAX_ATTEMPTS:
            for key in ("pending_google", "signup_otp_hash", "signup_otp_expiry", "signup_otp_attempts"):
                session.pop(key, None)
            flash("Too many incorrect attempts. Please sign up with Google again.", "error")
            return redirect(url_for("signin"))

        if not code or _signup_otp_hash(code) != session["signup_otp_hash"]:
            session["signup_otp_attempts"] = attempts + 1
            remaining = SIGNUP_OTP_MAX_ATTEMPTS - (attempts + 1)
            flash(f"Incorrect code. {remaining} attempt(s) remaining.", "error")
            return redirect(url_for("verify_signup_otp"))

        # ✅ OTP verified — mark verified and move on to role selection
        session["otp_verified"] = True
        session["email"] = pending["email"]
        session["user_name"] = pending.get("name") or ""
        for key in ("signup_otp_hash", "signup_otp_expiry", "signup_otp_attempts"):
            session.pop(key, None)
        flash("Email verified successfully!", "success")
        return redirect(url_for("select_user_type"))

    return render_template(
        "auth/verify_signup_otp.html",
        masked_email=masked,
        full_email=pending["email"],
        user_name=pending.get("name") or "",
        picture_url=pending.get("picture") or ""
    )

@app.route("/signup/resend_otp", methods=["POST"])
def resend_signup_otp():
    """Resend a fresh signup OTP to the pending Google email."""
    pending = session.get("pending_google")
    if not pending:
        return redirect(url_for("signin"))

    otp = _issue_signup_otp()
    if send_signup_otp_email(pending["email"], otp):
        flash(f"A new verification code was sent to {_mask_email(pending['email'])}.", "success")
    else:
        flash("Could not resend the email right now. Please try again shortly.", "error")
    return redirect(url_for("verify_signup_otp"))

# ------------------- ROLE SELECTION / ACCOUNT CREATION -------------------
@app.route("/select_user_type", methods=["GET", "POST"])
def select_user_type():
    """Allow OAuth users to select their user type.

    Two paths:
    1. Pending Google sign-up (account NOT yet created): requires the Gmail OTP
       to be verified, then the account is created here with the chosen role.
    2. Legacy OAuth user whose account exists without a role yet.
    """
    pending = session.get("pending_google")

    if pending:
        if not session.get("otp_verified"):
            print("❌ Pending signup present but OTP not verified - redirecting")
            return redirect(url_for("verify_signup_otp"))

        # If an account with this email appeared meanwhile, drop the pending flow
        existing = User.query.filter_by(email=pending["email"]).first()
        if existing:
            session.pop("pending_google", None)
            session.pop("otp_verified", None)
        else:
            if request.method == "POST":
                user_type = request.form.get("user_type")
                if user_type not in ["1", "2"]:
                    flash("Invalid role selected. Please choose Mentor or Mentee.", "error")
                    return redirect(url_for("select_user_type"))

                # Final one-account-per-email guard (covers Gmail variants and
                # accounts created between OTP verification and this moment).
                canonical_new = _canonical_email(pending["email"])
                duplicate = None
                for candidate in User.query.all():
                    if _canonical_email(candidate.email) == canonical_new:
                        duplicate = candidate
                        break
                if duplicate:
                    print(f"⛔ Duplicate signup blocked: '{pending['email']}' matches existing account '{duplicate.email}'")
                    for key in ("pending_google", "otp_verified"):
                        session.pop(key, None)
                    flash(f"An account already exists with this email address. Please sign in with your existing account instead.", "error")
                    return redirect(url_for("signin"))

                try:
                    new_user = User(
                        name=(pending.get("name") or pending["email"].split("@")[0]).strip(),
                        email=pending["email"],
                        google_id=pending.get("google_id"),
                        oauth_provider="google",
                        profile_picture_url=pending.get("picture") or None,
                        oauth_created_at=datetime.utcnow(),
                        user_type=user_type
                    )
                    db.session.add(new_user)
                    db.session.flush()

                    if user_type == "3":
                        institution = Institution.query.filter_by(name=institution_name).first()
                        if not institution:
                            institution = Institution(
                                user_id=new_user.id,
                                name=institution_name,
                                contact_person=new_user.name,
                                contact_email=new_user.email,
                                status="active"
                            )
                            db.session.add(institution)
                            db.session.flush()
                        new_user.institution_id = institution.id

                    db.session.commit()
                    print(f"✅ Verified signup complete - new {user_type} account id={new_user.id}")
                except Exception as e:
                    db.session.rollback()
                    app.logger.error(f"Pending signup account creation failed: {e}")
                    flash("Could not create your account. Please try again.", "error")
                    return redirect(url_for("select_user_type"))

                # Welcome email (non-blocking)
                try:
                    send_welcome_email(new_user.email, new_user.name, signup_method="oauth")
                except Exception as e:
                    print(f"⚠️ Welcome email failed but signup successful: {e}")

                # Log the user in
                session.permanent = True
                session["email"] = new_user.email
                session["user_id"] = new_user.id
                session["user_type"] = user_type
                session["user_name"] = new_user.name
                session["oauth_user"] = True

                for key in ("pending_google", "otp_verified"):
                    session.pop(key, None)

                flash("Your account has been created and your email verified!", "success")

                if user_type == "1":
                    flash("Welcome! Please complete your mentor profile to continue.", "info")
                    return redirect(url_for("editmentorprofile"))
                elif user_type == "2":
                    flash("Welcome! Please complete your mentee profile to continue.", "info")
                    return redirect(url_for("editmenteeprofile"))
                elif user_type == "0":
                    flash("Welcome! Please complete your supervisor profile to continue.", "info")
                    return redirect(url_for("editsupervisorprofile"))
                elif user_type == "3":
                    flash("Welcome! Please complete your institution profile to continue.", "info")
                    return redirect(url_for("editinstitutionprofile"))

            # GET — show the role selection page for a verified pending signup
            return render_template(
                "auth/select_user_type.html",
                user={"name": pending.get("name") or "", "email": pending["email"]},
                pending=True
            )

    if "email" not in session:
        print("❌ No email in session - redirecting to signin")
        return redirect(url_for("signin"))
    
    print(f"✅ Email in session: {session.get('email')}")
    
    user = User.query.filter_by(email=session["email"]).first()
    
    if not user:
        print(f"❌ User not found for email: {session.get('email')}")
        return redirect(url_for("signin"))
    
    print(f"✅ User found: {user.email}, Current type: {user.user_type}")
    
    # If user already has a type, redirect to dashboard
    if user.user_type:
        session.permanent = True
        session["user_type"] = user.user_type
        session["user_id"] = user.id
        
        print(f"📝 User already has type: {user.user_type}, redirecting to dashboard")
        
        if user.user_type == "1":
            return redirect(url_for("mentordashboard"))
        elif user.user_type == "2":
            return redirect(url_for("menteedashboard"))
        elif user.user_type == "0":
            return redirect(url_for("supervisordashboard"))
        elif user.user_type == "3":
            return redirect(url_for("institutiondashboard"))
    
    if request.method == "POST":
        user_type = request.form.get("user_type")
        
        print(f"📝 User selected type: {user_type}")
        
        if user_type not in ["0", "1", "2", "3"]:
            flash("Invalid user type selected", "error")
            return redirect(url_for("select_user_type"))
        
        # Update user type
        user.user_type = user_type
        db.session.commit()
        
        print(f"✅ User type saved to database: {user_type}")
        
        # Update session
        session.permanent = True
        session["user_type"] = user_type
        session["user_id"] = user.id
        session["user_name"] = user.name
        
        print(f"📝 Session updated - Type: {session.get('user_type')}, ID: {session.get('user_id')}")
        
        # Redirect to profile completion
        if user_type == "1":
            flash("Welcome! Please complete your mentor profile to continue.", "info")
            return redirect(url_for("editmentorprofile"))
        elif user_type == "2":
            flash("Welcome! Please complete your mentee profile to continue.", "info")
            return redirect(url_for("editmenteeprofile"))
        elif user_type == "0":
            flash("Welcome! Please complete your supervisor profile to continue.", "info")
            return redirect(url_for("editsupervisorprofile"))
        elif user_type == "3":
            flash("Welcome! Please complete your institution profile to continue.", "info")
            return redirect(url_for("editinstitutionprofile"))
    
    return render_template("auth/select_user_type.html", user=user)

# Helper function to calculate mentor profile completion percentage
def calculate_mentor_profile_completion(mentor_id, profile_obj=None):
    """
    Calculate profile completion percentage and return missing fields
    Includes all meaningful profile fields for accurate completion tracking
    Returns: {
        'percentage': int (0-100),
        'missing_fields': list of missing field names,
        'completed_fields': int,
        'total_fields': int
    }
    """
    profile = profile_obj if profile_obj is not None else MentorProfile.query.filter_by(user_id=mentor_id).first()
    
    # Define all profile fields for completion calculation
    all_fields = {
        # Personal & Professional Details
        'Profile Photo': profile.profile_picture if profile else None,
        'Profession': profile.profession if profile else None,
        'Skills': profile.skills if profile else None,
        'Job Role': profile.role if profile else None,
        'Industry Sector': profile.industry_sector if profile else None,
        'Organisation': profile.organisation if profile else None,
        'Years of Experience': profile.years_of_experience if profile else None,
        
        # Contact Information
        'Location': profile.location if profile else None,
        'WhatsApp': profile.whatsapp if profile else None,
        
        # Education & Background
        'Languages': profile.language if profile else None,
        'Highest Qualification': profile.highest_qualification if profile else None,
        'Degree Name': profile.degree_name if profile else None,
        'Field of Study': profile.field_of_study if profile else None,
        'University Name': profile.university_name if profile else None,
        'Graduation Year': profile.graduation_year if profile else None,
        'Academic Status': profile.academic_status if profile else None,
        'Certifications': profile.certifications if profile else None,
        'Research Work': profile.research_work if profile else None,
        
        # Social Links
        'LinkedIn Profile': profile.linkedin_link if profile else None,
        'GitHub Profile': profile.github_link if profile else None,
        'Portfolio Link': profile.portfolio_link if profile else None,
        'Other Social Link': profile.other_social_link if profile else None,
        
        # Mentorship Preferences
        'Mentorship Topics': profile.mentorship_topics if profile else None,
        'Mentorship Type Preference': profile.mentorship_type_preference if profile else None,
        'Preferred Communication': profile.preferred_communication if profile else None,
        'Availability': profile.availability if profile else None,
        'Connect Frequency': profile.connect_frequency if profile else None,
        'Preferred Duration': profile.preferred_duration if profile else None,
        
        # Mentor Philosophy
        'Why Mentor': profile.why_mentor if profile else None,
        'Mentorship Philosophy': profile.mentorship_philosophy if profile else None,
        'Mentorship Motto': profile.mentorship_motto if profile else None,
        
        # Additional Information
        'Additional Info': profile.additional_info if profile else None,
    }
    
    # Count completed and missing fields
    completed_fields = sum(1 for field in all_fields.values() if field)
    total_fields = len(all_fields)
    
    missing_fields = [field_name for field_name, field_value in all_fields.items() if not field_value]
    
    percentage = (completed_fields * 100) // total_fields if total_fields > 0 else 0
    
    return {
        'percentage': min(percentage, 100),  # Cap at 100%
        'missing_fields': missing_fields,
        'completed_fields': completed_fields,
        'total_fields': total_fields
    }

# ------------------
@app.route("/mentordashboard", methods=["GET", "POST"])
def mentordashboard():
    if "email" not in session or session.get("user_type") != "1":  # Only mentors
        return redirect(url_for("signin"))

    mentor_id = session.get("user_id")

    
    # ------------------- Check Profile Completion -------------------
    user = User.query.filter_by(email=session["email"]).first()
    profile_complete = check_profile_complete(user.id, "1")
    
    # Calculate profile completion percentage and missing fields
    profile_stats = calculate_mentor_profile_completion(user.id)



    # ------------------- mentee requests -------------------
            # Fetch current mentor
    mentor = User.query.filter_by(email=session["email"]).first()


    if not mentor:
            flash("Mentor profile not found.", "error")
            return redirect(url_for("signin"))

        # Fetch incoming mentorship requests for this mentor
    incoming_requests = MentorshipRequest.query.filter_by(
            mentor_id=mentor.id
        ).all()

        # Fetch all mentees
    all_mentees = MenteeProfile.query.all()

        # Unique filter values from mentees
    streams = [row.stream for row in MenteeProfile.query.with_entities(MenteeProfile.stream).distinct() if row.stream]
    schools = [row.school_college_name for row in MenteeProfile.query.with_entities(MenteeProfile.school_college_name).distinct() if row.school_college_name]
    goals = [row.goal for row in MenteeProfile.query.with_entities(MenteeProfile.goal).distinct() if row.goal]

        # Get a specific mentee for the profile section (if needed)
        # For example, get the first mentee from the requests if available
    example_mentee = None
    if incoming_requests and incoming_requests[0].mentee:
            example_mentee = incoming_requests[0].mentee

        # Mentor profile info
    mentor_info = {
            "full_name": mentor.name, 
            "username": mentor.email,
            "date_time": datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        }



    # ------------------- find mentees (with filters) -------------------
    query = MenteeProfile.query.join(User, MenteeProfile.user_id == User.id)

    search_query = request.args.get("search", "").lower()
    stream_filter = request.args.get("stream", "")
    school_filter = request.args.get("school", "")
    goal_filter = request.args.get("goal", "")

    if search_query:
        query = query.filter(
            or_(
                User.name.ilike(f"%{search_query}%"),
                MenteeProfile.stream.ilike(f"%{search_query}%"),
                MenteeProfile.school_college_name.ilike(f"%{search_query}%")
            )
        )
    if stream_filter:
        query = query.filter(MenteeProfile.stream == stream_filter)
    if school_filter:
        query = query.filter(MenteeProfile.school_college_name == school_filter)
    if goal_filter:
        query = query.filter(MenteeProfile.goal == goal_filter)

    all_mentees = query.all()

    # dropdown options
    streams = sorted({m.stream for m in MenteeProfile.query.distinct() if m.stream})
    schools = sorted({m.school_college_name for m in MenteeProfile.query.distinct() if m.school_college_name})
    goals = sorted({m.goal for m in MenteeProfile.query.distinct() if m.goal})

    # Connected mentees (fully approved requests)
    connected_reqs = MentorshipRequest.query.filter_by(
        mentor_id=mentor.id,
        
        supervisor_status="approved",
        final_status="approved"
    ).all()
    my_mentees = [req.mentee for req in connected_reqs if req.mentee]

    return render_template(
        "mentor/mentordashboard.html",
        mentorship_requests=incoming_requests,
        all_mentees=all_mentees,
        streams=streams,
        schools=schools,
        goals=goals,
        incoming_requests=incoming_requests,
        mentor_info=mentor_info,
        active_section="dashboard",
        show_sidebar=True,
        mentee=example_mentee,
        profile_complete=profile_complete,
        profile_stats=profile_stats,
        my_mentees=my_mentees
    )

@app.route("/mentor_mentorship_request", methods=["GET", "POST"])
def mentor_mentorship_request():
    if "email" not in session or session.get("user_type") != "1":  # Only mentors
        return redirect(url_for("signin"))
    
    # Remove profile_required check - allow mentors to access even with incomplete profile

    mentor_id = session.get("user_id")

    user = User.query.filter_by(email=session["email"]).first()
    profile_complete = check_profile_complete(user.id, "1")

    # ------------------- mentee requests -------------------
            # Fetch current mentor
    mentor = User.query.filter_by(email=session["email"]).first()

    if not mentor:
            flash("Mentor profile not found.", "error")
            return redirect(url_for("signin"))

        # Fetch incoming mentorship requests for this mentor
    incoming_requests = MentorshipRequest.query.filter_by(
            mentor_id=mentor.id).filter(
                (MentorshipRequest.mentor_status == "pending") | 
                (MentorshipRequest.supervisor_status == "pending")
        ).all()


    mentee_id = request.args.get("mentee_id")  # or request.form.get("mentee_id")
    mentee = MenteeProfile.query.get(mentee_id)

        # Fetch all mentees
    all_mentees = MenteeProfile.query.all()

        # Unique filter values from mentees
    streams = [row.stream for row in MenteeProfile.query.with_entities(MenteeProfile.stream).distinct() if row.stream]
    schools = [row.school_college_name for row in MenteeProfile.query.with_entities(MenteeProfile.school_college_name).distinct() if row.school_college_name]
    goals = [row.goal for row in MenteeProfile.query.with_entities(MenteeProfile.goal).distinct() if row.goal]

        # Get a specific mentee for the profile section (if needed)
        # For example, get the  first mentee from the requests if available
    example_mentee = None
    if incoming_requests and incoming_requests[0].mentee:
            example_mentee = incoming_requests[0].mentee

        # Mentor profile info
    mentor_info = {
            "full_name": mentor.name, 
            "username": mentor.email,

        }


    existing_pending_request = None
    existing_active_mentorship = None





    return render_template(
        "mentor/mentor_mentorship_request.html",
        mentorship_requests=incoming_requests,
        all_mentees=all_mentees,
        streams=streams,   
        schools=schools,
        goals=goals,
        incoming_requests=incoming_requests,
        mentor_info=mentor_info,
        active_section="meetingrequests",
        show_sidebar=True,
        mentee=example_mentee,
        profile_complete=profile_complete
    )

@app.route("/menteedashboard")
@profile_required
def menteedashboard():
    if "email" in session and session.get("user_type") == "2":
        # Fetch current mentee and profile
        user = User.query.options(joinedload(User.mentee_profile)).filter_by(email=session["email"]).first()
        mentee_profile = user.mentee_profile if user else None
        profile_complete = check_profile_complete(user.id, "2", profile_obj=mentee_profile) if user else False

        all_mentors = MentorProfile.query.options(joinedload(MentorProfile.user)).all()

        # unique filter values from db
        professions = sorted({row.profession for row in all_mentors if row.profession})
        locations = sorted({row.location for row in all_mentors if row.location})
        educations = sorted({row.education for row in all_mentors if row.education})
        experiences = sorted({row.years_of_experience for row in all_mentors if row.years_of_experience})

        career_goal = mentee_profile.goal if mentee_profile else None
        parent_consent_status = mentee_profile.parent_consent_status if mentee_profile else None
        parent_email = mentee_profile.parent_email if mentee_profile else None

        # Fetch the mentee's connected mentors (fully approved requests)
        connected_requests = MentorshipRequest.query.options(
            joinedload(MentorshipRequest.mentor).joinedload(User.mentor_profile)
        ).filter_by(
            mentee_id=user.id,
            supervisor_status="approved",
            final_status="approved"
        ).all()

        my_mentors = []
        for req in connected_requests:
            if req.mentor and req.mentor.mentor_profile:
                my_mentors.append(req.mentor.mentor_profile)

        spotlight_tasks = []
        master_active = MenteeTask.query.filter(
            MenteeTask.mentee_id == user.id,
            MenteeTask.status.in_(["pending", "in-progress"])
        ).order_by(MenteeTask.meeting_number.asc()).all()
        for t in master_active:
            spotlight_tasks.append({
                "id": t.id,
                "type": "master",
                "serial": t.meeting_number,
                "title": (t.master_task.journey_phase if t.master_task else "Mentorship Task"),
                "detail": (t.master_task.purpose_of_call if t.master_task else ""),
                "status": compute_task_progress_status("master", t.id, t.mentee_id, t.mentor_id),
                "progress": t.progress or 0,
                "due_date": t.due_date
            })

        personal_active = PersonalTask.query.filter(
            PersonalTask.mentee_id == user.id,
            PersonalTask.status.in_(["pending", "in-progress"])
        ).order_by(PersonalTask.created_date.desc()).all()
        for t in personal_active:
            spotlight_tasks.append({
                "id": t.id,
                "type": "personal",
                "serial": None,
                "title": t.title,
                "detail": (t.description or ""),
                "status": compute_task_progress_status("personal", t.id, t.mentee_id, t.mentor_id or None),
                "progress": t.progress or 0,
                "due_date": t.due_date
            })

        today = datetime.utcnow().date()
        spotlight_tasks.sort(key=lambda x: 0 if (x["due_date"] and x["due_date"].date() < today) else 1)

        return render_template(
            "mentee/menteedashboard.html",
            all_mentors=all_mentors,
            my_mentors=my_mentors,
            professions=professions,
            locations=locations,
            educations=educations,
            experiences=experiences,
            show_sidebar=True,
            profile_complete=profile_complete,
            career_goal=career_goal,
            parent_consent_status=parent_consent_status,
            parent_email=parent_email,
            spotlight_tasks=spotlight_tasks,
            today_date=today
        )

    return redirect(url_for("signin"))

@app.route("/supervisordashboard")
@profile_required
def supervisordashboard():
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))

    user = User.query.filter_by(email=session["email"]).first()
    profile_complete = check_profile_complete(user.id, "0")



    source_page = request.args.get("from", "supervisor")

    # ----------------- Mentors -----------------
    mentor_query = MentorProfile.query
    profession = request.args.get("profession")
    location = request.args.get("location")
    education = request.args.get("education")
    experience = request.args.get("experience")

    if profession:
        mentor_query = mentor_query.filter_by(profession=profession)
    if location:
        mentor_query = mentor_query.filter_by(location=location)
    if education:
        mentor_query = mentor_query.filter_by(education=education)
    if experience:
        if experience == "0-2":
            mentor_query = mentor_query.filter(cast(MentorProfile.years_of_experience, Integer).between(0, 2))
        elif experience == "3-5":
            mentor_query = mentor_query.filter(cast(MentorProfile.years_of_experience, Integer).between(3, 5))
        elif experience == "6-10":
            mentor_query = mentor_query.filter(cast(MentorProfile.years_of_experience, Integer).between(6, 10))
        elif experience == "10+":
            mentor_query = mentor_query.filter(cast(MentorProfile.years_of_experience, Integer) >= 10)

    mentors = mentor_query.join(User, MentorProfile.user_id == User.id).order_by(User.created_at.asc()).all()

    # Add serial numbers based on timestamp order
    for idx, m in enumerate(mentors, 1):
        m.serial = idx

    options = {
        "professions": sorted({row[0] for row in MentorProfile.query.with_entities(MentorProfile.profession).distinct() if row[0]}),
        "locations": sorted({row[0] for row in MentorProfile.query.with_entities(MentorProfile.location).distinct() if row[0]}),
        "educations": sorted({row[0] for row in MentorProfile.query.with_entities(MentorProfile.education).distinct() if row[0]}),
        "experiences": sorted({row[0] for row in MentorProfile.query.with_entities(MentorProfile.years_of_experience).distinct() if row[0]}),
    }

    # ----------------- Mentees -----------------
    mentee_query = MenteeProfile.query.join(User, MenteeProfile.user_id == User.id)
    search_query = request.args.get("search", "").lower()
    stream_filter = request.args.get("stream", "")
    school_filter = request.args.get("school", "")
    goal_filter = request.args.get("goal", "")

    if search_query:
        mentee_query = mentee_query.filter(
            or_(
                User.name.ilike(f"%{search_query}%"),
                MenteeProfile.stream.ilike(f"%{search_query}%"),
                MenteeProfile.school_college_name.ilike(f"%{search_query}%")
            )
        )
    if stream_filter:
        mentee_query = mentee_query.filter(MenteeProfile.stream == stream_filter)
    if school_filter:
        mentee_query = mentee_query.filter(MenteeProfile.school_college_name == school_filter)
    if goal_filter:
        mentee_query = mentee_query.filter(MenteeProfile.goal == goal_filter)

    all_mentees = mentee_query.order_by(User.created_at.asc()).all()

    # Add serial numbers based on timestamp order
    for idx, m in enumerate(all_mentees, 1):
        m.serial = idx

    # ----------------- Mentee dropdowns -----------------
    mentee_streams = sorted({row[0] for row in MenteeProfile.query.with_entities(MenteeProfile.stream).distinct() if row[0]})
    mentee_schools = sorted({row[0] for row in MenteeProfile.query.with_entities(MenteeProfile.school_college_name).distinct() if row[0]})
    mentee_goals = sorted({row[0] for row in MenteeProfile.query.with_entities(MenteeProfile.goal).distinct() if row[0]})

    # ----------------- Requests -----------------
    all_requests = MentorshipRequest.query.all()
    mentor_requests = MentorProfile.query.filter_by(status="pending").all()
    mentee_requests = MenteeProfile.query.filter_by(status="pending").all()

    # ----------------- Dashboard Breakdown Data -----------------
    mentor_by_location = {}
    mentor_by_institution = {}
    mentor_by_profession = {}
    for m in mentors:
        loc = getattr(m, "location", "") or "Unknown"
        inst = getattr(m, "institution_name", "") or (m.user.institution if m.user and hasattr(m.user, 'institution') else "") or "Unknown"
        prof = getattr(m, "profession", "") or "Unknown"
        mentor_by_location.setdefault(loc, []).append(m)
        mentor_by_institution.setdefault(inst, []).append(m)
        mentor_by_profession.setdefault(prof, []).append(m)

    mentor_scores = {}
    for mr in all_requests:
        if mr.final_status == "approved":
            mid = mr.mentor_id
            if mid not in mentor_scores:
                mentor_scores[mid] = {"completed": 0, "total": 0}
            mentor_scores[mid]["completed"] += 1
            mentor_scores[mid]["total"] += 1
        elif mr.mentor_id:
            mid = mr.mentor_id
            if mid not in mentor_scores:
                mentor_scores[mid] = {"completed": 0, "total": 0}
            mentor_scores[mid]["total"] += 1

    def get_mentor_score(mentor_user_id):
        s = mentor_scores.get(mentor_user_id, {"completed": 0, "total": 0})
        if s["total"] == 0:
            return 0
        return round((s["completed"] / s["total"]) * 100)

    for group in [mentor_by_location, mentor_by_institution, mentor_by_profession]:
        for key in group:
            group[key].sort(key=lambda m: get_mentor_score(m.user_id) if m.user else 0, reverse=True)

    mentee_by_location = {}
    mentee_by_institution = {}
    mentee_by_stream = {}
    for m in all_mentees:
        loc = "Unknown"
        inst = "Unknown"
        stream = getattr(m, "stream", "") or "Unknown"
        if m.user:
            loc = getattr(m.user, "institution", "") or "Unknown"
        if hasattr(m, "institution"):
            inst = m.institution or "Unknown"
        elif hasattr(m, "institution_name"):
            inst = m.institution_name or "Unknown"
        mentee_by_location.setdefault(loc, []).append(m)
        mentee_by_institution.setdefault(inst, []).append(m)
        mentee_by_stream.setdefault(stream, []).append(m)

    active_requests = [r for r in all_requests if r.final_status == "approved"]
    active_by_type = {"anchor": [], "special": []}
    for r in active_requests:
        t = getattr(r, "mentor_type", "") or "special"
        active_by_type.setdefault(t, []).append(r)

    pending_requests = [r for r in all_requests if r.supervisor_status == "pending"]
    pending_by_type = {"mentor": [], "mentee": []}
    for r in pending_requests:
        if r.mentor_status == "pending":
            pending_by_type["mentor"].append(r)
        else:
            pending_by_type["mentee"].append(r)

    today = dt.date.today()
    pending_by_age = {"Today": [], "This Week": [], "Older": []}
    for r in pending_requests:
        created = r.created_at.date() if r.created_at else today
        if created == today:
            pending_by_age["Today"].append(r)
        elif (today - created).days <= 7:
            pending_by_age["This Week"].append(r)
        else:
            pending_by_age["Older"].append(r)

    return render_template(
        "supervisor/supervisordashboard.html",
        show_sidebar=True,
        user_email=session["email"],
        mentors=mentors,
        mentees=all_mentees,
        all_requests=all_requests,
        mentor_requests=mentor_requests,
        mentee_requests=mentee_requests,
        professions=options["professions"],
        locations=options["locations"],
        educations=options["educations"],
        experiences=options["experiences"],
        mentee_streams=mentee_streams,
        mentee_schools=mentee_schools,
        mentee_goals=mentee_goals,
        active_section="dashboard",
        source_page=source_page,
        profile_complete=profile_complete,
        mentor_by_location=mentor_by_location,
        mentor_by_institution=mentor_by_institution,
        mentor_by_profession=mentor_by_profession,
        mentee_by_location=mentee_by_location,
        mentee_by_institution=mentee_by_institution,
        mentee_by_stream=mentee_by_stream,
        active_by_type=active_by_type,
        pending_by_type=pending_by_type,
        pending_by_age=pending_by_age,
        get_mentor_score=get_mentor_score
    )
    
@app.route("/institution")
def institution():
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))

    # Get all institutions
    institutions = Institution.query.order_by(Institution.id.asc()).all()
    
    # Get institution statistics
    institution_stats = []
    for inst in institutions:
        # Count mentors in this institution
        mentors_count = User.query.filter(
            (User.user_type == "1") & 
            ((User.institution_id == inst.id) | (User.institution == inst.name))
        ).count()
        
        # Count mentees in this institution
        mentees_count = User.query.filter(
            (User.user_type == "2") & 
            ((User.institution_id == inst.id) | (User.institution == inst.name))
        ).count()
        
        # Count active mentorships
        active_mentorships = MentorshipRequest.query\
            .join(User, MentorshipRequest.mentee_id == User.id)\
            .filter(
                ((User.institution_id == inst.id) | (User.institution == inst.name)) &
                (MentorshipRequest.final_status == "approved")
            ).count()
        
        institution_stats.append({
            'institution': inst,
            'mentors_count': mentors_count,
            'mentees_count': mentees_count,
            'active_mentorships': active_mentorships,
            'status': inst.status
        })
    
    return render_template(
        "supervisor/institution.html",
        show_sidebar=True,
        active_section="institution",
        institution_stats=institution_stats
    )

@app.route("/view_institution/<int:institution_id>")
def view_institution(institution_id):
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))
    
    institution = Institution.query.get_or_404(institution_id)
    
    # Get institution admin
    admin = None
    if institution.user_id:
        admin = User.query.get(institution.user_id)
    
    # Get all users from this institution
    # First get users by institution_id (new system)
    users_by_id = User.query.filter_by(institution_id=institution_id).all()
    
    # Then get users by institution name (legacy system)
    users_by_name = User.query.filter(
        User.institution == institution.name,
        User.institution_id.is_(None)  # Only get legacy records
    ).all()
    
    # Combine both lists
    all_users = list(users_by_id) + list(users_by_name)
    
    # Separate mentors and mentees
    institution_mentors = [user for user in all_users if user.user_type == "1"]
    institution_mentees = [user for user in all_users if user.user_type == "2"]
    
    # Get mentorship requests involving institution members
    # First get mentee IDs
    mentee_ids = [user.id for user in institution_mentees]
    
    institution_mentorship_requests = []
    if mentee_ids:
        institution_mentorship_requests = MentorshipRequest.query\
            .filter(MentorshipRequest.mentee_id.in_(mentee_ids))\
            .all()
    
    # Calculate statistics
    total_mentors = len(institution_mentors)
    total_mentees = len(institution_mentees)
    active_mentorships = len([req for req in institution_mentorship_requests if req.final_status == "approved"])
    
    return render_template(
        "supervisor/view_institution.html",
        show_sidebar=True,
        active_section="institution",
        institution=institution,
        admin=admin,
        institution_mentors=institution_mentors,
        institution_mentees=institution_mentees,
        mentorship_requests=institution_mentorship_requests,
        total_mentors=total_mentors,
        total_mentees=total_mentees,
        active_mentorships=active_mentorships,
        now=datetime.utcnow()
    )

@app.route("/update_institution_status/<int:institution_id>", methods=["POST"])
def update_institution_status(institution_id):
    if "email" not in session or session.get("user_type") != "0":
        return jsonify({"success": False, "message": "Unauthorized"})
    
    institution = Institution.query.get_or_404(institution_id)
    
    action = request.form.get("action")
    if action == "activate":
        institution.status = "active"
        message = "Institution activated successfully!"
    elif action == "deactivate":
        institution.status = "inactive"
        message = "Institution deactivated successfully!"
    else:
        return jsonify({"success": False, "message": "Invalid action"})
    
    try:
        db.session.commit()
        return jsonify({"success": True, "message": message, "new_status": institution.status})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)})

@app.route("/institution_users/<int:institution_id>/<user_type>")
def institution_users(institution_id, user_type):
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))
    
    institution = Institution.query.get_or_404(institution_id)
    
    # Get users based on type
    if user_type == "mentors":
        # Get mentors by institution_id (new system)
        mentors_by_id = User.query.filter_by(
            user_type="1", 
            institution_id=institution_id
        ).all()
        
        # Get mentors by institution name (legacy system)
        mentors_by_name = User.query.filter(
            User.user_type == "1",
            User.institution == institution.name,
            User.institution_id.is_(None)
        ).all()
        
        users = list(mentors_by_id) + list(mentors_by_name)
        title = f"Mentors - {institution.name}"
        
    elif user_type == "mentees":
        # Get mentees by institution_id (new system)
        mentees_by_id = User.query.filter_by(
            user_type="2", 
            institution_id=institution_id
        ).all()
        
        # Get mentees by institution name (legacy system)
        mentees_by_name = User.query.filter(
            User.user_type == "2",
            User.institution == institution.name,
            User.institution_id.is_(None)
        ).all()
        
        users = list(mentees_by_id) + list(mentees_by_name)
        title = f"Mentees - {institution.name}"
    
    else:
        flash("Invalid user type", "error")
        return redirect(url_for("view_institution", institution_id=institution_id))
    
    return render_template(
        "supervisor/institution_users.html",
        show_sidebar=True,
        active_section="institution",
        institution=institution,
        users=users,
        user_type=user_type,
        title=title
    )



# ============ PASSWORD RESET ROUTES (Supervisor) ============

@app.route("/reset_user_password/<int:user_id>", methods=["GET", "POST"])
def reset_user_password(user_id):
    """Supervisor can reset any user's password"""
    if "email" not in session or session.get("user_type") != "0":
        flash("Only supervisors can reset passwords!", "error")
        return redirect(url_for("signin"))
    
    user = User.query.get_or_404(user_id)
    
    if request.method == "POST":
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        
        # Validate passwords
        if not new_password or not confirm_password:
            flash("Please enter both password fields!", "error")
            return redirect(url_for("reset_user_password", user_id=user_id))
        
        if len(new_password) < 6:
            flash("Password must be at least 6 characters long!", "error")
            return redirect(url_for("reset_user_password", user_id=user_id))
        
        if new_password != confirm_password:
            flash("Passwords do not match!", "error")
            return redirect(url_for("reset_user_password", user_id=user_id))
        
        try:
            # Hash and update password
            hashed_password = generate_password_hash(new_password, method='pbkdf2:sha256', salt_length=8)
            user.password = hashed_password
            db.session.commit()
            
            flash(f"✅ Password reset successfully for {user.name} ({user.email})", "success")
            return redirect(url_for("supervisordashboard"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error resetting password: {str(e)}", "error")
            return redirect(url_for("reset_user_password", user_id=user_id))
    
    return render_template(
        "supervisor/reset_password.html",
        user=user,
        show_sidebar=True
    )


@app.route("/manage_users_passwords")
def manage_users_passwords():
    """Supervisor dashboard to manage user passwords"""
    if "email" not in session or session.get("user_type") != "0":
        flash("Only supervisors can access this page!", "error")
        return redirect(url_for("signin"))
    
    # Get all users
    all_users = User.query.all()
    
    # Group by user type
    mentors = [u for u in all_users if u.user_type == "1"]
    mentees = [u for u in all_users if u.user_type == "2"]
    supervisors = [u for u in all_users if u.user_type == "0"]
    
    return render_template(
        "supervisor/manage_passwords.html",
        show_sidebar=True,
        mentors=mentors,
        mentees=mentees,
        supervisors=supervisors,
        total_users=len(all_users)
    )


# ============ CREATE ACCOUNT ROUTES (Supervisor) ============

@app.route("/create_account", methods=["GET", "POST"])
def create_account():
    """Supervisor can create accounts for mentors, mentees, and institutions"""
    if "email" not in session or session.get("user_type") != "0":
        flash("Only supervisors can create accounts!", "error")
        return redirect(url_for("signin"))
    
    if request.method == "POST":
        name = request.form.get("name")
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        user_type = request.form.get("user_type")
        institution_name = request.form.get("institution", "")
        new_institution_name = request.form.get("new_institution_name", "")
        
        # For institution admin, the name is the institution name
        if user_type == "3":
            if new_institution_name:
                # Use the institution name provided in the new_institution_name field
                institution_name = new_institution_name
                name = institution_name
            else:
                flash("Please provide an institution name!", "error")
                return redirect(url_for("create_account"))
        
        # Validation
        if not all([name, email, password, confirm_password, user_type]):
            flash("Please fill all required fields!", "error")
            return redirect(url_for("create_account"))
        
        if len(password) < 6:
            flash("Password must be at least 6 characters long!", "error")
            return redirect(url_for("create_account"))
        
        if password != confirm_password:
            flash("Passwords do not match!", "error")
            return redirect(url_for("create_account"))
        
        # Check if email already exists
        existing_user = User.query.filter(db.func.lower(User.email) == email).first()
        if existing_user:
            flash("Email already exists! Please use a different email.", "error")
            return redirect(url_for("create_account"))
        
        # For institutions, check if institution name already exists
        if user_type == "3":
            existing_institution = User.query.filter_by(name=name, user_type="3").first()
            if existing_institution:
                flash("Institution name already exists! Please use a different name.", "error")
                return redirect(url_for("create_account"))
        
        try:
            # Hash password
            hashed_password = generate_password_hash(password, method='pbkdf2:sha256', salt_length=8)
            
            # Create new user
            new_user = User(
                name=name,
                email=email,
                password=hashed_password,
                user_type=user_type,
                institution=institution_name if user_type != "3" else None  # Don't store institution for institution admins
            )
            db.session.add(new_user)
            db.session.flush()  # Get user ID
            
            # For institution admin (user_type = "3"), create institution profile
            if user_type == "3":
                institution = Institution(
                    user_id=new_user.id,
                    status="active"
                )
                db.session.add(institution)
                db.session.flush()
                
                new_user.institution_id = institution.id
            
            db.session.commit()
            
            flash(f"✅ Account created successfully for {name} ({email})", "success")
            return redirect(url_for("manage_created_accounts"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating account: {str(e)}", "error")
            return redirect(url_for("create_account"))
    
    # Get existing institutions for dropdown (only show institutions that can be selected by mentors/mentees)
    # These would be institutions created by supervisors, not institution admins
    institutions = Institution.query.all()  # For now, show all institutions
    
    return render_template(
        "supervisor/create_account.html",
        show_sidebar=True,
        institutions=institutions
    )


@app.route("/manage_created_accounts")
def manage_created_accounts():
    """View all accounts created by supervisors"""
    if "email" not in session or session.get("user_type") != "0":
        flash("Only supervisors can access this page!", "error")
        return redirect(url_for("signin"))
    
    # Get all users
    all_users = User.query.all()
    
    # Group by user type
    mentors = [u for u in all_users if u.user_type == "1"]
    mentees = [u for u in all_users if u.user_type == "2"]
    institutions = [u for u in all_users if u.user_type == "3"]
    
    # Add serial numbers (no DB changes)
    for idx, mentor in enumerate(mentors, 1):
        mentor.serial = idx
    for idx, mentee in enumerate(mentees, 1):
        mentee.serial = idx
    for idx, institution in enumerate(institutions, 1):
        institution.serial = idx
    
    return render_template(
        "supervisor/manage_created_accounts.html",
        show_sidebar=True,
        mentors=mentors,
        mentees=mentees,
        institutions=institutions,
        total_accounts=len(all_users)
    )


# ============ EDIT & DELETE USER ROUTES (Supervisor) ============

@app.route("/edit_user/<int:user_id>", methods=["GET", "POST"])
def edit_user(user_id):
    """Supervisor can edit user details"""
    if "email" not in session or session.get("user_type") != "0":
        flash("Only supervisors can edit users!", "error")
        return redirect(url_for("signin"))
    
    user = User.query.get_or_404(user_id)
    
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        institution = request.form.get("institution")
        
        # Validation
        if not all([name, email]):
            flash("Please fill all required fields!", "error")
            return redirect(url_for("edit_user", user_id=user_id))
        
        # Check if email is already taken by another user
        existing_user = User.query.filter(User.email == email, User.id != user_id).first()
        if existing_user:
            flash("Email already taken by another user!", "error")
            return redirect(url_for("edit_user", user_id=user_id))
        
        try:
            user.name = name
            user.email = email
            user.institution = institution
            db.session.commit()
            
            flash(f"✅ User details updated successfully for {name}", "success")
            return redirect(url_for("manage_created_accounts"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating user: {str(e)}", "error")
            return redirect(url_for("edit_user", user_id=user_id))
    
    # Get institutions for dropdown
    institutions = Institution.query.filter_by(status="active").all()
    
    return render_template(
        "supervisor/edit_user.html",
        user=user,
        institutions=institutions,
        show_sidebar=True
    )


@app.route("/delete_user/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    """Supervisor can delete users"""
    if "email" not in session or session.get("user_type") != "0":
        flash("Only supervisors can delete users!", "error")
        return redirect(url_for("signin"))
    
    user = User.query.get_or_404(user_id)
    user_email = user.email
    user_name = user.name
    
    try:
        # Delete related records first (due to foreign key constraints)
        tables_to_clean = [
            ("mentor_profile", "user_id"),
            ("mentee_profile", "user_id"),
            ("supervisor_profile", "user_id"),
            ("institutions", "user_id"),  # Delete institutions created by user
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
            # Chat messages and conversations
            ("chat_messages", "sender_id"),
            ("chat_conversations", "participant1_id"),
            ("chat_conversations", "participant2_id"),
        ]
        
        for table, column in tables_to_clean:
            db.session.execute(text(f"DELETE FROM {table} WHERE {column} = {user_id}"))
        
        # Delete the user
        db.session.delete(user)
        db.session.commit()
        
        flash(f"✅ User {user_name} ({user_email}) has been deleted successfully", "success")
        return redirect(url_for("manage_created_accounts"))
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting user: {str(e)}", "error")
        return redirect(url_for("manage_created_accounts"))


def _get_institution_details(user):
    """Resolve institution record, ID, name, and matching aliases for an institution user."""
    institution = None
    if user.institution_id:
        institution = db.session.get(Institution, user.institution_id)
    if not institution and user.id:
        institution = Institution.query.filter_by(user_id=user.id).first()
    if not institution and user.institution:
        institution = Institution.query.join(User, Institution.user_id == User.id).filter(
            func.trim(func.lower(User.name)) == user.institution.strip().lower()
        ).first()

    inst_id = institution.id if institution else user.institution_id
    inst_name = (institution.name if institution else user.name) or user.institution or ""

    clean_name = inst_name.strip()
    clean_lower = clean_name.lower()
    aliases = {clean_lower}
    if "(" in clean_name and ")" in clean_name:
        p1 = clean_name.split("(")[0].strip().lower()
        p2 = clean_name.split("(")[1].split(")")[0].strip().lower()
        if p1:
            aliases.add(p1)
        if p2:
            aliases.add(p2)
    if user.institution and user.institution.strip():
        aliases.add(user.institution.strip().lower())

    for sfx in [
        " india", " luxembourg", " foundation", " society", " education",
        " pvt ltd", " pvt", " ltd", " private limited", " limited", " llc", " inc",
        " global", " uk", " us"
    ]:
        if clean_lower.endswith(sfx):
            base = clean_lower[:-len(sfx)].strip()
            if len(base) >= 2:
                aliases.add(base)
    if "wes" in clean_lower:
        aliases.add("wes")
        aliases.add("wes foundation")
        aliases.add("wazir education society")

    return institution, inst_id, inst_name, aliases


def _get_institution_members(user, include_paired=False):
    """
    Returns (mentors, mentees) belonging to this institution.
    Matches across User and Profile fields without modifying the database.
    If include_paired=True, also includes mentors/mentees linked via mentorship requests.
    """
    institution, inst_id, inst_name, aliases = _get_institution_details(user)

    # 1. Direct mentees
    all_mentees = User.query.filter_by(user_type="2").all()
    direct_mentees = []
    for m in all_mentees:
        matched = False
        if inst_id and (m.institution_id == inst_id or m.institution_id == user.id):
            matched = True
        u_inst = (m.institution or "").strip().lower()
        if u_inst and any(a == u_inst or a in u_inst for a in aliases):
            matched = True
        mp = m.mentee_profile
        if mp:
            for attr in ["institution", "institution_name", "current_organization"]:
                val = (getattr(mp, attr, "") or "").strip().lower()
                if val and any(a == val or a in val for a in aliases):
                    matched = True
            for attr in ["school_name", "school_college_name", "board_university"]:
                val = (getattr(mp, attr, "") or "").strip().lower()
                if val and any(a in val for a in aliases):
                    matched = True
        # For WES Foundation: also match cohort students created under WES
        if not matched and any("wes" in a for a in aliases):
            m_email = (m.email or "").lower()
            m_coll = ((getattr(mp, "school_college_name", "") or "") if mp else "").lower()
            if "ccc2526" in m_email or "wes" in m_email or any(k in m_coll for k in ["nehru digree", "nehru degree", "burhar", "shahdol", "dhanpuri"]):
                matched = True
        if matched:
            direct_mentees.append(m)

    # 2. Direct mentors
    all_mentors = User.query.filter_by(user_type="1").all()
    direct_mentors = []
    for m in all_mentors:
        matched = False
        if inst_id and (m.institution_id == inst_id or m.institution_id == user.id):
            matched = True
        u_inst = (m.institution or "").strip().lower()
        if u_inst and any(a == u_inst or a in u_inst for a in aliases):
            matched = True
        mp = m.mentor_profile
        if mp:
            mp_org = (getattr(mp, "organisation", "") or "").strip().lower()
            mp_uni = (getattr(mp, "university_name", "") or "").strip().lower()
            if mp_org and any(a == mp_org or a in mp_org for a in aliases):
                matched = True
            if mp_uni and any(a in mp_uni for a in aliases):
                matched = True
        if matched:
            direct_mentors.append(m)

    if not include_paired:
        direct_mentors.sort(key=lambda u: (u.name or "").lower())
        direct_mentees.sort(key=lambda u: (u.name or "").lower())
        return direct_mentors, direct_mentees

    # 3. Include mentors paired with this institution's mentees, and mentees paired with this institution's mentors
    mentee_ids = [m.id for m in direct_mentees]
    mentor_ids = [m.id for m in direct_mentors]

    paired_mentors = []
    if mentee_ids:
        requests_with_mentees = MentorshipRequest.query.filter(MentorshipRequest.mentee_id.in_(mentee_ids)).all()
        for r in requests_with_mentees:
            m_user = db.session.get(User, r.mentor_id)
            if m_user:
                paired_mentors.append(m_user)

    paired_mentees = []
    if mentor_ids:
        requests_with_mentors = MentorshipRequest.query.filter(MentorshipRequest.mentor_id.in_(mentor_ids)).all()
        for r in requests_with_mentors:
            e_user = db.session.get(User, r.mentee_id)
            if e_user:
                paired_mentees.append(e_user)

    dropdown_mentors = list({m.id: m for m in (direct_mentors + paired_mentors)}.values())
    dropdown_mentees = list({m.id: m for m in (direct_mentees + paired_mentees)}.values())

    dropdown_mentors.sort(key=lambda u: (u.name or "").lower())
    dropdown_mentees.sort(key=lambda u: (u.name or "").lower())
    return dropdown_mentors, dropdown_mentees


# ✅ UPDATE THIS ROUTE (remove profile references)

@app.route("/institutiondashboard")
@profile_required
def institutiondashboard():
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))

    user = User.query.filter_by(email=session["email"]).first()
    profile_complete = check_profile_complete(user.id, "3")

    institution, inst_id, institution_name, aliases = _get_institution_details(user)
    
    # Get direct mentors and mentees who belong to this institution
    institution_mentors, institution_mentees = _get_institution_members(user, include_paired=False)

    # Get mentorship requests involving institution members
    mentee_ids = [m.id for m in institution_mentees]
    institution_mentorship_requests = (
        MentorshipRequest.query.filter(MentorshipRequest.mentee_id.in_(mentee_ids)).all()
        if mentee_ids else []
    )

    # Notes written by or tagging the institution in the Resources Hub
    all_res_notes = ResourceNote.query.all()
    institution_notes = 0
    for rn in all_res_notes:
        if rn.mentee_id == user.id:
            institution_notes += 1
        elif inst_id and (rn.institution_id == inst_id or rn.tags_dict.get("inst") == inst_id):
            institution_notes += 1

    return render_template(
        "institution/institutiondashboard.html",
        show_sidebar=True,
        user=user,
        institution=institution,
        institution_mentors=institution_mentors,
        institution_mentees=institution_mentees,
        mentorship_requests=institution_mentorship_requests,
        institution_notes=institution_notes,
        profile_complete=profile_complete
    )

# Institution specific routes
@app.route("/institution_mentors")
def institution_mentors():
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))
    
    user = User.query.filter_by(email=session["email"]).first()
    institution_mentors, _ = _get_institution_members(user, include_paired=False)
    
    return render_template(
        "institution/institution_mentors.html",
        show_sidebar=True,
        mentors=institution_mentors
    )

@app.route("/institution_mentees")
def institution_mentees():
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))
    
    user = User.query.filter_by(email=session["email"]).first()
    _, institution_mentees = _get_institution_members(user, include_paired=False)
    
    return render_template(
        "institution/institution_mentees.html",
        show_sidebar=True,
        mentees=institution_mentees
    )

@app.route("/institution_mentorships")
def institution_mentorships():
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))
    
    user = User.query.filter_by(email=session["email"]).first()
    institution = None
    if user.institution_id:
        institution = Institution.query.filter_by(id=user.institution_id).first()
    if not institution:
        institution = Institution.query.filter_by(name=user.institution).first()
    institution_name = institution.name if institution else user.institution

    # Get ALL mentorship requests where either the mentee OR the mentor
    # belongs to this institution (by ID or by name) — pending first so the
    # institution can approve/reject them right from this tab
    all_mentorships = MentorshipRequest.query.filter(
        (
            MentorshipRequest.mentee_id.in_(
                db.session.query(User.id).filter(
                    (User.user_type == "2") & (
                        (User.institution_id == user.institution_id) |
                        (User.institution == institution_name)
                    )
                )
            )
        ) |
        (
            MentorshipRequest.mentor_id.in_(
                db.session.query(User.id).filter(
                    (User.user_type == "1") & (
                        (User.institution_id == user.institution_id) |
                        (User.institution == institution_name)
                    )
                )
            )
        )
    ).order_by(
        (MentorshipRequest.final_status == "pending").desc(),
        (MentorshipRequest.final_status == "approved").desc(),
        MentorshipRequest.created_at.desc()
    ).all()

    # Get additional data for each mentorship (mirrors supervisor_all_mentorships)
    mentorships_data = []
    for mentorship in all_mentorships:
        mentor = mentorship.mentor
        mentee = mentorship.mentee

        mentor_profile = mentor.mentor_profile if mentor else None
        mentee_profile = mentee.mentee_profile if mentee else None

        tasks = MenteeTask.query.filter_by(
            mentee_id=mentee.id if mentee else None,
            mentor_id=mentor.id if mentor else None
        ).all()

        meetings = MeetingRequest.query.filter(
            ((MeetingRequest.requester_id == mentee.id) & (MeetingRequest.requested_to_id == mentor.id)) |
            ((MeetingRequest.requester_id == mentor.id) & (MeetingRequest.requested_to_id == mentee.id))
        ).all()

        mentorships_data.append({
            "request": mentorship,
            "mentor": mentor,
            "mentor_profile": mentor_profile,
            "mentee": mentee,
            "mentee_profile": mentee_profile,
            "tasks": tasks,
            "meetings": meetings,
            "tasks_completed": len([t for t in tasks if compute_task_progress_status("master", t.id, t.mentee_id, t.mentor_id) == "done"]),
            "tasks_total": len(tasks),
            "meetings_completed": len([m for m in meetings if m.status == "approved"]),
            "meetings_total": len(meetings)
        })
    
    
    return render_template(
        "institution/institution_mentorships.html",
        show_sidebar=True,
        user=user,
        institution=institution,
        mentorships_data=mentorships_data,
        active_section="mentorships"
    )

@app.route("/institution_requests")
def institution_requests():
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))
    
    user = User.query.filter_by(email=session["email"]).first()
    institution = None
    if user.institution_id:
        institution = Institution.query.filter_by(id=user.institution_id).first()
    if not institution:
        institution = Institution.query.filter_by(name=user.institution).first()
    institution_name = institution.name if institution else user.institution

    # Mentorship requests where either the mentee OR the mentor belongs to this institution,
    # prioritised so pending ones appear first.
    from sqlalchemy.orm import joinedload
    mentorship_requests = MentorshipRequest.query.options(
        joinedload(MentorshipRequest.mentee).joinedload(User.mentee_profile),
        joinedload(MentorshipRequest.mentor).joinedload(User.mentor_profile)
    ).filter(
        (
            (MentorshipRequest.mentee_id.in_(
                db.session.query(User.id).filter(
                    (User.user_type == "2") & (
                        (User.institution_id == user.institution_id) |
                        (User.institution == institution_name)
                    )
                )
            )) |
            (MentorshipRequest.mentor_id.in_(
                db.session.query(User.id).filter(
                    (User.user_type == "1") & (
                        (User.institution_id == user.institution_id) |
                        (User.institution == institution_name)
                    )
                )
            ))
        )
    ).order_by(
        (MentorshipRequest.supervisor_status == "pending").desc(),
        MentorshipRequest.created_at.desc()
    ).all()

    return render_template(
        "institution/institution_requests.html",
        show_sidebar=True,
        user=user,
        institution=institution,
        mentorship_requests=mentorship_requests,
        pending_mentorship_requests=[r for r in mentorship_requests if r.supervisor_status == "pending"],
        approved_mentorships=[r for r in mentorship_requests if r.final_status == "approved"],
        active_section="requests"
    )

@app.route("/institution_all_meetings")
def institution_all_meetings():
    """All Meetings tab for the Institution — mirrors the supervisor's meeting details page,
    but scoped to meetings involving this institution's mentors and mentees."""
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))

    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("signin"))

    institution = None
    if user.institution_id:
        institution = Institution.query.filter_by(id=user.institution_id).first()
    if not institution:
        institution = Institution.query.filter_by(name=user.institution).first()
    institution_name = institution.name if institution else user.institution

    # All meetings involving the institution's mentors or mentees (by ID or by name)
    meetings = (
        MeetingRequest.query
        .join(User, db.or_(MeetingRequest.requester_id == User.id, MeetingRequest.requested_to_id == User.id))
        .filter(
            (User.user_type.in_(["1", "2"])) &
            (
                (User.institution_id == user.institution_id) |
                (User.institution == institution_name)
            )
        )
        .order_by(MeetingRequest.meeting_date.desc(), MeetingRequest.meeting_time.desc())
        .all()
    )

    from datetime import datetime, date
    now = datetime.now()

    # Prepare formatted meeting data with mentee & mentor info
    meeting_data = []
    for meeting in meetings:
        mentee = User.query.get(meeting.requester_id)
        mentor = User.query.get(meeting.requested_to_id)

        meeting_datetime = datetime.combine(meeting.meeting_date, meeting.meeting_time)
        is_upcoming = meeting_datetime > now

        meeting_data.append({
            "id": meeting.id,
            "title": meeting.meeting_title,
            "description": meeting.meeting_description,
            "date": meeting.meeting_date.strftime("%d-%m-%Y"),
            "time": meeting.meeting_time.strftime("%I:%M %p"),
            "datetime_obj": meeting_datetime,
            "duration": meeting.meeting_duration,
            "status": meeting.status,
            "mentee_name": mentee.name if mentee else "Unknown",
            "mentee_email": mentee.email if mentee else "N/A",
            "mentor_name": mentor.name if mentor else "Unknown",
            "mentor_email": mentor.email if mentor else "N/A",
            "created_at": meeting.created_at.strftime("%d-%m-%Y %I:%M %p") if meeting.created_at else "",
            "is_upcoming": is_upcoming,
            "meet_link": meeting.meet_link,
        })

    return render_template(
        "institution/institution_all_meetings.html",
        show_sidebar=True,
        user=user,
        institution=institution,
        meetings=meeting_data
    )

@app.route("/institution_response", methods=["POST"])
def institution_response():
    """Approve or reject a mentorship request from the institution dashboard,
    mirroring the supervisor's approve/reject flow."""
    if "email" not in session or session.get("user_type") != "3":
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    user = User.query.filter_by(email=session["email"]).first()
    institution = None
    if user.institution_id:
        institution = Institution.query.filter_by(id=user.institution_id).first()
    if not institution:
        institution = Institution.query.filter_by(name=user.institution).first()
    institution_name = institution.name if institution else user.institution

    request_id = request.form.get("request_id")
    action = request.form.get("action")

    # Allow the caller to specify which tab to return to (e.g. the
    # institution Mentorships tab). Only same-site relative paths allowed.
    next_url = request.form.get("next") or ""
    redirect_target = next_url if next_url.startswith("/") else url_for("institution_requests")

    if not request_id or not action:
        flash("Invalid request!", "error")
        return redirect(redirect_target)

    mentorship_request = MentorshipRequest.query.get(int(request_id))
    if not mentorship_request:
        flash("Request not found!", "error")
        return redirect(redirect_target)

    # Only allow institutions to manage requests involving their members
    mentee_in_inst = (
        mentorship_request.mentee_id in [
            u.id for u in User.query.filter(
                (User.user_type == "2") & (
                    (User.institution_id == user.institution_id) |
                    (User.institution == institution_name)
                )
            ).all()
        ]
    ) if mentorship_request.mentee_id else False
    mentor_in_inst = (
        mentorship_request.mentor_id in [
            u.id for u in User.query.filter(
                (User.user_type == "1") & (
                    (User.institution_id == user.institution_id) |
                    (User.institution == institution_name)
                )
            ).all()
        ]
    ) if mentorship_request.mentor_id else False

    if not (mentee_in_inst or mentor_in_inst):
        flash("This request does not belong to your institution.", "error")
        return redirect(redirect_target)

    # Update status based on action
    if action == "approve":
        flash("Mentorship request approved!", "success")
        if mentorship_request.duration_months == 12:
            assigned_tasks = assign_master_tasks_to_mentorship(mentorship_request)
            if assigned_tasks:
                flash(f"Mentorship approved! {len(assigned_tasks)} tasks assigned.", "success")
            else:
                flash("Mentorship approved! But no tasks were assigned.", "warning")
        else:
            flash("Mentorship request approved!", "success")

        # Re-set status AFTER task assignment (assign function may rollback session)
        mentorship_request.supervisor_status = "approved"
        mentorship_request.final_status = "approved"

    elif action == "reject":
        mentorship_request.supervisor_status = "rejected"
        mentorship_request.final_status = "rejected"
        flash("Mentorship request rejected!", "success")

        if mentorship_request.mentee:
            create_notification(
                mentorship_request.mentee.id,
                "Your mentorship request was rejected by your institution.",
                url_for("my_mentors")
            )
        if mentorship_request.mentor:
            create_notification(
                mentorship_request.mentor.id,
                "A mentorship with a mentee was rejected by your institution.",
                url_for("my_mentees")
            )
    else:
        flash("Invalid action!", "error")
        return redirect(redirect_target)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash("Something went wrong while updating the request.", "error")
        print("DB Commit Error:", e)

    # If connection is now complete (mentor accepted + institution approved),
    # notify both sides and send the connection emails.
    if action == "approve":
        notify_mentorship_connection(mentorship_request)
        send_mentorship_connected_email(mentorship_request)

    return redirect(redirect_target)

from sqlalchemy.orm import aliased
from sqlalchemy import and_, or_
from datetime import datetime


@app.route("/institution_all_tasks")
def institution_all_tasks():
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))

    user = User.query.filter_by(email=session["email"]).first()
    institution_id = user.institution_id
    institution_name = user.institution

    if not institution_id and not institution_name:
        flash("Institution not linked to your account.", "error")
        return redirect(url_for("institutiondashboard"))

    all_institution_tasks = []
    
    # Get all users from the institution
    institution_users = User.query.filter(
        (User.institution == institution_name) | 
        (User.institution_id == institution_id)
    ).all()
    
    institution_user_ids = [user.id for user in institution_users]

    all_ratings = TaskRating.query.all()
    ratings_map = {(r.task_type, r.task_id): r for r in all_ratings}
    all_mentee_fb = MenteeFeedback.query.all()
    mentee_fb_map = {(f.task_type, f.task_id): f for f in all_mentee_fb}
    all_inst_refl = InstitutionReflection.query.all()
    inst_refl_set = {(r.task_type, r.task_id) for r in all_inst_refl}

    # 1. PERSONAL TASKS (Self-assigned by mentees)
    personal_tasks_self = PersonalTask.query.filter(
        PersonalTask.mentee_id.in_(institution_user_ids),
        PersonalTask.mentor_id == None
    ).all()

    for task in personal_tasks_self:
        mentee = db.session.get(User, task.mentee_id)
        r_obj = ratings_map.get(('personal', task.id))
        mf_obj = mentee_fb_map.get(('personal', task.id))
        has_ref = ('personal', task.id) in inst_refl_set
        all_institution_tasks.append({
            "id": f"personal_{task.id}",
            "serial": f"P-{task.id}",
            "title": task.title,
            "description": task.description,
            "due_date": task.due_date,
            "status": compute_task_progress_status("personal", task.id, task.mentee_id, None),
            "progress": task.progress or 0,
            "priority": task.priority or "medium",
            "category": getattr(task, 'category', None) or "Personal",
            "mentor_id": None,
            "mentor_name": "Self-assigned",
            "mentee_id": task.mentee_id,
            "mentee_name": mentee.name if mentee else "Unknown",
            "mentee_email": mentee.email if mentee else "",
            "type": "personal",
            "rating": r_obj.rating if r_obj else 0,
            "menteeRating": mf_obj.rating if mf_obj else None,
            "hasReflection": has_ref,
            "isCritical": task.is_critical if hasattr(task, 'is_critical') else False,
            "comments": task.comments if hasattr(task, 'comments') else None
        })

    # 2. PERSONAL TASKS (Assigned by mentors)
    personal_tasks_by_mentors = PersonalTask.query.filter(
        PersonalTask.mentee_id.in_(institution_user_ids),
        PersonalTask.mentor_id != None
    ).all()

    for task in personal_tasks_by_mentors:
        mentee = db.session.get(User, task.mentee_id)
        mentor = db.session.get(User, task.mentor_id)
        
        # Check if mentor belongs to same institution
        if mentor and (mentor.institution == institution_name or mentor.institution_id == institution_id):
            r_obj = ratings_map.get(('personal', task.id))
            mf_obj = mentee_fb_map.get(('personal', task.id))
            has_ref = ('personal', task.id) in inst_refl_set
            all_institution_tasks.append({
                "id": f"personal_{task.id}",
                "serial": f"P-{task.id}",
                "title": task.title,
                "description": task.description,
                "due_date": task.due_date,
                "status": compute_task_progress_status("personal", task.id, task.mentee_id, task.mentor_id),
                "progress": task.progress or 0,
                "priority": task.priority or "medium",
                "category": getattr(task, 'category', None) or "Personal",
                "mentor_id": task.mentor_id,
                "mentor_name": mentor.name if mentor else "Unknown",
                "mentor_email": mentor.email if mentor else "",
                "mentee_id": task.mentee_id,
                "mentee_name": mentee.name if mentee else "Unknown",
                "mentee_email": mentee.email if mentee else "",
                "type": "personal",
                "rating": r_obj.rating if r_obj else 0,
                "menteeRating": mf_obj.rating if mf_obj else None,
                "hasReflection": has_ref,
                "isCritical": task.is_critical if hasattr(task, 'is_critical') else False,
                "comments": task.comments if hasattr(task, 'comments') else None
            })

    # 3. MENTEE TASKS (Master Tasks)
    mentee_tasks = MenteeTask.query.filter(
        MenteeTask.mentee_id.in_(institution_user_ids)
    ).all()

    for task in mentee_tasks:
        mentee = db.session.get(User, task.mentee_id)
        mentor = db.session.get(User, task.mentor_id)
        master_task = db.session.get(MasterTask, task.task_id) if task.task_id else None
        
        if mentor and (mentor.institution == institution_name or mentor.institution_id == institution_id):
            r_obj = ratings_map.get(('master', task.id))
            mf_obj = mentee_fb_map.get(('master', task.id))
            has_ref = ('master', task.id) in inst_refl_set
            all_institution_tasks.append({
                "id": f"master_{task.id}",
                "serial": f"M-{task.id}",
                "title": master_task.purpose_of_call if master_task else "Mentorship Task",
                "description": master_task.mentee_focus if master_task else "No description",
                "due_date": task.due_date,
                "status": compute_task_progress_status("master", task.id, task.mentee_id, task.mentor_id),
                "progress": task.progress or 0,
                "priority": "high",  # Master tasks are typically high priority
                "category": "Mentorship Task",
                "mentor_id": task.mentor_id,
                "mentor_name": mentor.name if mentor else "Unknown",
                "mentor_email": mentor.email if mentor else "",
                "mentee_id": task.mentee_id,
                "mentee_name": mentee.name if mentee else "Unknown",
                "mentee_email": mentee.email if mentee else "",
                "type": "master",
                "rating": r_obj.rating if r_obj else 0,
                "menteeRating": mf_obj.rating if mf_obj else None,
                "hasReflection": has_ref,
                "isCritical": True,  # Master tasks are always critical
                "comments": task.comments if hasattr(task, 'comments') else None
            })

    # Sort by due date (most urgent first)
    all_institution_tasks.sort(key=lambda x: x['due_date'] if x['due_date'] else datetime.max)

    # Get mentors and mentees for filters
    institution_mentors = User.query.filter(
        User.id.in_(institution_user_ids),
        User.user_type == "1"  # Mentor type
    ).all()
    
    institution_mentees = User.query.filter(
        User.id.in_(institution_user_ids),
        User.user_type == "2"  # Mentee type
    ).all()

    return render_template(
        "institution/institution_all_tasks.html",
        show_sidebar=True,
        tasks=all_institution_tasks,
        mentors=[{"id": m.id, "name": m.name} for m in institution_mentors],
        mentees=[{"id": m.id, "name": m.name} for m in institution_mentees],
        now=datetime.now(),
        profile_complete=True
    )

@app.route("/get_institution_tasks_data")
def get_institution_tasks_data():
    if "email" not in session or session.get("user_type") != "3":
        return jsonify({"success": False, "message": "Unauthorized"})

    user = User.query.filter_by(email=session["email"]).first()
    institution_id = user.institution_id
    institution_name = user.institution

    # Get all users from the institution
    institution_users = User.query.filter(
        (User.institution == institution_name) | 
        (User.institution_id == institution_id)
    ).all()
    
    institution_user_ids = [user.id for user in institution_users]
    
    # Pre-fetch all ratings in memory to avoid N+1 queries
    ratings = TaskRating.query.all()
    ratings_map = {(r.task_type, r.task_id): r.rating for r in ratings}

    inst_id_val = institution_id or user.id

    # Pre-fetch all mentee feedbacks and institution reflections
    mentee_feedbacks = MenteeFeedback.query.all()
    mentee_ratings_map = {(mf.task_type, mf.task_id): (mf.rating or 0) for mf in mentee_feedbacks}
    inst_reflections = InstitutionReflection.query.filter_by(institution_id=inst_id_val).all()
    inst_refl_map = {(ir.task_type, ir.task_id): bool(ir.text) for ir in inst_reflections}

    def _get_mentee_rating_val(ttype, tid):
        return mentee_ratings_map.get((ttype, tid), 0)

    def _get_has_reflection_val(ttype, tid):
        return inst_refl_map.get((ttype, tid), False)
    
    tasks_data = []
    
    # Get Personal Tasks
    personal_tasks = PersonalTask.query.filter(
        PersonalTask.mentee_id.in_(institution_user_ids)
    ).all()
    
    for task in personal_tasks:
        mentee = db.session.get(User, task.mentee_id)
        mentor = db.session.get(User, task.mentor_id) if task.mentor_id else None
        m_rating = ratings_map.get(('personal', task.id), getattr(task, 'rating', 0) or 0)
        
        tasks_data.append({
            "id": f"personal_{task.id}",
            "serial": f"P-{task.id}",
            "title": task.title,
            "description": task.description,
            "dueDate": task.due_date.isoformat() if task.due_date else None,
            "status": compute_task_progress_status("personal", task.id, task.mentee_id, task.mentor_id or None),
            "progress": task.progress or 0,
            "priority": task.priority or "medium",
            "category": getattr(task, 'category', None) or "Personal",
            "mentorId": task.mentor_id,
            "mentorName": mentor.name if mentor else "Self-assigned",
            "menteeId": task.mentee_id,
            "menteeName": mentee.name if mentee else "Unknown",
            "type": "personal",
            "rating": m_rating,
            "menteeRating": _get_mentee_rating_val("personal", task.id),
            "hasReflection": _get_has_reflection_val("personal", task.id),
            "isCritical": task.is_critical if hasattr(task, 'is_critical') else False
        })
    
    # Get Mentee Tasks (Master Tasks)
    mentee_tasks = MenteeTask.query.filter(
        MenteeTask.mentee_id.in_(institution_user_ids)
    ).all()
    
    for task in mentee_tasks:
        mentee = db.session.get(User, task.mentee_id)
        mentor = db.session.get(User, task.mentor_id)
        master_task = db.session.get(MasterTask, task.task_id) if task.task_id else None
        m_rating = ratings_map.get(('master', task.id), 0)
        
        tasks_data.append({
            "id": f"master_{task.id}",
            "serial": f"M-{task.id}",
            "title": master_task.purpose_of_call if master_task else "Mentorship Task",
            "description": master_task.mentee_focus if master_task else "No description",
            "dueDate": task.due_date.isoformat() if task.due_date else None,
            "status": compute_task_progress_status("master", task.id, task.mentee_id, task.mentor_id),
            "progress": task.progress or 0,
            "priority": "high",
            "category": "Mentorship Task",
            "mentorId": task.mentor_id,
            "mentorName": mentor.name if mentor else "Unknown",
            "menteeId": task.mentee_id,
            "menteeName": mentee.name if mentee else "Unknown",
            "type": "master",
            "rating": m_rating,
            "menteeRating": _get_mentee_rating_val("master", task.id),
            "hasReflection": _get_has_reflection_val("master", task.id),
            "isCritical": True
        })
    
    # Get institution mentors and mentees for filters
    institution_mentors = User.query.filter(
        User.id.in_(institution_user_ids),
        User.user_type == "1"
    ).all()
    
    institution_mentees = User.query.filter(
        User.id.in_(institution_user_ids),
        User.user_type == "2"
    ).all()

    return jsonify({
        "success": True,
        "tasks": tasks_data,
        "mentors": [{"id": m.id, "name": m.name} for m in institution_mentors],
        "mentees": [{"id": m.id, "name": m.name} for m in institution_mentees],
        "institutionName": institution_name
    })



@app.route("/institution_profile")
def institutionprofile_old():
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))

    user = User.query.filter_by(email=session["email"]).first()
    
    # Get institution by user_id (primary - linked as admin) or by institution_id
    institution_details = None
    if user.id:
        institution_details = Institution.query.filter_by(user_id=user.id).first()
    if not institution_details and user.institution_id:
        institution_details = Institution.query.filter_by(id=user.institution_id).first()
    if not institution_details:
        institution_details = Institution.query.filter_by(name=user.institution).first()
    
    # If institution not found, create default data
    if not institution_details:
        print(f"Institution '{user.institution}' not found, creating default data")
        # Create default institution object
        from datetime import datetime
        institution_details = type('obj', (object,), {
            'name': user.institution,
            'email_domain': user.email.split('@')[1] if '@' in user.email else 'example.com',
            'contact_person': user.name,
            'contact_email': user.email,
            'contact_phone': 'Not provided',
            'address': 'Not provided',
            'city': 'Not provided',
            'state': 'Not provided',
            'country': 'Not provided',
            'website': 'Not provided',
            'status': 'active',
            'created_at': datetime.utcnow(),
            'id': 0
        })()
    
    # Calculate statistics using institution_id
    total_students = User.query.filter_by(
        user_type="2", 
        institution_id=user.institution_id
    ).count()
    
    total_mentors = User.query.filter_by(
        user_type="1", 
        institution_id=user.institution_id
    ).count()
    
    # Count active mentorships
    active_mentorships = MentorshipRequest.query\
        .join(User, MentorshipRequest.mentee_id == User.id)\
        .filter(
            User.institution_id == user.institution_id,
            MentorshipRequest.final_status == "approved"
        ).count()

    completed_mentorships = 0  # Placeholder

    return render_template(
        "institution/institutionprofile.html",
        show_sidebar=False,
        full_name=user.name,
        email=user.email,
        institution=user.institution,
        total_students=total_students,
        total_mentors=total_mentors,
        active_mentorships=active_mentorships,
        completed_mentorships=completed_mentorships,
        institution_details=institution_details
    )


@app.route("/editinstitutionprofile", methods=["GET", "POST"])
def editinstitutionprofile():
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))

    user = User.query.filter_by(email=session["email"]).first()
    
    # Get institution by user_id (primary - linked as admin) or by institution_id
    institution_details = None
    if user.id:
        institution_details = Institution.query.filter_by(user_id=user.id).first()
    if not institution_details and user.institution_id:
        institution_details = Institution.query.filter_by(id=user.institution_id).first()
    if not institution_details:
        institution_details = Institution.query.filter_by(name=user.institution).first()

    if request.method == "POST":
        try:
            # Validate only editable mandatory fields
            # Note: name and contact_email are read-only from signup_details, so they're not validated
            mandatory_fields = {
                "contact_person": request.form.get("contact_person"),
                "contact_phone": request.form.get("contact_phone"),
                "address": request.form.get("address"),
                "city": request.form.get("city"),
                "state": request.form.get("state"),
                "country": request.form.get("country"),
                "website": request.form.get("website"),
            }
            
            # Check for empty fields
            missing_fields = []
            for field_name, field_value in mandatory_fields.items():
                if not field_value:
                    missing_fields.append(field_name.replace("_", " ").title())
            
            if missing_fields:
                flash(f"Please fill all mandatory fields: {', '.join(missing_fields)}", "error")
                return redirect(url_for("editinstitutionprofile"))
            
            # If institution doesn't exist, create it with user_id link
            if not institution_details:
                institution_details = Institution(
                    user_id=user.id,  # Link to admin user
                    name=request.form.get("name", user.institution)
                )
                db.session.add(institution_details)
                db.session.flush()
            
            # Update institution details from form
            # Note: name and contact_email are read-only from signup_details, so they're not updated
            institution_details.email_domain = request.form.get("email_domain", "")
            institution_details.contact_person = request.form.get("contact_person", "")
            institution_details.contact_phone = request.form.get("contact_phone", "")
            institution_details.address = request.form.get("address", "")
            institution_details.city = request.form.get("city", "")
            institution_details.state = request.form.get("state", "")
            institution_details.country = request.form.get("country", "")
            institution_details.website = request.form.get("website", "")
            
            # Safely set institution_type
            try:
                institution_type = request.form.get("institution_type", "other")
                if hasattr(institution_details, 'institution_type'):
                    institution_details.institution_type = institution_type
            except Exception as e:
                print(f"Warning: Could not set institution_type: {e}")
            
            # Link both ways: user.institution_id and institution.user_id
            user.institution_id = institution_details.id
            if not institution_details.user_id:
                institution_details.user_id = user.id
            
            # Handle profile picture upload
            if 'profile_picture' in request.files:
                file = request.files['profile_picture']
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(f"institution_{institution_details.id}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    institution_details.profile_picture = filename
            
            # Update user details
            if hasattr(user, 'designation'):
                user.designation = request.form.get("designation", "")
            if hasattr(user, 'department'):
                user.department = request.form.get("department", "")
            if hasattr(user, 'phone'):
                user.phone = request.form.get("official_phone", "")
            
            db.session.commit()
            flash("Institution profile updated successfully!", "success")
            return redirect(url_for("institutionprofile"))
            
        except Exception as e:
            db.session.rollback()
            print(f"Error updating institution profile: {str(e)}")
            flash(f"Error updating profile: {str(e)}", "error")
            return redirect(url_for("editinstitutionprofile"))

    # GET request - prepare data for the form
    institution_type = 'other'
    if institution_details and hasattr(institution_details, 'institution_type'):
        institution_type = institution_details.institution_type or 'other'

    return render_template(
        "institution/editinstitutionprofile.html",
        show_sidebar=False,
        name=user.name,  # Institution name from signup_details.name
        email=user.email,  # Institution email from signup_details.email
        institution_details=institution_details
    )

#-------- find function------------
@app.route("/find_mentor", methods=["GET"])
@cache.cached(timeout=60, query_string=True)
def find_mentor():
    # Get current mentee's profile for suggestions
    current_user_id = None
    mentee_profile = None
    current_user = None
    
    if "email" in session:
        current_user = User.query.filter_by(email=session["email"]).first()
        if current_user and session.get("user_type") == "2":
            current_user_id = current_user.id
            mentee_profile = MenteeProfile.query.filter_by(user_id=current_user_id).first()

    source_page = request.args.get("from", "mentees")
    profession = request.args.get("profession")
    location = request.args.get("location")
    education = request.args.get("education")
    experience = request.args.get("experience")

    # Get ALL users with user_type = "1" (mentors) - eager load mentor_profile in 1 single query
    all_mentor_users = User.query.filter_by(user_type="1").options(joinedload(User.mentor_profile)).all()
    
    # Create enriched mentor objects combining User and MentorProfile data
    all_mentors = []
    for user in all_mentor_users:
        mentor_profile = user.mentor_profile
        
        # Create enriched object with user data as fallback
        mentor = type('MentorData', (), {})()
        
        if mentor_profile:
            # Use profile data if available
            mentor.id = mentor_profile.id
            mentor.user_id = user.id
            mentor.user = user
            mentor.profession = mentor_profile.profession
            mentor.organisation = mentor_profile.organisation
            mentor.location = mentor_profile.location
            mentor.years_of_experience = mentor_profile.years_of_experience
            mentor.education = mentor_profile.education
            mentor.language = mentor_profile.language
            mentor.preferred_communication = mentor_profile.preferred_communication
            mentor.skills = mentor_profile.skills
            mentor.role = mentor_profile.role
            mentor.industry_sector = mentor_profile.industry_sector
            mentor.linkedin_link = mentor_profile.linkedin_link
            mentor.github_link = mentor_profile.github_link
            mentor.portfolio_link = mentor_profile.portfolio_link
            mentor.other_social_link = mentor_profile.other_social_link
            mentor.profile_picture = mentor_profile.profile_picture
            mentor.why_mentor = mentor_profile.why_mentor
            mentor.mentorship_topics = mentor_profile.mentorship_topics
            mentor.mentorship_type_preference = mentor_profile.mentorship_type_preference
            mentor.availability = mentor_profile.availability
            mentor.connect_frequency = mentor_profile.connect_frequency
            mentor.preferred_duration = mentor_profile.preferred_duration
            mentor.highest_qualification = mentor_profile.highest_qualification
            mentor.degree_name = mentor_profile.degree_name
            mentor.field_of_study = mentor_profile.field_of_study
            mentor.university_name = mentor_profile.university_name
            mentor.graduation_year = mentor_profile.graduation_year
            mentor.academic_status = mentor_profile.academic_status
            mentor.certifications = mentor_profile.certifications
            mentor.research_work = mentor_profile.research_work
            mentor.mentorship_philosophy = mentor_profile.mentorship_philosophy
            mentor.mentorship_motto = mentor_profile.mentorship_motto
            mentor.is_profile_complete = check_profile_complete(user.id, "1", profile_obj=mentor_profile)
        else:
            # Use basic user data as fallback for incomplete profiles
            mentor.id = user.id
            mentor.user_id = user.id
            mentor.user = user
            mentor.profession = None
            mentor.organisation = None
            mentor.location = None
            mentor.years_of_experience = None
            mentor.education = None
            mentor.language = None
            mentor.preferred_communication = None
            mentor.skills = None
            mentor.role = None
            mentor.industry_sector = None
            mentor.linkedin_link = None
            mentor.github_link = None
            mentor.portfolio_link = None
            mentor.other_social_link = None
            mentor.profile_picture = user.profile_picture if hasattr(user, 'profile_picture') else None  # Use user's profile pic if available
            mentor.why_mentor = None
            mentor.mentorship_topics = None
            mentor.mentorship_type_preference = None
            mentor.availability = None
            mentor.connect_frequency = None
            mentor.preferred_duration = None
            mentor.highest_qualification = None
            mentor.degree_name = None
            mentor.field_of_study = None
            mentor.university_name = None
            mentor.graduation_year = None
            mentor.academic_status = None
            mentor.certifications = None
            mentor.research_work = None
            mentor.mentorship_philosophy = None
            mentor.mentorship_motto = None
            mentor.is_profile_complete = False
        
        all_mentors.append(mentor)
    
    # Apply filters to enriched mentor list
    filtered_mentors = all_mentors
    
    if profession:
        filtered_mentors = [m for m in filtered_mentors if m.profession == profession]
    if location:
        filtered_mentors = [m for m in filtered_mentors if m.location == location]
    if education:
        filtered_mentors = [m for m in filtered_mentors if m.education == education]
    if experience:
        filtered_mentors = [m for m in filtered_mentors if m.years_of_experience]
        if experience == "0-2":
            filtered_mentors = [m for m in filtered_mentors if 0 <= int(m.years_of_experience) <= 2]
        elif experience == "3-5":
            filtered_mentors = [m for m in filtered_mentors if 3 <= int(m.years_of_experience) <= 5]
        elif experience == "6-10":
            filtered_mentors = [m for m in filtered_mentors if 6 <= int(m.years_of_experience) <= 10]
        elif experience == "10+":
            filtered_mentors = [m for m in filtered_mentors if int(m.years_of_experience) >= 10]
    
    all_mentors = filtered_mentors
    
    # Calculate suggestions if mentee is logged in
    suggested_mentors = []
    if mentee_profile:
        suggested_mentors = calculate_mentor_suggestions(mentee_profile, all_mentors, current_user_id)
    
    # Get filter options from all mentor profiles (not all mentors)
    mentor_profiles = MentorProfile.query.all()
    options = {
        "professions": sorted({row.profession for row in mentor_profiles if row.profession}),
        "locations": sorted({row.location for row in mentor_profiles if row.location}),
        "educations": sorted({row.education for row in mentor_profiles if row.education}),
        "experiences": sorted({row.years_of_experience for row in mentor_profiles if row.years_of_experience}),
    }

    # Dynamic render/redirect based on source
    if source_page == "supervisor_find_mentor" or session.get("user_type") in ("0", "3"):
        return render_template(
        "supervisor/supervisor_find_mentor.html",
        mentors=all_mentors,
        all_mentors=all_mentors,
        suggested_mentors=suggested_mentors,
        professions=options["professions"],
        locations=options["locations"],
        educations=options["educations"],
        experiences=options["experiences"],
        show_sidebar=True
        )
    else:  # default mentee
        return render_template(
        "mentee/mentee_find_mentors.html",
        all_mentors=all_mentors,
        suggested_mentors=suggested_mentors,
        professions=options["professions"],
        locations=options["locations"],
        educations=options["educations"],
        experiences=options["experiences"],
        active_section="findmentor",
        show_sidebar=True,
        current_user=current_user
    )


@app.route("/api/mentor_sourcing_request", methods=["POST"])
def submit_mentor_sourcing_request():
    """Handle mentor sourcing / feedback request submitted by mentee."""
    if "email" not in session:
        return jsonify({"success": False, "error": "Please sign in to submit a request."}), 401

    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return jsonify({"success": False, "error": "User account not found."}), 404

    target_role = (request.form.get("target_role") or "").strip()
    target_industry = (request.form.get("target_industry") or "").strip()
    skills_needed = (request.form.get("skills_needed") or "").strip()
    preferred_experience = (request.form.get("preferred_experience") or "").strip()
    linkedin_profile = (request.form.get("linkedin_profile") or "").strip()
    message = (request.form.get("message") or "").strip()
    countries = (request.form.get("countries") or "").strip()
    languages = (request.form.get("languages") or "").strip()

    if not target_role:
        return jsonify({"success": False, "error": "Please enter the target role or title."}), 400
    if not target_industry:
        return jsonify({"success": False, "error": "Please enter the target industry or domain."}), 400
    if not message:
        return jsonify({"success": False, "error": "Please provide details on what you are looking for."}), 400

    # Prepend country and language metadata to message if provided
    meta_parts = []
    if countries:
        meta_parts.append("[Preferred Countries]: " + countries)
    if languages:
        meta_parts.append("[Preferred Languages]: " + languages)
    if meta_parts:
        message = "\n".join(meta_parts) + "\n\n" + message

    try:
        req = MentorSourcingRequest(
            mentee_id=user.id,
            name=user.name,
            email=user.email,
            target_role=target_role,
            target_industry=target_industry,
            skills_needed=skills_needed,
            preferred_experience=preferred_experience,
            linkedin_profile=linkedin_profile,
            message=message,
            status="pending",
            created_at=datetime.utcnow()
        )
        db.session.add(req)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Thank you! Your mentor request has been submitted. Our team will review your specifics and work to source a mentor for you."
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "An error occurred while saving your request. Please try again."}), 500


def calculate_mentor_suggestions(mentee_profile, all_mentors, current_user_id):
    """
    Calculate mentor suggestions based on matching criteria
    Returns list of mentors with suggestion percentage
    """
    suggestions = []
    
    # Get current mentee's user info
    current_user = User.query.get(current_user_id)
    
    for mentor in all_mentors:
        score = 0
        max_score = 100
        
        # 1. Institution Match (30% weight)
        if current_user and mentor.user and current_user.institution == mentor.user.institution:
            score += 30
            
        # 2. Industry/Field Match (25% weight)
        if mentee_profile.who_am_i and mentor.industry_sector:
            # Map mentee categories to mentor industries
            industry_matches = {
                'university_student': ['Education', 'Technology', 'Research'],
                'school_student': ['Education', 'Career Development'],
                'young_professional': ['Technology', 'Business', 'Finance', 'Marketing'],
                'seeking_internship': ['Technology', 'Business', 'Healthcare'],
                'exploring': ['Career Development', 'Business', 'Education']
            }
            
            if mentee_profile.who_am_i in industry_matches:
                if mentor.industry_sector in industry_matches[mentee_profile.who_am_i]:
                    score += 25
                elif any(keyword in mentor.industry_sector.lower() for keyword in ['tech', 'business', 'education']):
                    score += 15
                    
        # 3. Skills Match (20% weight)
        if mentee_profile.key_skills and mentor.skills:
            mentee_skills = set([skill.strip().lower() for skill in mentee_profile.key_skills.split(',') if skill.strip()])
            mentor_skills = set([skill.strip().lower() for skill in mentor.skills.split(',') if skill.strip()])
            
            if mentee_skills.intersection(mentor_skills):
                overlap_ratio = len(mentee_skills.intersection(mentor_skills)) / len(mentee_skills) if mentee_skills else 0
                score += min(20, overlap_ratio * 20)
                
        # 4. Location Match (15% weight)
        mentee_location = f"{mentee_profile.city}, {mentee_profile.country}" if mentee_profile.city and mentee_profile.country else ""
        if mentee_location and mentor.location:
            if mentee_location.lower() == mentor.location.lower():
                score += 15
            elif mentee_profile.country and mentee_profile.country.lower() in mentor.location.lower():
                score += 10
                
        # 5. Mentorship Topics Match (10% weight)
        if mentee_profile.mentorship_expectations and mentor.mentorship_topics:
            mentee_expectations = mentee_profile.mentorship_expectations.lower()
            mentor_topics = mentor.mentorship_topics.lower()
            
            # Check for common keywords
            common_keywords = ['career', 'skill', 'interview', 'job', 'development', 'guidance']
            matches = sum(1 for keyword in common_keywords if keyword in mentee_expectations and keyword in mentor_topics)
            if matches > 0:
                score += min(10, matches * 2)
        
        # Only include mentors with 60%+ match as suggestions
        if score >= 60:
            suggestions.append({
                'mentor': mentor,
                'suggestion_percentage': min(100, int(score))
            })
    
    # Sort by suggestion percentage (highest first) and limit to top 10
    suggestions.sort(key=lambda x: x['suggestion_percentage'], reverse=True)
    return suggestions[:10]

@app.route("/find_mentees", methods=["GET"])
@cache.cached(timeout=60, query_string=True)
def find_mentees():
    if "email" not in session or session.get("user_type") != "1": 
        return redirect(url_for("signin"))

    # Base query
    query = MenteeProfile.query.join(User, MenteeProfile.user_id == User.id)

    source_page = request.args.get("from", "mentor")

    # Filters
    search_query = request.args.get("search", "").lower()
    stream_filter = request.args.get("stream", "")
    school_filter = request.args.get("school", "")
    goal_filter = request.args.get("goal", "")

    if search_query:
        query = query.filter(
            or_(
                User.name.ilike(f"%{search_query}%"),
                MenteeProfile.stream.ilike(f"%{search_query}%"),
                MenteeProfile.school_college_name.ilike(f"%{search_query}%")
            )
        )

    if stream_filter:
        query = query.filter(MenteeProfile.stream == stream_filter)
    if school_filter:
        query = query.filter(MenteeProfile.school_college_name == school_filter)
    if goal_filter:
        query = query.filter(MenteeProfile.goal == goal_filter)

    filtered_mentees = query.all()
    

    # Get filter options directly
    streams = sorted({m.stream for m in MenteeProfile.query.with_entities(MenteeProfile.stream).distinct() if m.stream})
    schools = sorted({m.school_college_name for m in MenteeProfile.query.with_entities(MenteeProfile.school_college_name).distinct() if m.school_college_name})
    goals = sorted({m.goal for m in MenteeProfile.query.with_entities(MenteeProfile.goal).distinct() if m.goal})

    
    # Dynamic render/redirect based on source
    if source_page == "supervisor":
        return render_template(
            "supervisor/supervisor_find_mentee.html",
            all_mentees=filtered_mentees,
            streams=streams,
            schools=schools,
            goals=goals,
            active_section="mentees",
            show_sidebar=True
        )
    else:  # default mentor
        return render_template(
            "mentor/mentor_find_mentees.html",
            all_mentees=filtered_mentees,
            streams=streams,
            schools=schools,
            goals=goals,
            active_section="findmentees",
            show_sidebar=True
        )

# mentee dashboard to my mentors
class MentorLite:
    """Minimal MentorProfile stand-in for a mentor with no profile yet.
    Exposes `.user` and all MentorProfile attribute names as empty strings
    so templates can render them safely."""

    def __init__(self, user):
        self.user = user
        for attr in [
            "profile_picture", "profession", "organisation", "location",
            "years_of_experience", "education", "language",
            "preferred_communication", "why_mentor", "role",
            "industry_sector", "skills", "availability",
            "mentorship_topics", "linkedin_link", "github_link",
            "portfolio_link", "preferred_duration",
            "mentorship_type_preference", "connect_frequency",
            "whatsapp", "highest_qualification", "degree_name",
            "field_of_study", "university_name", "graduation_year",
            "academic_status", "certifications", "research_work",
            "mentorship_philosophy", "mentorship_motto", "other_social_link",
        ]:
            setattr(self, attr, "")

@app.route("/my_mentors")
def my_mentors():
    if "email" not in session or session.get("user_type") != "2":
        return redirect(url_for("signin"))

    # Fetch current mentee
    mentee = User.query.filter_by(email=session["email"]).first()

    if not mentee:
        flash("Mentee profile not found.", "error")
        return redirect(url_for("signin"))

    profile_complete = check_profile_complete(mentee.id, "2")

    # A fully approved request means: Mentor accepted AND Supervisor approved AND system final approval is done.
    accepted_requests = MentorshipRequest.query.filter_by(
        mentee_id=mentee.id,
        
        supervisor_status="approved",
        final_status="approved"
    ).all()

    my_mentors = []
    for req in accepted_requests:
        if req.mentor:
            mentor_data = {
                "mentorship_id": req.id,
                "completed": False,
                "completion_pct": 0
            }
            done, pct = _check_mentorship_completed(req.mentee_id, req.mentor_id)
            mentor_data["completed"] = done
            mentor_data["completion_pct"] = pct
            mentor_data["rating"] = compute_mentorship_composite_rating(req.mentee_id, req.mentor_id)
            if req.mentor.mentor_profile:
                mp = req.mentor.mentor_profile
                mentor_data["profile"] = mp
                mentor_data["user"] = req.mentor
            else:
                mentor_data["profile"] = MentorLite(req.mentor)
                mentor_data["user"] = req.mentor
            my_mentors.append(mentor_data)

    return render_template(
        "mentee/mentee_my_mentors.html",
        my_mentors=my_mentors,
        show_sidebar=True,
        profile_complete=profile_complete
    )

@app.route("/my_mentees")
def my_mentees():
    if "email" not in session or session.get("user_type") != "1":
        return redirect(url_for("signin"))

    mentor = User.query.filter_by(email=session["email"]).first()
    profile_complete = check_profile_complete(mentor.id, "1")
    
    if not mentor:
        flash("Mentor profile not found.", "error")
        return redirect(url_for("signin"))

    accepted_requests = MentorshipRequest.query.options(
        joinedload(MentorshipRequest.mentee).joinedload(User.mentee_profile)
    ).filter_by(
        mentor_id=mentor.id,
        supervisor_status="approved",
        final_status="approved"
    ).all()

    my_mentees_data = []
    for req in accepted_requests:
        if req.mentee:
            mentee_profile = req.mentee.mentee_profile
            done, pct = _check_mentorship_completed(req.mentee_id, req.mentor_id)
            if mentee_profile:
                mentee_profile_complete = check_profile_complete(req.mentee.id, "2")
                
                my_mentees_data.append({
                    "mentorship_id": req.id,
                    "completed": done,
                    "completion_pct": pct,
                    "rating": compute_mentorship_composite_rating(req.mentee_id, req.mentor_id),
                    "user": {
                        "name": req.mentee.name,
                        "email": req.mentee.email
                    },
                    "profile": {
                        # General Details
                        "father_name": mentee_profile.father_name,
                        "address_line1": mentee_profile.address_line1,
                        "address_line2": mentee_profile.address_line2,
                        "city": mentee_profile.city,
                        "state": mentee_profile.state,
                        "postal_code": mentee_profile.postal_code,
                        "country": mentee_profile.country,
                        
                        # Who am I
                        "who_am_i": mentee_profile.who_am_i,
                        
                        # Common fields
                        "dob": mentee_profile.dob,
                        "mobile_number": mentee_profile.mobile_number,
                        "whatsapp_number": mentee_profile.whatsapp_number,
                        "mentorship_expectations": mentee_profile.mentorship_expectations,
                        
                        # School Student fields
                        "school_name": mentee_profile.school_name,
                        "school_board": mentee_profile.school_board,
                        "school_passing_year": mentee_profile.school_passing_year,
                        "favourite_subject": mentee_profile.favourite_subject,
                        
                        # University Student fields
                        "institution_name": mentee_profile.institution_name,
                        "board_university": mentee_profile.board_university,
                        "course_stream": mentee_profile.course_stream,
                        "education_level": mentee_profile.education_level,
                        
                        # Seeking Internship fields
                        "career_interest": mentee_profile.career_interest,
                        "key_skills": mentee_profile.key_skills,
                        
                        # Young Professional fields
                        "current_role": mentee_profile.current_role,
                        "industry": mentee_profile.industry,
                        "years_experience": mentee_profile.years_experience,
                        "current_organization": mentee_profile.current_organization,
                        "career_goal": mentee_profile.career_goal,
                        
                        # Exploring fields
                        "main_challenge": mentee_profile.main_challenge,
                        
                        # Old fields (for backward compatibility)
                        "school_college_name": mentee_profile.school_college_name,
                        "govt_private": mentee_profile.govt_private,
                        "stream": mentee_profile.stream,
                        "class_year": mentee_profile.class_year,
                        "goal": mentee_profile.goal,
                        "parent_name": mentee_profile.parent_name,
                        "parent_mobile": mentee_profile.parent_mobile,
                        "comments": mentee_profile.comments,
                        "terms_agreement": mentee_profile.terms_agreement,
                        "profile_picture": mentee_profile.profile_picture,
                        "profile_complete": mentee_profile_complete 
                    }
                })

    return render_template(
        "mentor/mentor_my_mentees.html",
        my_mentees=my_mentees_data,
        show_sidebar=True,
        profile_complete=profile_complete
    )

@app.route("/supervisor_find_mentor")
def supervisor_find_mentor():
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))

    profession = request.args.get("profession")
    location = request.args.get("location")
    education = request.args.get("education")
    experience = request.args.get("experience")

    # Fetch ALL mentors (including incomplete profiles)
    all_users = User.query.filter_by(user_type="1").all()
    
    # Create enriched mentor objects with fallback data
    enriched_mentors = []
    for user in all_users:
        profile = MentorProfile.query.filter_by(user_id=user.id).first()
        
        if profile:
            # Complete profile exists - use it
            enriched_mentor = {
                'id': profile.id,
                'user_id': user.id,
                'user': user,
                'profession': profile.profession,
                'organisation': profile.organisation,
                'location': profile.location,
                'years_of_experience': profile.years_of_experience,
                'profile_picture': profile.profile_picture,
                'education': profile.education,
                'language': profile.language,
                'preferred_communication': profile.preferred_communication,
                'why_mentor': profile.why_mentor,
                'role': profile.role,
                'industry_sector': profile.industry_sector,
                'skills': profile.skills,
                'availability': profile.availability,
                'mentorship_topics': profile.mentorship_topics,
                'linkedin_link': profile.linkedin_link,
                'github_link': profile.github_link,
                'portfolio_link': profile.portfolio_link,
                'preferred_duration': profile.preferred_duration,
                'mentorship_type_preference': profile.mentorship_type_preference,
                'connect_frequency': profile.connect_frequency,
                'whatsapp': profile.whatsapp,
                'highest_qualification': profile.highest_qualification,
                'degree_name': profile.degree_name,
                'field_of_study': profile.field_of_study,
                'university_name': profile.university_name,
                'graduation_year': profile.graduation_year,
                'academic_status': profile.academic_status,
                'certifications': profile.certifications,
                'research_work': profile.research_work,
                'mentorship_philosophy': profile.mentorship_philosophy,
                'mentorship_motto': profile.mentorship_motto,
                'other_social_link': profile.other_social_link,
                'criminal_certificate': profile.criminal_certificate,
                'is_profile_complete': True
            }
        else:
            # No profile yet - create basic fallback object
            enriched_mentor = {
                'id': user.id,
                'user_id': user.id,
                'user': user,
                'profession': None,
                'organisation': None,
                'location': None,
                'years_of_experience': None,
                'profile_picture': None,
                'education': None,
                'language': None,
                'preferred_communication': None,
                'why_mentor': None,
                'role': None,
                'industry_sector': None,
                'skills': None,
                'availability': None,
                'mentorship_topics': None,
                'linkedin_link': None,
                'github_link': None,
                'portfolio_link': None,
                'preferred_duration': None,
                'mentorship_type_preference': None,
                'connect_frequency': None,
                'whatsapp': None,
                'highest_qualification': None,
                'degree_name': None,
                'field_of_study': None,
                'university_name': None,
                'graduation_year': None,
                'academic_status': None,
                'certifications': None,
                'research_work': None,
                'mentorship_philosophy': None,
                'mentorship_motto': None,
                'other_social_link': None,
                'criminal_certificate': None,
                'is_profile_complete': False
            }
        
        enriched_mentors.append(enriched_mentor)

    # Apply filters to enriched mentors
    filtered_mentors = enriched_mentors
    
    if profession:
        filtered_mentors = [m for m in filtered_mentors if m.get('profession') == profession]
    if location:
        filtered_mentors = [m for m in filtered_mentors if m.get('location') == location]
    if education:
        filtered_mentors = [m for m in filtered_mentors if m.get('education') == education]
    if experience:
        filtered_mentors = [m for m in filtered_mentors if m.get('years_of_experience')]
        if experience == "0-2":
            filtered_mentors = [m for m in filtered_mentors if int(m.get('years_of_experience', 0)) <= 2]
        elif experience == "3-5":
            filtered_mentors = [m for m in filtered_mentors if 3 <= int(m.get('years_of_experience', 0)) <= 5]
        elif experience == "6-10":
            filtered_mentors = [m for m in filtered_mentors if 6 <= int(m.get('years_of_experience', 0)) <= 10]
        elif experience == "10+":
            filtered_mentors = [m for m in filtered_mentors if int(m.get('years_of_experience', 0)) >= 10]

    # Sort by user creation timestamp (oldest first) and add serial numbers
    filtered_mentors.sort(key=lambda m: m['user'].created_at if m['user'].created_at else datetime.min)
    for idx, m in enumerate(filtered_mentors, 1):
        m['serial'] = idx

    # Get unique filter options from all enriched mentors
    professions = sorted({m.get('profession') for m in enriched_mentors if m.get('profession')})
    locations = sorted({m.get('location') for m in enriched_mentors if m.get('location')})
    educations = sorted({m.get('education') for m in enriched_mentors if m.get('education')})
    experiences = sorted({m.get('years_of_experience') for m in enriched_mentors if m.get('years_of_experience')})

    return render_template(
        "supervisor/supervisor_find_mentor.html",
        mentors=filtered_mentors,
        professions=professions,
        locations=locations,
        educations=educations,
        experiences=experiences,
        active_section="mentors",
        show_sidebar=True
    )

@app.route("/supervisor_find_mentee")
def supervisor_find_mentee():
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))

    mentee_query = MenteeProfile.query.join(User, MenteeProfile.user_id == User.id)
    search_query = request.args.get("search", "").lower()
    stream_filter = request.args.get("stream", "")
    school_filter = request.args.get("school", "")
    who_am_i_filter = request.args.get("who_am_i", "")
    consent_filter = request.args.get("consent_status", "")
    city_filter = request.args.get("city", "")
    state_filter = request.args.get("state", "")
    govt_private_filter = request.args.get("govt_private", "")
    education_level_filter = request.args.get("education_level", "")

    if search_query:
        mentee_query = mentee_query.filter(
            or_(
                User.name.ilike(f"%{search_query}%"),
                MenteeProfile.stream.ilike(f"%{search_query}%"),
                MenteeProfile.school_college_name.ilike(f"%{search_query}%")
            )
        )
    if stream_filter:
        mentee_query = mentee_query.filter(MenteeProfile.stream == stream_filter)
    if school_filter:
        mentee_query = mentee_query.filter(MenteeProfile.school_college_name == school_filter)
    if who_am_i_filter:
        mentee_query = mentee_query.filter(MenteeProfile.who_am_i == who_am_i_filter)
    if consent_filter:
        mentee_query = mentee_query.filter(MenteeProfile.parent_consent_status == consent_filter)
    if city_filter:
        mentee_query = mentee_query.filter(MenteeProfile.city == city_filter)
    if state_filter:
        mentee_query = mentee_query.filter(MenteeProfile.state == state_filter)
    if govt_private_filter:
        mentee_query = mentee_query.filter(MenteeProfile.govt_private == govt_private_filter)
    if education_level_filter:
        mentee_query = mentee_query.filter(MenteeProfile.education_level == education_level_filter)

    # Order by user creation timestamp and add serial numbers
    mentee_query = mentee_query.order_by(User.created_at.asc())
    all_mentees = mentee_query.all()
    for idx, m in enumerate(all_mentees, 1):
        m.serial = idx

    mentee_streams = sorted({row[0] for row in MenteeProfile.query.with_entities(MenteeProfile.stream).distinct() if row[0]})
    mentee_schools = sorted({row[0] for row in MenteeProfile.query.with_entities(MenteeProfile.school_college_name).distinct() if row[0]})
    mentee_who_am_i = sorted({row[0] for row in MenteeProfile.query.with_entities(MenteeProfile.who_am_i).distinct() if row[0]})
    mentee_consent_statuses = ["pending", "approved", "rejected"]
    mentee_cities = sorted({row[0] for row in MenteeProfile.query.with_entities(MenteeProfile.city).distinct() if row[0]})
    mentee_states = sorted({row[0] for row in MenteeProfile.query.with_entities(MenteeProfile.state).distinct() if row[0]})
    mentee_govt_private = sorted({row[0] for row in MenteeProfile.query.with_entities(MenteeProfile.govt_private).distinct() if row[0]})
    mentee_education_levels = sorted({row[0] for row in MenteeProfile.query.with_entities(MenteeProfile.education_level).distinct() if row[0]})

    return render_template(
        "supervisor/supervisor_find_mentee.html",
        mentees=all_mentees,
        mentee_streams=mentee_streams,
        mentee_schools=mentee_schools,
        mentee_who_am_i=mentee_who_am_i,
        mentee_consent_statuses=mentee_consent_statuses,
        mentee_cities=mentee_cities,
        mentee_states=mentee_states,
        mentee_govt_private=mentee_govt_private,
        mentee_education_levels=mentee_education_levels,
        active_section="mentees",
        show_sidebar=True
    )

# supervisor view requests
@app.route("/requests")
def view_requests():
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))

    # Get status filter from query params (default: pending)
    status_filter = request.args.get("status", "pending")

    # Fetch mentorship requests with proper eager loading of profile relationships
    from sqlalchemy.orm import joinedload
    
    mentorship_query = MentorshipRequest.query.options(
        joinedload(MentorshipRequest.mentee).joinedload(User.mentee_profile),
        joinedload(MentorshipRequest.mentor).joinedload(User.mentor_profile)
    )

    if status_filter == "pending":
        mentorship_query = mentorship_query.filter(
            MentorshipRequest.supervisor_status == "pending"
        )
    elif status_filter == "approved":
        mentorship_query = mentorship_query.filter(
            MentorshipRequest.final_status == "approved"
        )
    elif status_filter == "rejected":
        mentorship_query = mentorship_query.filter(
            MentorshipRequest.final_status == "rejected"
        )
    # "all" shows everything (no additional filter)

    all_mentorship_requests = mentorship_query.order_by(MentorshipRequest.created_at.desc()).all()
    
    mentor_requests = MentorProfile.query.filter_by(status="pending").all()
    mentee_requests = MenteeProfile.query.filter_by(status="pending").all()
    sourcing_requests_count = MentorSourcingRequest.query.count()

    return render_template(
        "supervisor/supervisor_request.html",
        all_requests=all_mentorship_requests,
        mentor_requests=mentor_requests,
        mentee_requests=mentee_requests,
        sourcing_requests_count=sourcing_requests_count,
        status_filter=status_filter,
        active_section="requests",
        show_sidebar=True
    )


@app.route("/supervisor/mentor_sourcing_requests")
def supervisor_sourcing_requests():
    """Subpage showing mentor sourcing / feedback requests submitted by mentees."""
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))

    status_filter = request.args.get("status", "all")
    query = MentorSourcingRequest.query.options(joinedload(MentorSourcingRequest.mentee))

    if status_filter in ("pending", "sourcing", "resolved"):
        query = query.filter_by(status=status_filter)

    requests_list = query.order_by(MentorSourcingRequest.created_at.desc()).all()

    total_count = MentorSourcingRequest.query.count()
    pending_count = MentorSourcingRequest.query.filter_by(status="pending").count()
    sourcing_count = MentorSourcingRequest.query.filter_by(status="sourcing").count()
    resolved_count = MentorSourcingRequest.query.filter_by(status="resolved").count()

    return render_template(
        "supervisor/supervisor_sourcing_requests.html",
        requests=requests_list,
        status_filter=status_filter,
        total_count=total_count,
        pending_count=pending_count,
        sourcing_count=sourcing_count,
        resolved_count=resolved_count,
        active_section="requests",
        show_sidebar=True
    )


@app.route("/api/mentor_sourcing_request/<int:req_id>/status", methods=["POST"])
def update_mentor_sourcing_request_status(req_id):
    """Update status of a mentor sourcing request (pending, sourcing, resolved)."""
    if "email" not in session or session.get("user_type") != "0":
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    req = MentorSourcingRequest.query.get_or_404(req_id)
    new_status = (request.form.get("status") or "").strip().lower()
    if new_status not in ("pending", "sourcing", "resolved"):
        return jsonify({"success": False, "error": "Invalid status."}), 400

    old_status = req.status
    req.status = new_status
    db.session.commit()

    # Notify mentee on status changes (except when resolving, which has its own endpoint)
    if new_status != "resolved" and req.mentee:
        status_labels = {"pending": "Pending", "sourcing": "In Progress", "resolved": "Resolved"}
        label = status_labels.get(new_status, new_status.capitalize())
        msg_parts = []
        if '[Preferred Countries]:' in (req.message or ''):
            for line in req.message.split('\n'):
                if line.startswith('[Preferred Countries]:'):
                    msg_parts.append(line.replace('[Preferred Countries]:', '').strip())
        create_notification(
            req.mentee.id,
            f"Your mentor sourcing request for '{req.target_role}' has been updated to '{label}'.",
            url_for("mentee_sourcing_requests")
        )

    return jsonify({"success": True, "message": f"Status updated to {new_status.capitalize()}."})


def _parse_resolved_mentors(message_text):
    """Parse resolved mentors from message metadata. Returns list of dicts."""
    mentors = []
    if not message_text:
        return mentors
    for line in message_text.split('\n'):
        if line.startswith('[Resolved Mentors]:'):
            mentors_str = line.replace('[Resolved Mentors]:', '').strip()
            if mentors_str:
                for part in mentors_str.split('||'):
                    part = part.strip()
                    if '(ID:' in part:
                        name = part.split('(ID:')[0].strip()
                        try:
                            mid = int(part.split('(ID:')[1].rstrip(')').strip())
                        except (ValueError, IndexError):
                            mid = None
                        mentors.append({"name": name, "id": mid})
    return mentors


def _build_resolved_mentors_line(mentors_list):
    """Build the [Resolved Mentors] metadata line from a list of dicts."""
    if not mentors_list:
        return ""
    parts = []
    for m in mentors_list:
        if m.get("id"):
            parts.append(f"{m['name']} (ID:{m['id']})")
        else:
            parts.append(m.get("name", "Unknown"))
    return "[Resolved Mentors]: " + " || ".join(parts)


@app.route("/api/mentor_sourcing_request/<int:req_id>/resolve", methods=["POST"])
def resolve_mentor_sourcing_request(req_id):
    """Resolve a sourcing request with attached mentor profiles and notify mentee."""
    if "email" not in session or session.get("user_type") != "0":
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    req = MentorSourcingRequest.query.get_or_404(req_id)
    mentee = req.mentee

    # Get mentor IDs from form (comma-separated)
    mentor_ids_str = (request.form.get("mentor_ids") or "").strip()
    mentor_names_str = (request.form.get("mentor_names") or "").strip()

    mentors_list = []
    if mentor_ids_str:
        ids = [int(x.strip()) for x in mentor_ids_str.split(",") if x.strip().isdigit()]
        names = [n.strip() for n in mentor_names_str.split(",")] if mentor_names_str else []
        for i, mid in enumerate(ids):
            # Verify mentor exists
            mentor_user = User.query.get(mid)
            if mentor_user and mentor_user.user_type == "1":
                name = names[i] if i < len(names) else mentor_user.name
                mentors_list.append({"name": name, "id": mid})

    # Build message with resolved mentors metadata
    message = req.message or ""
    # Remove any existing resolved mentors line
    lines = [l for l in message.split('\n') if not l.startswith('[Resolved Mentors]:')]
    resolved_line = _build_resolved_mentors_line(mentors_list)
    if resolved_line:
        lines.append(resolved_line)
    # Add resolution date
    lines.append(f"[Resolution Date]: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    req.message = '\n'.join(lines)

    req.status = "resolved"
    db.session.commit()

    # Notify mentee
    if mentee:
        mentor_names = [m["name"] for m in mentors_list]
        if mentor_names:
            mentor_list_str = ", ".join(mentor_names[:-1]) + " and " + mentor_names[-1] if len(mentor_names) > 1 else mentor_names[0]
            notif_msg = f"Your mentor sourcing request for '{req.target_role}' has been resolved! Mentors found: {mentor_list_str}."
        else:
            notif_msg = f"Your mentor sourcing request for '{req.target_role}' has been resolved."
        create_notification(
            mentee.id,
            notif_msg,
            url_for("mentee_sourcing_requests")
        )

        # Send email notification
        try:
            subject = "Your Mentor Sourcing Request Has Been Resolved"
            mentor_rows = ""
            for m in mentors_list:
                mentor_rows += f"""
                <tr>
                    <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-weight:600;color:#111827;">{m['name']}</td>
                    <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;color:#6b7280;">{m.get('id', 'N/A')}</td>
                </tr>"""
            html_content = f"""
            <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
                <div style="background:linear-gradient(135deg,#2563eb,#7c3aed);padding:24px;border-radius:12px 12px 0 0;text-align:center;">
                    <h1 style="color:white;margin:0;font-size:22px;">Mentor Connect</h1>
                </div>
                <div style="background:#f9fafb;padding:24px;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 12px 12px;">
                    <h2 style="color:#111827;margin-top:0;">Hello {mentee.name},</h2>
                    <p style="color:#374151;line-height:1.6;">Great news! Your mentor sourcing request has been resolved. Here are the mentors our team has sourced for you:</p>
                    <table style="width:100%;border-collapse:collapse;margin:16px 0;background:white;border-radius:8px;overflow:hidden;border:1px solid #e5e7eb;">
                        <thead><tr style="background:#f3f4f6;"><th style="padding:8px 12px;text-align:left;font-size:12px;color:#6b7280;text-transform:uppercase;">Mentor Name</th><th style="padding:8px 12px;text-align:left;font-size:12px;color:#6b7280;text-transform:uppercase;">Profile ID</th></tr></thead>
                        <tbody>{mentor_rows}</tbody>
                    </table>
                    <p style="color:#374151;line-height:1.6;">You can now browse the Find Mentors page to view these mentors and send mentorship requests.</p>
                    <div style="text-align:center;margin-top:24px;">
                        <a href="{url_for('find_mentor', _external=True)}" style="display:inline-block;padding:12px 28px;background:#2563eb;color:white;border-radius:8px;text-decoration:none;font-weight:600;">Browse Mentors</a>
                    </div>
                </div>
            </div>"""
            send_email_reminder(mentee.email, subject, html_content)
        except Exception as e:
            print(f"Error sending resolve email: {e}")

    return jsonify({
        "success": True,
        "message": f"Request resolved with {len(mentors_list)} mentor(s). Mentee has been notified."
    })


@app.route("/api/mentor_sourcing_request/<int:req_id>/add_mentors", methods=["POST"])
def add_mentors_to_sourcing_request(req_id):
    """Add more mentors to an already resolved sourcing request."""
    if "email" not in session or session.get("user_type") != "0":
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    req = MentorSourcingRequest.query.get_or_404(req_id)
    if req.status != "resolved":
        return jsonify({"success": False, "error": "Request must be resolved before adding mentors."}), 400

    mentor_ids_str = (request.form.get("mentor_ids") or "").strip()
    mentor_names_str = (request.form.get("mentor_names") or "").strip()

    # Parse existing resolved mentors
    existing = _parse_resolved_mentors(req.message)
    existing_ids = {m["id"] for m in existing if m.get("id")}

    # Add new mentors
    added = 0
    if mentor_ids_str:
        ids = [int(x.strip()) for x in mentor_ids_str.split(",") if x.strip().isdigit()]
        names = [n.strip() for n in mentor_names_str.split(",")] if mentor_names_str else []
        for i, mid in enumerate(ids):
            if mid not in existing_ids:
                mentor_user = User.query.get(mid)
                if mentor_user and mentor_user.user_type == "1":
                    name = names[i] if i < len(names) else mentor_user.name
                    existing.append({"name": name, "id": mid})
                    added += 1

    # Rebuild message
    message = req.message or ""
    lines = [l for l in message.split('\n') if not l.startswith('[Resolved Mentors]:')]
    resolved_line = _build_resolved_mentors_line(existing)
    if resolved_line:
        lines.append(resolved_line)
    req.message = '\n'.join(lines)
    db.session.commit()

    # Notify mentee about new mentors
    if added > 0 and req.mentee:
        new_names = [m["name"] for m in existing if m.get("id") not in existing_ids or m.get("id") in {int(x.strip()) for x in mentor_ids_str.split(",") if x.strip().isdigit()}]
        create_notification(
            req.mentee.id,
            f"Additional mentors have been added to your resolved sourcing request for '{req.target_role}'.",
            url_for("mentee_sourcing_requests")
        )

    return jsonify({
        "success": True,
        "message": f"Added {added} new mentor(s). Total: {len(existing)}."
    })


@app.route("/api/mentor_sourcing_request/<int:req_id>/resolved_mentors", methods=["GET"])
def get_resolved_mentors(req_id):
    """Get the list of resolved mentors for a sourcing request."""
    if "email" not in session or session.get("user_type") != "0":
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    req = MentorSourcingRequest.query.get_or_404(req_id)
    mentors = _parse_resolved_mentors(req.message)

    # Enrich with profile data
    enriched = []
    for m in mentors:
        if m.get("id"):
            mentor_user = User.query.get(m["id"])
            if mentor_user:
                mp = mentor_user.mentor_profile
                enriched.append({
                    "id": m["id"],
                    "name": mentor_user.name,
                    "profession": mp.profession if mp else None,
                    "organisation": mp.organisation if mp else None,
                    "location": mp.location if mp else None,
                    "skills": mp.skills if mp else None,
                    "profile_picture": mp.profile_picture if mp else None,
                })
            else:
                enriched.append({"id": m["id"], "name": m["name"]})
        else:
            enriched.append({"name": m.get("name", "Unknown")})

    return jsonify({"success": True, "mentors": enriched})


@app.route("/api/search_mentors", methods=["GET"])
def api_search_mentors():
    """Search mentors by name, profession, or skills for sourcing request modal."""
    if "email" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"success": True, "mentors": []})

    like_q = f"%{q}%"
    mentor_users = User.query.filter_by(user_type="1").options(
        joinedload(User.mentor_profile)
    ).filter(
        db.or_(
            User.name.ilike(like_q),
            User.email.ilike(like_q)
        )
    ).limit(50).all()

    # Also search by profession/skills in MentorProfile
    profile_matches = MentorProfile.query.filter(
        db.or_(
            MentorProfile.profession.ilike(like_q),
            MentorProfile.skills.ilike(like_q),
            MentorProfile.role.ilike(like_q),
            MentorProfile.organisation.ilike(like_q)
        )
    ).all()

    seen_ids = set()
    results = []

    for user in mentor_users:
        if user.id not in seen_ids:
            seen_ids.add(user.id)
            mp = user.mentor_profile
            results.append({
                "id": user.id,
                "name": user.name,
                "profession": mp.profession if mp else None,
                "organisation": mp.organisation if mp else None,
                "location": mp.location if mp else None,
                "skills": mp.skills if mp else None,
            })

    for mp in profile_matches:
        if mp.user_id not in seen_ids:
            seen_ids.add(mp.user_id)
            results.append({
                "id": mp.user_id,
                "name": mp.user.name if mp.user else "Unknown",
                "profession": mp.profession,
                "organisation": mp.organisation,
                "location": mp.location,
                "skills": mp.skills,
            })

    return jsonify({"success": True, "mentors": results[:30]})


@app.route("/mentee/sourcing_requests")
def mentee_sourcing_requests():
    """Mentee view of their own sourcing requests and resolved mentors."""
    if "email" not in session or session.get("user_type") != "2":
        return redirect(url_for("signin"))

    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("signin"))

    requests_list = MentorSourcingRequest.query.filter_by(mentee_id=user.id).order_by(
        MentorSourcingRequest.created_at.desc()
    ).all()

    # Enrich each resolved request with mentor data
    enriched_requests = []
    for req in requests_list:
        mentors = _parse_resolved_mentors(req.message)
        enriched_mentors = []
        for m in mentors:
            if m.get("id"):
                mentor_user = User.query.get(m["id"])
                if mentor_user:
                    mp = mentor_user.mentor_profile
                    enriched_mentors.append({
                        "id": m["id"],
                        "name": mentor_user.name,
                        "profession": mp.profession if mp else None,
                        "organisation": mp.organisation if mp else None,
                        "location": mp.location if mp else None,
                        "skills": mp.skills if mp else None,
                        "profile_picture": mp.profile_picture if mp else None,
                    })
        enriched_requests.append({
            "request": req,
            "resolved_mentors": enriched_mentors,
        })

    return render_template(
        "mentee/mentee_sourcing_requests.html",
        requests=enriched_requests,
        active_section="sourcing_requests",
        show_sidebar=True
    )


@app.route("/mentee_calendar")
def mentee_calendar():
    if "email" not in session or session.get("user_type") != "2":
        return redirect(url_for("signin"))
    
    # Get logged-in mentee
    mentee = User.query.filter_by(email=session["email"]).first()
    
    # Fetch all meetings created by this mentee
    meetings = MeetingRequest.query.filter_by(requester_id=mentee.id).order_by(
        MeetingRequest.meeting_date.asc(),
        MeetingRequest.meeting_time.asc()
    ).all()

    all_participants = _get_all_meeting_participants()
    extra_meeting_ids = []
    for mid, pdata in all_participants.items():
        if pdata.get("mentee_id") == mentee.id:
            extra_meeting_ids.append(mid)

    extra_meetings = []
    if extra_meeting_ids:
        extra_meetings = MeetingRequest.query.filter(
            MeetingRequest.id.in_(extra_meeting_ids),
            ~MeetingRequest.id.in_([m.id for m in meetings])
        ).order_by(
            MeetingRequest.meeting_date.asc(),
            MeetingRequest.meeting_time.asc()
        ).all()
    
    all_meetings = list(meetings) + list(extra_meetings)
    
    # Prepare meeting data for the calendar
    calendar_meetings = []
    for meeting in all_meetings:
        pdata = _get_meeting_participants(meeting.id)
        if pdata and pdata.get("mentor_id"):
            mentor = User.query.get(pdata["mentor_id"])
        else:
            mentor = User.query.get(meeting.requested_to_id)
        
        # Determine meeting status based on date/time
        meeting_datetime = datetime.combine(meeting.meeting_date, meeting.meeting_time)
        now = datetime.now()
        
        if meeting.status == "cancelled":
            status = "cancelled"
        elif meeting_datetime < now:
            status = "completed"
        else:
            status = "upcoming"
        
        calendar_meetings.append({
            "id": meeting.id,
            "title": meeting.meeting_title,
            "date": meeting_datetime,
            "duration": meeting.meeting_duration,
            "mentor": mentor.name if mentor else "Unknown Mentor",
            "type": "Video Call",  # You can add this field to your MeetingRequest model if needed
            "status": status,
            "description": meeting.meeting_description or "No description provided",
            "meet_link": meeting.meet_link
        })
    
    # Fetch mentee's approved mentors for the Schedule Meeting button
    accepted_requests = MentorshipRequest.query.filter_by(
        mentee_id=mentee.id,
        supervisor_status="approved",
        final_status="approved"
    ).all()
    
    my_mentors = []
    for req in accepted_requests:
        if req.mentor:
            my_mentors.append(req.mentor)
    
    return render_template(
        "mentee/mentee_calendar.html",
        show_sidebar=True,
        meetings=calendar_meetings,
        my_mentors=my_mentors,
        current_date=datetime.utcnow()
    )


@app.route("/mentor_calendar")
def mentor_calendar():
    if "email" not in session or session.get("user_type") != "1":
        return redirect(url_for("signin"))
    
    # Get logged-in mentor
    mentor = User.query.filter_by(email=session["email"]).first()
    
    # Fetch all meetings where this mentor is the requested_to person
    meetings = MeetingRequest.query.filter_by(requested_to_id=mentor.id).order_by(
        MeetingRequest.meeting_date.asc(),
        MeetingRequest.meeting_time.asc()
    ).all()

    all_participants = _get_all_meeting_participants()
    extra_meeting_ids = []
    for mid, pdata in all_participants.items():
        if pdata.get("mentor_id") == mentor.id:
            extra_meeting_ids.append(mid)

    extra_meetings = []
    if extra_meeting_ids:
        extra_meetings = MeetingRequest.query.filter(
            MeetingRequest.id.in_(extra_meeting_ids),
            ~MeetingRequest.id.in_([m.id for m in meetings])
        ).order_by(
            MeetingRequest.meeting_date.asc(),
            MeetingRequest.meeting_time.asc()
        ).all()

    all_meetings = list(meetings) + list(extra_meetings)
    
    # Prepare meeting data for the calendar
    calendar_meetings = []
    for meeting in all_meetings:
        pdata = _get_meeting_participants(meeting.id)
        if pdata and pdata.get("mentee_id"):
            mentee = User.query.get(pdata["mentee_id"])
        else:
            mentee = User.query.get(meeting.requester_id)
        
        # Determine meeting status based on date/time
        meeting_datetime = datetime.combine(meeting.meeting_date, meeting.meeting_time)
        now = datetime.now()
        
        if meeting.status == "cancelled":
            status = "cancelled"
        elif meeting_datetime < now:
            status = "completed"
        else:
            status = "upcoming"
        
        calendar_meetings.append({
            "id": meeting.id,
            "title": meeting.meeting_title,
            "date": meeting_datetime,
            "duration": meeting.meeting_duration,
            "mentee": mentee.name if mentee else "Unknown Mentee",
            "mentee_email": mentee.email if mentee else "",
            "type": "Video Call",
            "status": status,
            "description": meeting.meeting_description or "No description provided",
            "meet_link": meeting.meet_link
        })
    
    return render_template(
        "mentor/mentor_calendar.html",
        show_sidebar=True,
        meetings=calendar_meetings
    )


@app.route("/supervisor_calendar")
def supervisor_calendar():
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))
    
    # Fetch ALL meetings from the database
    meetings = MeetingRequest.query.order_by(
        MeetingRequest.meeting_date.asc(),
        MeetingRequest.meeting_time.asc()
    ).all()
    
    # Prepare meeting data for the calendar
    calendar_meetings = []
    for meeting in meetings:
        # Get mentee and mentor details
        mentee = User.query.get(meeting.requester_id)
        mentor = User.query.get(meeting.requested_to_id)
        
        # Determine meeting status based on date/time
        meeting_datetime = datetime.combine(meeting.meeting_date, meeting.meeting_time)
        now = datetime.now()
        
        if meeting.status == "cancelled":
            status = "cancelled"
        elif meeting_datetime < now:
            status = "completed"
        else:
            status = "upcoming"
        
        calendar_meetings.append({
            "id": meeting.id,
            "title": meeting.meeting_title,
            "date": meeting_datetime,
            "duration": meeting.meeting_duration,
            "mentee": mentee.name if mentee else "Unknown Mentee",
            "mentee_email": mentee.email if mentee else "",
            "mentor": mentor.name if mentor else "Unknown Mentor",
            "mentor_email": mentor.email if mentor else "",
            "type": "Video Call",
            "status": status,
            "description": meeting.meeting_description or "No description provided",
            "meet_link": meeting.meet_link,
            "created_at": meeting.created_at
        })
    
    # Fetch all mentors, mentees, and institutions for the schedule meeting form
    mentors = User.query.filter_by(user_type="1").all()
    mentees = User.query.filter_by(user_type="2").all()
    institutions = User.query.filter_by(user_type="3").all()

    # Fetch approved mentorships for the mentorship dropdown
    from sqlalchemy.orm import joinedload
    approved_mentorships = MentorshipRequest.query.options(
        joinedload(MentorshipRequest.mentor),
        joinedload(MentorshipRequest.mentee)
    ).filter(
        MentorshipRequest.final_status == "approved"
    ).order_by(MentorshipRequest.created_at.desc()).all()

    mentorships_list = []
    for mr in approved_mentorships:
        mentor_name = mr.mentor.name if mr.mentor else "Unknown"
        mentee_name = mr.mentee.name if mr.mentee else "Unknown"
        # Resolve institution user_id from mentor's or mentee's institution_id
        inst_user_id = ""
        for u in (mr.mentor, mr.mentee):
            if u and u.institution_id:
                inst = Institution.query.get(u.institution_id)
                if inst and inst.user_id:
                    inst_user_id = str(inst.user_id)
                    break
        mentor_inst = (mr.mentor.institution or (mr.mentor.institution_ref.name if mr.mentor and mr.mentor.institution_ref else "")) if mr.mentor else ""
        mentee_inst = (mr.mentee.institution or (mr.mentee.institution_ref.name if mr.mentee and mr.mentee.institution_ref else "")) if mr.mentee else ""
        mentor_inst_id = mr.mentor.institution_id if mr.mentor and mr.mentor.institution_id else ""
        mentee_inst_id = mr.mentee.institution_id if mr.mentee and mr.mentee.institution_id else ""
        mentorships_list.append({
            "id": mr.id,
            "mentor_id": mr.mentor_id,
            "mentee_id": mr.mentee_id,
            "mentor_name": mentor_name,
            "mentee_name": mentee_name,
            "mentor_institution": (mentor_inst or "").strip(),
            "mentee_institution": (mentee_inst or "").strip(),
            "mentor_inst_id": mentor_inst_id,
            "mentee_inst_id": mentee_inst_id,
            "purpose": mr.purpose or "",
            "duration": mr.duration_months or 0,
            "inst_user_id": inst_user_id
        })

    return render_template(
        "supervisor/supervisor_calendar.html",
        show_sidebar=True,
        meetings=calendar_meetings,
        mentors=mentors,
        mentees=mentees,
        institutions=institutions,
        mentorships=mentorships_list
    )




    #          task




# ------------------ TASK MANAGEMENT ROUTES ------------------

@app.route("/mentee_tasks")
def mentee_tasks():
    if "email" not in session or session.get("user_type") != "2":
        return redirect(url_for("signin"))
    
    # Get logged-in mentee
    mentee = User.query.filter_by(email=session["email"]).first()
    
    # ✅ FETCH MENTORS FOR DROPDOWN (only approved mentors)
    approved_mentors = MentorshipRequest.query\
        .filter_by(
            mentee_id=mentee.id,
             
            supervisor_status="approved",
            final_status="approved"
        )\
        .join(User, MentorshipRequest.mentor_id == User.id)\
        .all()
    
    mentors_list = [{"id": req.mentor.id, "name": req.mentor.name} for req in approved_mentors]
    
    # Fetch tasks
    assigned_tasks = MenteeTask.query\
        .filter_by(mentee_id=mentee.id)\
        .join(MasterTask, MenteeTask.task_id == MasterTask.id)\
        .order_by(MenteeTask.meeting_number)\
        .all()
    
    personal_tasks = PersonalTask.query\
        .filter_by(mentee_id=mentee.id)\
        .order_by(PersonalTask.created_date.desc())\
        .all()
    
    # Add serial numbers: continue numbering across assigned + personal tasks
    try:
        start_index = 1
        for i, t in enumerate(assigned_tasks, start_index):
            setattr(t, 'serial', i)
        # personal tasks continue numbering after assigned tasks
        start_index = len(assigned_tasks) + 1
        for i, t in enumerate(personal_tasks, start=start_index):
            setattr(t, 'serial', i)
    except Exception:
        # If we can't set attributes (unlikely), ignore and continue
        pass

    # Calculate statistics using computed task progress status
    total_tasks = len(assigned_tasks) + len(personal_tasks)
    today = datetime.utcnow().date()

    done_tasks = 0
    active_tasks = 0
    not_started_tasks = 0
    overdue_tasks = 0

    for t in assigned_tasks:
        status = compute_task_progress_status("master", t.id, t.mentee_id, t.mentor_id)
        setattr(t, 'status', status)  # Override DB status with computed 4-stage status
        if status == 'done':
            done_tasks += 1
        elif status in ('in-progress', 'committed'):
            active_tasks += 1
        elif status == 'not-started':
            not_started_tasks += 1
        if t.due_date and t.due_date.date() < today and status != 'done':
            overdue_tasks += 1

    for t in personal_tasks:
        status = compute_task_progress_status("personal", t.id, t.mentee_id, t.mentor_id)
        setattr(t, 'status', status)  # Override DB status with computed 4-stage status
        if status == 'done':
            done_tasks += 1
        elif status in ('in-progress', 'committed'):
            active_tasks += 1
        elif status == 'not-started':
            not_started_tasks += 1
        if t.due_date and t.due_date.date() < today and status != 'done':
            overdue_tasks += 1

    completed_tasks = done_tasks
    pending_tasks = active_tasks + not_started_tasks
    
    return render_template(
        "mentee/mentee_tasks.html",
        show_sidebar=True,
        assigned_tasks=assigned_tasks,
        personal_tasks=personal_tasks,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        overdue_tasks=overdue_tasks,
        today=today,
        mentors_list=mentors_list,  # ✅ PASS MENTORS TO TEMPLATE
        profile_complete=check_profile_complete(mentee.id, "2")
    )


# ------------------ MENTEE RATING VIEW ROUTES ------------------
@app.route('/mentee_get_task_rating/<task_type>/<int:task_id>')
def mentee_get_task_rating(task_type, task_id):
    try:
        if "email" not in session or session.get("user_type") != "2":
            return jsonify({'success': False, 'message': 'Unauthorized'})
        
        # Get current mentee
        mentee = User.query.filter_by(email=session["email"]).first()
        if not mentee:
            return jsonify({'success': False, 'message': 'Mentee not found'})
        
        # Verify the task belongs to this mentee
        if task_type == 'master':
            task = MenteeTask.query.filter_by(id=task_id, mentee_id=mentee.id).first()
        else:
            task = PersonalTask.query.filter_by(id=task_id, mentee_id=mentee.id).first()
            
        if not task:
            return jsonify({'success': False, 'message': 'Task not found or access denied'})
        
        # Get rating for this task
        rating = TaskRating.query.filter_by(
            task_id=task_id,
            task_type=task_type
        ).first()
        
        if rating:
            # Get mentor details
            mentor = User.query.get(rating.mentor_id)
            
            return jsonify({
                'success': True,
                'rating': {
                    'rating': rating.rating,
                    'feedback': rating.feedback,
                    'strengths': rating.strengths,
                    'improvements': rating.improvements,
                    'rated_at': rating.rated_at.isoformat(),
                    'mentor_name': mentor.name if mentor else 'Unknown Mentor'
                }
            })
        else:
            return jsonify({'success': True, 'rating': None})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})



@app.route("/update_task_status", methods=["POST"])
def update_task_status():
    if "email" not in session or session.get("user_type") != "2":
        return jsonify({"success": False, "message": "Unauthorized"})
    
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        task_type = data.get('task_type')  # 'master' or 'personal'
        status = data.get('status')
        progress = data.get('progress', 0)
        
        # Get current mentee
        mentee = User.query.filter_by(email=session["email"]).first()
        
        # Find the task
        if task_type == 'master':
            # Update master task
            task = MenteeTask.query.filter_by(id=task_id, mentee_id=mentee.id).first()
            if not task:
                return jsonify({"success": False, "message": "Mentorship task not found"})
            
            task.status = status
            if status == 'completed':
                task.completed_date = datetime.utcnow()
                task.progress = 100
            else:
                task.progress = progress
                
        elif task_type == 'personal':
            # Update personal task
            task = PersonalTask.query.filter_by(id=task_id, mentee_id=mentee.id).first()
            if not task:
                return jsonify({"success": False, "message": "Personal task not found"})
            
            task.status = status
            task.progress = progress
            if status == 'completed':
                task.completed_date = datetime.utcnow()
        
        else:
            return jsonify({"success": False, "message": "Invalid task type"})
        
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": f"Task marked as {status}",
            "progress": progress
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)})

@app.route("/create_personal_task", methods=["POST"])
def create_personal_task():
    if "email" not in session or session.get("user_type") != "2":
        return jsonify({"success": False, "message": "Unauthorized"})
    
    try:
        data = request.get_json()
        title = data.get('title')
        description = data.get('description')
        due_date_str = data.get('due_date')
        priority = data.get('priority', 'medium')
        mentor_id = data.get('mentor_id')
        
        # Get current mentee
        mentee = User.query.filter_by(email=session["email"]).first()
        
        # ✅ Validate mentor (if provided)
        selected_mentor = None
        if mentor_id and mentor_id != 'self':
            selected_mentor = User.query.get(int(mentor_id))
            if not selected_mentor or selected_mentor.user_type != "1":
                return jsonify({"success": False, "message": "Invalid mentor selected"})
        
        # Convert due date string to datetime
        due_date = None
        if due_date_str:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
        
        # Create personal task
        personal_task = PersonalTask(
            mentee_id=mentee.id,
            mentor_id=selected_mentor.id if selected_mentor else None,  # ✅ SET MENTOR OR NULL
            title=title,
            description=description,
            due_date=due_date,
            priority=priority,
            status="pending",
            progress=0
        )
        
        
        db.session.add(personal_task)
        db.session.commit()
        
        mentor_name = selected_mentor.name if selected_mentor else "Self"
        
        return jsonify({
            "success": True, 
            "message": f"Personal task created successfully under {mentor_name}",
            "task_id": personal_task.id,
            "task_type": "personal"
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)})

@app.route("/get_task_details/<int:task_id>")
def get_task_details(task_id):
    if "email" not in session:
        return jsonify({"success": False, "message": "Unauthorized"})
    
    try:
        task_type = request.args.get('type', 'master')  # Default to master
        
        if task_type == 'master':
            # Get master task with all related data
            task = MenteeTask.query\
                .join(MasterTask, MenteeTask.task_id == MasterTask.id)\
                .filter(MenteeTask.id == task_id)\
                .first()
            
            if not task:
                return jsonify({"success": False, "message": "Mentorship task not found"})
            
            # Verify access rights
            user = User.query.filter_by(email=session["email"]).first()
            user_type = session.get("user_type")
            
            if user_type == "2" and task.mentee_id != user.id:
                return jsonify({"success": False, "message": "Access denied"})
            
            task_data = {
                "id": task.id,
                "type": "master",
                "title": task.master_task.purpose_of_call,
                "description": task.master_task.mentee_focus,
                "due_date": task.due_date.strftime('%Y-%m-%d') if task.due_date else None,
                "status": compute_task_progress_status("master", task.id, task.mentee_id, task.mentor_id),
                "progress": task.progress or 0,
                "assigned_by": task.mentor.name if task.mentor else "System",
                "assigned_date": task.assigned_date.strftime('%Y-%m-%d') if task.assigned_date else None,
                "completed_date": task.completed_date.strftime('%Y-%m-%d') if task.completed_date else None,
                "month": task.month,
                "meeting_number": task.meeting_number,
                "mentor_focus": task.master_task.mentor_focus,
                "journey_phase": task.master_task.journey_phase,
                "meeting_plan": task.master_task.meeting_plan_overview
            }
            
        elif task_type == 'personal':
            # Get personal task
            task = PersonalTask.query.filter_by(id=task_id).first()
            
            if not task:
                return jsonify({"success": False, "message": "Personal task not found"})
            
            # Verify access rights
            user = User.query.filter_by(email=session["email"]).first()
            mentor = db.session.get(User, task.mentor_id) if task.mentor_id else None
            assigned_by = mentor.name if mentor else "Self"

            task_data = {
                "id": task.id,
                "type": "personal",
                "title": task.title,
                "description": task.description,
                "due_date": task.due_date.strftime('%Y-%m-%d') if task.due_date else None,
                "status": compute_task_progress_status("personal", task.id, task.mentee_id, task.mentor_id or None),
                "progress": task.progress or 0,
                "priority": task.priority,
                "assigned_by": assigned_by,
                "created_date": task.created_date.strftime('%Y-%m-%d') if task.created_date else None,
                "completed_date": task.completed_date.strftime('%Y-%m-%d') if task.completed_date else None
            }
        
        else:
            return jsonify({"success": False, "message": "Invalid task type"})
        
        return jsonify({"success": True, "task": task_data})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})



# ------------------ MENTOR TASK MANAGEMENT ROUTES ------------------
@app.route("/mentor_tasks")
def mentor_tasks():
    if "email" not in session or session.get("user_type") != "1":
        return redirect(url_for("signin"))
    
    # Get logged-in mentor
    mentor = User.query.filter_by(email=session["email"]).first()
    profile_complete = check_profile_complete(mentor.id, "1")
    
    if not mentor:
        flash("Mentor profile not found.", "error")
        return redirect(url_for("signin"))

    # Get mentor's mentees
    my_mentees_data = []
    accepted_requests = MentorshipRequest.query.filter_by(
        mentor_id=mentor.id,
        
        supervisor_status="approved",
        final_status="approved"
    ).all()

    for req in accepted_requests:
        if req.mentee:
            mentee_profile = MenteeProfile.query.filter_by(user_id=req.mentee.id).first()
            if mentee_profile:
                my_mentees_data.append({
                    "user": req.mentee,
                    "profile": mentee_profile
                })

    # Get personal tasks assigned by this mentor
    personal_tasks = PersonalTask.query.filter_by(mentor_id=mentor.id).all()
    
    # Get master tasks for mentees
    all_mentee_tasks = []
    for mentee_data in my_mentees_data:
        tasks = MenteeTask.query.filter_by(
            mentee_id=mentee_data["user"].id,
            mentor_id=mentor.id
        ).join(MasterTask, MenteeTask.task_id == MasterTask.id)\
         .order_by(MenteeTask.meeting_number)\
         .all()
        all_mentee_tasks.extend(tasks)

    # Assign serial numbers across mentor's personal tasks and mentee master tasks
    try:
        idx = 1
        for t in personal_tasks:
            setattr(t, 'serial', idx)
            idx += 1
        for t in all_mentee_tasks:
            setattr(t, 'serial', idx)
            idx += 1
    except Exception:
        pass

    # Calculate statistics using computed status
    all_tasks = list(personal_tasks) + list(all_mentee_tasks)
    total_tasks = len(all_tasks)
    done_count = 0
    active_count = 0
    not_started_count = 0
    overdue_count = 0
    today = datetime.utcnow().date()
    for t in all_tasks:
        ttype = "master" if hasattr(t, 'meeting_number') and hasattr(t, 'task_id') else "personal"
        st = compute_task_progress_status(ttype, t.id, t.mentee_id, t.mentor_id or None)
        setattr(t, 'status', st)  # Override DB status with computed 4-stage status
        if st == 'done':
            done_count += 1
        elif st in ('in-progress', 'committed'):
            active_count += 1
        else:
            not_started_count += 1
        if t.due_date and hasattr(t.due_date, 'date') and t.due_date.date() < today and st != 'done':
            overdue_count += 1

    completed_tasks = done_count
    pending_tasks = active_count + not_started_count
    overdue_tasks = overdue_count

    return render_template(
        "mentor/mentor_tasks.html",
        show_sidebar=True,
        my_mentees=my_mentees_data,
        personal_tasks=personal_tasks,
        mentee_tasks=all_mentee_tasks,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        overdue_tasks=overdue_tasks,
        today=today,
        profile_complete=profile_complete
    )

def build_mentee_work_book(rows, file_label):
    """Build the styled Excel workbook bytes for a set of mentee work rows.
    Shared by the manual export button and the external API endpoint.

    Returns a (BytesIO buffer, download_filename) tuple. Never throws."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Mentee Work"

    headers = [
        "Mentee Name", "Mentee Email", "Mentor Name", "Task Type",
        "Work / Task", "Details", "Month", "Meeting No.",
        "Assigned Date", "Due Date (Deadline)", "Completed Date",
        "Status", "Progress (%)", "Priority"
    ]

    header_fill = PatternFill(start_color="1D4ED8", end_color="1D4ED8", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    thin = Side(style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    def fmt(v):
        if not v:
            return "N/A"
        if hasattr(v, "strftime"):
            return v.strftime("%d-%b-%Y")
        return str(v)

    def status_label(s):
        if s == "completed":
            return "Completed"
        if s in ("in-progress", "in_progress"):
            return "In Progress"
        return "Pending / Not Completed"

    now_dt = datetime.utcnow()

    for r_idx, r in enumerate(rows, start=2):
        due = r["due_date"]
        is_completed = r["status"] == "completed"
        status = status_label(r["status"])
        if not is_completed and due and hasattr(due, "date") and due.date() < now_dt.date():
            status = "Overdue / Not Completed"

        values = [
            r["mentee"], r["mentee_email"], r["mentor"], r["task_type"],
            r["title"], r["description"], r["month"], r["meeting_number"],
            fmt(r["assigned_date"]), fmt(r["due_date"]), fmt(r["completed_date"]),
            status, r["progress"], r["priority"]
        ]
        for c_idx, val in enumerate(values, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if c_idx == 12 and status.startswith("Completed"):
                cell.font = Font(bold=True, color="065F46")
            elif c_idx == 12 and status.startswith("Overdue"):
                cell.font = Font(bold=True, color="DC2626")

    # Column widths
    widths = [18, 24, 18, 16, 40, 50, 12, 12, 14, 14, 14, 22, 12, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:N{max(len(rows) + 1, 2)}"

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"{file_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return buffer, filename

def collect_mentor_work_rows(user):
    """Collect all mentee work rows (master + personal tasks) for a mentor."""
    rows = []
    mentor_name = user.name or "N/A"

    master_tasks = MenteeTask.query.filter(
        MenteeTask.mentor_id == user.id
    ).order_by(MenteeTask.meeting_number).all()
    personal_tasks = PersonalTask.query.filter_by(mentor_id=user.id)\
        .order_by(PersonalTask.created_date.desc())\
        .all()

    for t in master_tasks:
        mentee_user = t.mentee
        rows.append({
            "mentee": mentee_user.name if mentee_user else "N/A",
            "mentee_email": mentee_user.email if mentee_user else "",
            "mentor": mentor_name,
            "task_type": "Mentorship Task",
            "title": t.master_task.mentee_focus if t.master_task else "",
            "description": t.master_task.purpose_of_call if t.master_task else "",
            "month": t.month or (t.master_task.month if t.master_task else ""),
            "meeting_number": t.meeting_number,
            "assigned_date": t.assigned_date,
            "due_date": t.due_date,
            "completed_date": t.completed_date,
            "status": compute_task_progress_status("master", t.id, t.mentee_id, t.mentor_id),
            "progress": t.progress or 0,
            "priority": "N/A"
        })
    for t in personal_tasks:
        mentee_user = t.mentee
        rows.append({
            "mentee": mentee_user.name if mentee_user else "N/A",
            "mentee_email": mentee_user.email if mentee_user else "",
            "mentor": mentor_name,
            "task_type": "Personal Task",
            "title": t.title,
            "description": t.description or "",
            "month": "",
            "meeting_number": "N/A",
            "assigned_date": t.created_date,
            "due_date": t.due_date,
            "completed_date": t.completed_date,
            "status": compute_task_progress_status("personal", t.id, t.mentee_id, t.mentor_id or None),
            "progress": t.progress or 0,
            "priority": t.priority or "medium"
        })
    return rows

def collect_mentee_own_rows(user):
    """Collect all work rows (master + personal tasks) for a mentee themselves."""
    rows = []

    master_tasks = MenteeTask.query.filter_by(mentee_id=user.id)\
        .join(MasterTask, MenteeTask.task_id == MasterTask.id)\
        .order_by(MenteeTask.meeting_number)\
        .all()
    personal_tasks = PersonalTask.query.filter_by(mentee_id=user.id)\
        .order_by(PersonalTask.created_date.desc())\
        .all()

    mentee_name = user.name or "N/A"
    for t in master_tasks:
        rows.append({
            "mentee": mentee_name,
            "mentee_email": user.email or "",
            "mentor": t.mentor.name if t.mentor else "N/A",
            "task_type": "Mentorship Task",
            "title": t.master_task.mentee_focus if t.master_task else "",
            "description": t.master_task.purpose_of_call if t.master_task else "",
            "month": t.month or (t.master_task.month if t.master_task else ""),
            "meeting_number": t.meeting_number,
            "assigned_date": t.assigned_date,
            "due_date": t.due_date,
            "completed_date": t.completed_date,
            "status": compute_task_progress_status("master", t.id, t.mentee_id, t.mentor_id),
            "progress": t.progress or 0,
            "priority": "N/A"
        })
    for t in personal_tasks:
        rows.append({
            "mentee": mentee_name,
            "mentee_email": user.email or "",
            "mentor": t.mentor.name if t.mentor else "N/A",
            "task_type": "Personal Task",
            "title": t.title,
            "description": t.description or "",
            "month": "",
            "meeting_number": "N/A",
            "assigned_date": t.created_date,
            "due_date": t.due_date,
            "completed_date": t.completed_date,
            "status": compute_task_progress_status("personal", t.id, t.mentee_id, t.mentor_id or None),
            "progress": t.progress or 0,
            "priority": t.priority or "medium"
        })
    return rows

def collect_all_system_work_rows():
    """Collect all mentee work rows across the system for supervisors/admins."""
    rows = []
    master_tasks = MenteeTask.query.order_by(MenteeTask.assigned_date.desc()).all()
    personal_tasks = PersonalTask.query.order_by(PersonalTask.created_date.desc()).all()

    for t in master_tasks:
        mentee_user = t.mentee
        mentor_user = t.mentor
        rows.append({
            "mentee": mentee_user.name if mentee_user else "N/A",
            "mentee_email": mentee_user.email if mentee_user else "",
            "mentor": mentor_user.name if mentor_user else "N/A",
            "task_type": "Mentorship Task",
            "title": t.master_task.mentee_focus if t.master_task else "",
            "description": t.master_task.purpose_of_call if t.master_task else "",
            "month": t.month or (t.master_task.month if t.master_task else ""),
            "meeting_number": t.meeting_number,
            "assigned_date": t.assigned_date,
            "due_date": t.due_date,
            "completed_date": t.completed_date,
            "status": compute_task_progress_status("master", t.id, t.mentee_id, t.mentor_id),
            "progress": t.progress or 0,
            "priority": "N/A"
        })
    for t in personal_tasks:
        mentee_user = t.mentee
        mentor_user = t.mentor
        rows.append({
            "mentee": mentee_user.name if mentee_user else "N/A",
            "mentee_email": mentee_user.email if mentee_user else "",
            "mentor": mentor_user.name if mentor_user else "N/A",
            "task_type": "Personal Task",
            "title": t.title,
            "description": t.description or "",
            "month": "",
            "meeting_number": "N/A",
            "assigned_date": t.created_date,
            "due_date": t.due_date,
            "completed_date": t.completed_date,
            "status": compute_task_progress_status("personal", t.id, t.mentee_id, t.mentor_id or None),
            "progress": t.progress or 0,
            "priority": t.priority or "medium"
        })
    return rows

@app.route("/export_mentee_work", methods=["GET"])
def export_mentee_work():
    """Export all tasks (master + personal) of mentees as an Excel file.
    Usable by mentees, mentors, and supervisors/admins."""
    if "email" not in session:
        return redirect(url_for("signin"))

    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("signin"))

    user_type = session.get("user_type")
    if user_type == "2":
        rows = collect_mentee_own_rows(user)
        file_label = "My_Work"
    elif user_type == "1":
        rows = collect_mentor_work_rows(user)
        file_label = "Mentee_Work_All"
    elif user_type in ["0", "3"]:
        rows = collect_all_system_work_rows()
        file_label = "All_Mentees_Work"
    else:
        return jsonify({"error": "Unauthorized user type."}), 403

    from flask import send_file
    buffer, filename = build_mentee_work_book(rows, file_label)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ===== IP-BASED COUNTRY DETECTION (no DB changes) =====
COUNTRY_DIAL_CODES = {
    "AF": "+93", "AL": "+355", "DZ": "+213", "AS": "+1684", "AD": "+376",
    "AO": "+244", "AI": "+1264", "AG": "+1268", "AR": "+54", "AM": "+374",
    "AW": "+297", "AU": "+61", "AT": "+43", "AZ": "+994", "BS": "+1242",
    "BH": "+973", "BD": "+880", "BB": "+1246", "BY": "+375", "BE": "+32",
    "BZ": "+501", "BJ": "+229", "BM": "+1441", "BT": "+975", "BO": "+591",
    "BA": "+387", "BW": "+267", "BR": "+55", "BN": "+673", "BG": "+359",
    "BF": "+226", "BI": "+257", "KH": "+855", "CM": "+237", "CA": "+1",
    "CV": "+238", "KY": "+1345", "CF": "+236", "TD": "+235", "CL": "+56",
    "CN": "+86", "CO": "+57", "KM": "+269", "CG": "+242", "CD": "+243",
    "CR": "+506", "CI": "+225", "HR": "+385", "CU": "+53", "CW": "+599",
    "CY": "+357", "CZ": "+420", "DK": "+45", "DJ": "+253", "DM": "+1767",
    "DO": "+1809", "EC": "+593", "EG": "+20", "SV": "+503", "GQ": "+240",
    "ER": "+291", "EE": "+372", "ET": "+251", "FK": "+500", "FO": "+298",
    "FJ": "+679", "FI": "+358", "FR": "+33", "GF": "+594", "PF": "+689",
    "GA": "+241", "GM": "+220", "GE": "+995", "DE": "+49", "GH": "+233",
    "GI": "+350", "GR": "+30", "GL": "+299", "GD": "+1473", "GP": "+590",
    "GU": "+1671", "GT": "+502", "GN": "+224", "GW": "+245", "GY": "+592",
    "HT": "+509", "HN": "+504", "HK": "+852", "HU": "+36", "IS": "+354",
    "IN": "+91", "ID": "+62", "IR": "+98", "IQ": "+964", "IE": "+353",
    "IL": "+972", "IT": "+39", "JM": "+1876", "JP": "+81", "JO": "+962",
    "KZ": "+7", "KE": "+254", "KI": "+686", "KW": "+965", "KG": "+996",
    "LA": "+856", "LV": "+371", "LB": "+961", "LS": "+266", "LR": "+231",
    "LY": "+218", "LI": "+423", "LT": "+370", "LU": "+352", "MO": "+853",
    "MK": "+389", "MG": "+261", "MW": "+265", "MY": "+60", "MV": "+960",
    "ML": "+223", "MT": "+356", "MH": "+692", "MQ": "+596", "MR": "+222",
    "MU": "+230", "YT": "+262", "MX": "+52", "FM": "+691", "MD": "+373",
    "MC": "+377", "MN": "+976", "ME": "+382", "MS": "+1664", "MA": "+212",
    "MZ": "+258", "MM": "+95", "NA": "+264", "NR": "+674", "NP": "+977",
    "NL": "+31", "NC": "+687", "NZ": "+64", "NI": "+505", "NE": "+227",
    "NG": "+234", "NU": "+683", "KP": "+850", "MP": "+1670", "NO": "+47",
    "OM": "+968", "PK": "+92", "PW": "+680", "PS": "+970", "PA": "+507",
    "PG": "+675", "PY": "+595", "PE": "+51", "PH": "+63", "PL": "+48",
    "PT": "+351", "PR": "+1787", "QA": "+974", "RE": "+262", "RO": "+40",
    "RU": "+7", "RW": "+250", "BL": "+590", "SH": "+290", "KN": "+1869",
    "LC": "+1758", "MF": "+590", "PM": "+508", "VC": "+1784", "WS": "+685",
    "SM": "+378", "ST": "+239", "SA": "+966", "SN": "+221", "RS": "+381",
    "SC": "+248", "SL": "+232", "SG": "+65", "SX": "+1721", "SK": "+421",
    "SI": "+386", "SB": "+677", "SO": "+252", "ZA": "+27", "KR": "+82",
    "SS": "+211", "ES": "+34", "LK": "+94", "SD": "+249", "SR": "+597",
    "SZ": "+268", "SE": "+46", "CH": "+41", "SY": "+963", "TW": "+886",
    "TJ": "+992", "TZ": "+255", "TH": "+66", "TL": "+670", "TG": "+228",
    "TK": "+690", "TO": "+676", "TT": "+1868", "TN": "+216", "TR": "+90",
    "TM": "+993", "TC": "+1649", "TV": "+688", "VI": "+1340", "UG": "+256",
    "UA": "+380", "AE": "+971", "GB": "+44", "US": "+1", "UY": "+598",
    "UZ": "+998", "VU": "+678", "VA": "+379", "VE": "+58", "VN": "+84",
    "WF": "+681", "YE": "+967", "ZM": "+260", "ZW": "+263"
}

@app.route("/api/detect_country")
def api_detect_country():
    """Detect the user's country dial code from their IP address.
    Tries multiple free HTTPS geolocation APIs with fallback.
    No database changes. Returns JSON with dial_code and country name.
    """
    import urllib.request
    import urllib.error

    # ---- Step 1: Extract client IP from common proxy headers ----
    ip = None
    for header in ("CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP", "X-Client-IP"):
        val = request.headers.get(header)
        if val:
            ip = val.split(",")[0].strip()
            break
    if not ip:
        ip = request.remote_addr

    # Normalise localhost / IPv6 loopback
    if ip in ("127.0.0.1", "::1", "localhost", ""):
        ip = None  # let the API detect from the server's real IP

    # ---- Step 2: Try geolocation APIs (HTTPS only, in order) ----
    apis = []
    if ip:
        apis = [
            f"https://ipwho.is/{ip}",
            f"https://ipapi.co/{ip}/json/",
            f"https://api.ipify.org?format=json",  # IP-only, will chain below
        ]
    else:
        apis = [
            "https://ipwho.is/",
            "https://ipapi.co/json/",
        ]

    for url in apis:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())

            # ipify only returns IP — fetch geolocation in a second call
            if "ip" in data and "country_code" not in data:
                ip = data["ip"]
                geo_url = f"https://ipwho.is/{ip}"
                geo_req = urllib.request.Request(geo_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                with urllib.request.urlopen(geo_req, timeout=5) as geo_resp:
                    data = json.loads(geo_resp.read().decode())

            cc = data.get("country_code") or data.get("countryCode") or ""
            if cc:
                dial = COUNTRY_DIAL_CODES.get(cc, "")
                if dial:
                    return jsonify({
                        "success": True,
                        "country_code": cc,
                        "country_name": data.get("country", ""),
                        "dial_code": dial
                    })
        except Exception:
            continue  # try next API

    return jsonify({"success": False, "message": "Could not detect country from IP"})

@app.route("/api/export_mentee_work", methods=["POST"])
def api_export_mentee_work():
    """External API: export a mentor's mentee work as an Excel file.

    Authentication: header  X-API-Key: <key>  (see EXPORT_API_KEY in .env).
    Request body (JSON):
        {
          "mentor_id": 123
        }
    The mentor is looked up by id (or "mentor_email" if provided instead).
    Returns the same styled .xlsx the manual button produces.
    """
    import hmac

    # 1) Authenticate via API key header
    supplied_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if not supplied_key or not hmac.compare_digest(str(supplied_key), str(EXPORT_API_KEY)):
        return jsonify({"error": "Invalid or missing API key."}), 401

    # 2) Determine the mentor
    data = request.get_json(silent=True) or {}
    mentor_id = data.get("mentor_id")
    mentor_email = data.get("mentor_email")

    if mentor_id is None and not mentor_email:
        return jsonify({"error": "Provide 'mentor_id' (or 'mentor_email') in the JSON body."}), 400

    if mentor_email:
        mentor_user = User.query.filter_by(email=mentor_email, user_type="1").first()
    else:
        try:
            mentor_user = User.query.filter_by(id=int(mentor_id), user_type="1").first()
        except (TypeError, ValueError):
            return jsonify({"error": "'mentor_id' must be an integer."}), 400

    if not mentor_user:
        return jsonify({"error": "Mentor not found."}), 404

    # 3) Build the same report as the manual export button
    rows = collect_mentor_work_rows(mentor_user)
    from flask import send_file
    buffer, filename = build_mentee_work_book(rows, "Mentee_Work_All")

    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/mentor_create_task", methods=["POST"])
def mentor_create_task():
    if "email" not in session or session.get("user_type") != "1":
        return jsonify({"success": False, "message": "Unauthorized"})
    
    try:
        data = request.get_json()
        mentee_id = data.get('mentee_id')
        title = data.get('title')
        description = data.get('description')
        due_date_str = data.get('due_date')
        priority = data.get('priority', 'medium')
        category = data.get('category', 'Other')
        
        # Get current mentor
        mentor = User.query.filter_by(email=session["email"]).first()
        
        # Validate mentee belongs to this mentor
        mentorship = MentorshipRequest.query.filter_by(
            mentor_id=mentor.id,
            mentee_id=mentee_id,
            
            supervisor_status="approved",
            final_status="approved"
        ).first()
        
        if not mentorship:
            return jsonify({"success": False, "message": "Mentee not found or not assigned to you"})
        
        # Convert due date string to datetime
        due_date = None
        if due_date_str:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
        
        # Create personal task assigned by mentor
        personal_task = PersonalTask(
            mentee_id=mentee_id,
            mentor_id=mentor.id,
            title=title,
            description=description,
            due_date=due_date,
            priority=priority,
            status="pending",
            progress=0
        )
        
        db.session.add(personal_task)
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": "Task assigned successfully to mentee",
            "task_id": personal_task.id
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)})

@app.route("/get_mentor_task_details/<int:task_id>")
def get_mentor_task_details(task_id):
    if "email" not in session or session.get("user_type") != "1":
        return jsonify({"success": False, "message": "Unauthorized"})
    
    try:
        task_type = request.args.get('type', 'personal')
        
        if task_type == 'master':
            # Get master task with all related data
            task = MenteeTask.query\
                .join(MasterTask, MenteeTask.task_id == MasterTask.id)\
                .join(User, MenteeTask.mentee_id == User.id)\
                .filter(MenteeTask.id == task_id)\
                .first()
            
            if not task:
                return jsonify({"success": False, "message": "Mentorship task not found"})
            
            # Verify the mentor has access to this task
            mentor = User.query.filter_by(email=session["email"]).first()
            if task.mentor_id != mentor.id:
                return jsonify({"success": False, "message": "Access denied"})
            
            task_data = {
                "id": task.id,
                "type": "master",
                "title": task.master_task.purpose_of_call,
                "purpose_of_call": task.master_task.purpose_of_call,
                "description": task.master_task.mentee_focus,
                "due_date": task.due_date.strftime('%Y-%m-%d') if task.due_date else None,
                "status": compute_task_progress_status("master", task.id, task.mentee_id, task.mentor_id),
                "progress": task.progress or 0,
                "mentee_name": task.mentee.name if task.mentee else "Unknown",
                "mentee_email": task.mentee.email if task.mentee else "",
                "assigned_by": "System",
                "assigned_date": task.assigned_date.strftime('%Y-%m-%d') if task.assigned_date else None,
                "completed_date": task.completed_date.strftime('%Y-%m-%d') if task.completed_date else None,
                "month": task.month,
                "meeting_number": task.meeting_number,
                "mentor_focus": task.master_task.mentor_focus,
                "journey_phase": task.master_task.journey_phase,
                "meeting_plan": task.master_task.meeting_plan_overview
            }
            
        elif task_type == 'personal':
            # Get personal task
            task = PersonalTask.query\
                .join(User, PersonalTask.mentee_id == User.id)\
                .filter(PersonalTask.id == task_id)\
                .first()
            
            if not task:
                return jsonify({"success": False, "message": "Personal task not found"})
            
            # Verify the mentor has access to this task
            mentor = User.query.filter_by(email=session["email"]).first()
            if task.mentor_id != mentor.id:
                return jsonify({"success": False, "message": "Access denied"})
            
            task_data = {
                "id": task.id,
                "type": "personal",
                "title": task.title,
                "description": task.description,
                "due_date": task.due_date.strftime('%Y-%m-%d') if task.due_date else None,
                "status": compute_task_progress_status("personal", task.id, task.mentee_id, task.mentor_id or None),
                "progress": task.progress or 0,
                "priority": task.priority,
                "mentee_name": task.mentee.name if task.mentee else "Unknown",
                "mentee_email": task.mentee.email if task.mentee else "",
                "assigned_by": "You",
                "created_date": task.created_date.strftime('%Y-%m-%d') if task.created_date else None,
                "completed_date": task.completed_date.strftime('%Y-%m-%d') if task.completed_date else None
            }
        
        else:
            return jsonify({"success": False, "message": "Invalid task type"})
        
        return jsonify({"success": True, "task": task_data})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})



# Task Rating Routes - FIXED VERSION
@app.route('/rate_task/<task_type>/<int:task_id>', methods=['POST'])
def rate_task(task_type, task_id):
    if "email" not in session or session.get("user_type") != "1":
        return jsonify({'success': False, 'message': 'Only mentors can rate tasks'})
    
    try:
        # Get current mentor from session
        mentor = User.query.filter_by(email=session["email"]).first()
        if not mentor:
            return jsonify({'success': False, 'message': 'Mentor not found'})
        
        data = request.get_json()
        
        # Check if task exists and belongs to mentor's mentee
        if task_type == 'master':
            task = MenteeTask.query.filter_by(id=task_id, mentor_id=mentor.id).first()
        else:
            task = PersonalTask.query.filter_by(id=task_id, mentor_id=mentor.id).first()
            
        if not task:
            return jsonify({'success': False, 'message': 'Task not found or access denied'})
        
        # Check if already rated
        existing_rating = TaskRating.query.filter_by(
            task_id=task_id, 
            task_type=task_type,
            mentor_id=mentor.id
        ).first()
        
        if existing_rating:
            # Update existing rating
            existing_rating.rating = data['rating']
            existing_rating.feedback = data.get('feedback', '')
            existing_rating.strengths = data.get('strengths', '')
            existing_rating.improvements = data.get('improvements', '')
            existing_rating.rated_at = datetime.utcnow()
        else:
            # Create new rating
            new_rating = TaskRating(
                task_id=task_id,
                task_type=task_type,
                mentee_id=task.mentee_id,
                mentor_id=mentor.id,
                rating=data['rating'],
                feedback=data.get('feedback', ''),
                strengths=data.get('strengths', ''),
                improvements=data.get('improvements', '')
            )
            db.session.add(new_rating)
        
        db.session.commit()
        mentor_id = mentor.id
        new_status = compute_task_progress_status(task_type, task_id, task.mentee_id, mentor_id)
        
        return jsonify({
            'success': True, 
            'message': 'Task rated successfully',
            'status': new_status
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/get_task_rating/<task_type>/<int:task_id>')
def get_task_rating(task_type, task_id):
    try:
        if "email" not in session or session.get("user_type") != "1":
            return jsonify({'success': False, 'message': 'Unauthorized'})
        
        mentor = User.query.filter_by(email=session["email"]).first()
        if not mentor:
            return jsonify({'success': False, 'message': 'Mentor not found'})
        
        rating = TaskRating.query.filter_by(
            task_id=task_id,
            task_type=task_type,
            mentor_id=mentor.id
        ).first()
        
        if rating:
            return jsonify({
                'success': True,
                'rating': {
                    'rating': rating.rating,
                    'feedback': rating.feedback,
                    'strengths': rating.strengths,
                    'improvements': rating.improvements,
                    'rated_at': rating.rated_at.isoformat()
                }
            })
        else:
            return jsonify({'success': True, 'rating': None})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ===== MEETING PARTICIPANT SYNC (JSON file, no DB changes) =====
MEETING_PARTICIPANTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'meeting_participants_data')

def _get_meeting_participants_path(meeting_id):
    os.makedirs(MEETING_PARTICIPANTS_DIR, exist_ok=True)
    return os.path.join(MEETING_PARTICIPANTS_DIR, f'meeting_{meeting_id}.json')

_MEETING_PARTICIPANTS_CACHE = None
_MEETING_PARTICIPANTS_CACHE_TIME = 0

def _invalidate_meeting_participants_cache():
    global _MEETING_PARTICIPANTS_CACHE, _MEETING_PARTICIPANTS_CACHE_TIME
    _MEETING_PARTICIPANTS_CACHE = None
    _MEETING_PARTICIPANTS_CACHE_TIME = 0

def _save_meeting_participants(meeting_id, participants):
    path = _get_meeting_participants_path(meeting_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(participants, f, ensure_ascii=False, indent=2)
    _invalidate_meeting_participants_cache()

def _get_meeting_participants(meeting_id):
    path = _get_meeting_participants_path(meeting_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _get_all_meeting_participants():
    global _MEETING_PARTICIPANTS_CACHE, _MEETING_PARTICIPANTS_CACHE_TIME
    now = time.time()
    if _MEETING_PARTICIPANTS_CACHE is not None and (now - _MEETING_PARTICIPANTS_CACHE_TIME < 5):
        return _MEETING_PARTICIPANTS_CACHE
    os.makedirs(MEETING_PARTICIPANTS_DIR, exist_ok=True)
    result = {}
    for fname in os.listdir(MEETING_PARTICIPANTS_DIR):
        if fname.startswith('meeting_') and fname.endswith('.json'):
            try:
                meeting_id = int(fname.replace('meeting_', '').replace('.json', ''))
                with open(os.path.join(MEETING_PARTICIPANTS_DIR, fname), 'r', encoding='utf-8') as f:
                    result[meeting_id] = json.load(f)
            except Exception:
                pass
    _MEETING_PARTICIPANTS_CACHE = result
    _MEETING_PARTICIPANTS_CACHE_TIME = now
    return result


# ===== 4-STAGE TASK PROGRESS (computed, no DB changes) =====
# Stages: not-started, committed, in-progress, done

def _task_has_linked_meeting(task_type, task_id, mentee_id, mentor_id, all_pdata=None):
    """Check if any meeting in meeting_participants_data is linked to this task."""
    if all_pdata is None:
        all_pdata = _get_all_meeting_participants()
    str_task_id = str(task_id)
    for meeting_id, pdata in all_pdata.items():
        if pdata.get("task_type") == task_type and str(pdata.get("task_id")) == str_task_id:
            return True
        if pdata.get("mentee_id") == mentee_id and pdata.get("mentor_id") == mentor_id:
            if pdata.get("task_type") == task_type and str(pdata.get("task_id")) == str_task_id:
                return True
    return False


def _meeting_is_completed(task_type, task_id, meetings_map=None, all_pdata=None):
    """Check if the linked meeting has passed its date (i.e. meeting is completed)."""
    if all_pdata is None:
        all_pdata = _get_all_meeting_participants()
    str_task_id = str(task_id)
    from datetime import date as date_cls
    today = date_cls.today()
    for meeting_id, pdata in all_pdata.items():
        if pdata.get("task_type") == task_type and str(pdata.get("task_id")) == str_task_id:
            if meetings_map is not None:
                meeting = meetings_map.get(meeting_id)
            else:
                meeting = db.session.get(MeetingRequest, meeting_id)
            if meeting and meeting.meeting_date and meeting.meeting_date <= today:
                return True
    return False


def _has_mentee_feedback(task_type, task_id):
    """Check if mentee has submitted feedback for this task."""
    fb = MenteeFeedback.query.filter_by(task_type=task_type, task_id=task_id).first()
    if not fb:
        return False
    return bool((fb.text or '').strip() or fb.rating)


def _has_mentor_rating(task_type, task_id):
    """Check if mentor has submitted rating for this task."""
    rating = TaskRating.query.filter_by(task_id=task_id, task_type=task_type).first()
    return rating is not None


def _has_mentor_reflection(task_type, task_id):
    """Check if mentor has submitted a reflection for this task."""
    refl = MentorReflection.query.filter_by(task_type=task_type, task_id=task_id).first()
    if not refl:
        return False
    return bool((refl.text or '').strip())


def _has_institution_reflection(task_type, task_id):
    """Check if institution has submitted a reflection for this task."""
    refl = InstitutionReflection.query.filter_by(task_type=task_type, task_id=task_id).first()
    if not refl:
        return False
    return bool((refl.text or '').strip())


def compute_task_progress_status(task_type, task_id, mentee_id, mentor_id, ratings_set=None, meetings_map=None, all_pdata=None):
    """Compute the 4-stage task progress status dynamically.

    Stages:
      not-started : No feedback from anyone AND no meeting scheduled for this task.
      committed   : Task is attached to a scheduled meeting, but no feedback/ratings yet.
      in-progress : At least one persona has submitted feedback, but not all required personas have.
      done        : All involved personas have submitted their feedback/ratings.

    Returns one of: 'not-started', 'committed', 'in-progress', 'done'
    """
    # Gather feedback from all personas
    has_mentee_fb = _has_mentee_feedback(task_type, task_id)
    if ratings_set is not None:
        has_mentor_rt = (task_type, task_id) in ratings_set
    else:
        has_mentor_rt = _has_mentor_rating(task_type, task_id)
    has_mentor_refl = _has_mentor_reflection(task_type, task_id)
    has_inst_refl = _has_institution_reflection(task_type, task_id)

    mentor_submitted = has_mentor_rt or has_mentor_refl
    any_feedback = has_mentee_fb or mentor_submitted or has_inst_refl

    # Determine which personas are required for 'done'
    # Mentor required only if task has an assigned mentor
    mentor_done = mentor_submitted if mentor_id else True

    # Institution reflection required only for master tasks if mentee belongs to an institution
    inst_required = False
    if task_type == 'master' and mentee_id:
        mentee = db.session.get(User, mentee_id)
        if mentee and (mentee.institution_id or mentee.institution):
            inst_required = True
    inst_done = has_inst_refl if inst_required else True

    all_feedback = has_mentee_fb and mentor_done and inst_done

    has_meeting = _task_has_linked_meeting(task_type, task_id, mentee_id, mentor_id, all_pdata=all_pdata)

    if not has_meeting and not any_feedback:
        return 'not-started'

    if all_feedback:
        return 'done'

    if any_feedback:
        return 'in-progress'

    if has_meeting:
        return 'committed'

    return 'not-started'



def get_task_progress_label(status):
    """Return human-readable label for a task progress status."""
    labels = {
        'not-started': 'Not Started',
        'committed': 'Committed',
        'in-progress': 'In Progress',
        'done': 'Done',
    }
    return labels.get(status, 'Not Started')


def get_task_progress_css(status):
    """Return CSS classes for a task progress status badge."""
    css = {
        'not-started': 'bg-slate-100 text-slate-500',
        'committed': 'bg-amber-50 text-amber-600',
        'in-progress': 'bg-blue-50 text-blue-600',
        'done': 'bg-emerald-50 text-emerald-600',
    }
    return css.get(status, 'bg-slate-100 text-slate-500')


def _send_meeting_link_email(meeting, meet_link, calendar_add_link, teams_calendar_link,
                              platform, title, start_datetime, timezone,
                              mentor_id, mentee_id, supervisor, requested_to):
    """Send meeting link details to all participants via email + in-app notification.
    Never raises; logs errors instead.
    """
    try:
        # Determine all recipient emails
        recipients = {}
        # Supervisor (creator)
        recipients[supervisor.id] = supervisor
        # Requested-to user (mentor, mentee, or institution)
        if requested_to:
            recipients[requested_to.id] = requested_to
        # Resolve mentor and mentee from IDs for notification
        mentor_user = None
        mentee_user = None
        if mentor_id:
            mentor_user = User.query.get(int(mentor_id))
            if mentor_user:
                recipients[mentor_user.id] = mentor_user
        if mentee_id:
            mentee_user = User.query.get(int(mentee_id))
            if mentee_user:
                recipients[mentee_user.id] = mentee_user

        start_str = start_datetime.strftime("%B %d, %Y at %I:%M %p")

        # Build link section for email
        link_section = ""
        if meet_link:
            link_section = f'<p><a href="{meet_link}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;">Join Meeting</a></p>'
        elif platform == "teams" and teams_calendar_link:
            link_section = f'<p><a href="{teams_calendar_link}" style="display:inline-block;padding:12px 24px;background:#6264a7;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;">Create Meeting in Microsoft Teams</a></p>'
        elif calendar_add_link:
            link_section = f'<p><a href="{calendar_add_link}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;">Add to Google Calendar</a></p>'

        # Build fallback message
        fallback_msg = ""
        if not meet_link and platform == "google":
            fallback_msg = '<p style="color:#b45309;background:#fffbeb;padding:12px;border-radius:6px;font-size:13px;">No automatic meeting link was generated. Please open the Google Calendar event and click "Join with Google Meet" to get the link, then share it with participants.</p>'
        elif not meet_link and platform == "teams":
            fallback_msg = '<p style="color:#b45309;background:#fffbeb;padding:12px;border-radius:6px;font-size:13px;">No automatic Teams meeting link was generated. Please set up Microsoft Graph API credentials (MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, MS_USER_EMAIL) to enable automatic Teams meeting link generation, or use a custom link instead.</p>'
        elif not meet_link and platform == "custom":
            fallback_msg = '<p style="color:#b45309;background:#fffbeb;padding:12px;border-radius:6px;font-size:13px;">No meeting link was provided for this custom meeting.</p>'

        platform_display = "Other (Custom Link)" if platform == "custom" else ("Microsoft Teams" if platform == "teams" else "Google Meet")

        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
            <h2 style="color:#1e40af;">Meeting Scheduled</h2>
            <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin:16px 0;">
                <p><strong>Meeting:</strong> {title}</p>
                <p><strong>Date/Time:</strong> {start_str} ({timezone})</p>
                <p><strong>Platform:</strong> {platform_display}</p>
                <p><strong>Created by:</strong> {supervisor.name} ({supervisor.email})</p>
            </div>
            {link_section}
            {fallback_msg}
            {f'<p style="margin-top:12px;"><a href="{calendar_add_link}" style="color:#2563eb;">Add to Google Calendar</a></p>' if calendar_add_link and meet_link else ''}
            <p style="color:#64748b;font-size:12px;margin-top:24px;">This email was sent by Mentor Connect.</p>
        </div>
        """

        # Send email to all recipients
        for uid, user in recipients.items():
            if user and user.email:
                try:
                    send_email_reminder(
                        user.email,
                        f"Meeting Scheduled: {title}",
                        html_body
                    )
                except Exception as e:
                    app.logger.error(f"Failed to send meeting link email to {user.email}: {e}")

            # Create in-app notification
            link_url = meet_link or calendar_add_link or teams_calendar_link or ""
            notification_msg = f'New meeting "{title}" scheduled for {start_str}'
            if meet_link:
                notification_msg += f' — <a href="{meet_link}">Join Meeting</a>'
            create_notification(uid, notification_msg, link=link_url if link_url else None)

    except Exception as e:
        app.logger.error(f"Failed to send meeting link emails: {e}")


@app.route('/save_mentee_feedback', methods=['POST'])
def save_mentee_feedback():
    if "email" not in session or session.get("user_type") != "2":
        return jsonify({'success': False, 'message': 'Unauthorized'})
    try:
        mentee = User.query.filter_by(email=session["email"]).first()
        if not mentee:
            return jsonify({'success': False, 'message': 'Mentee not found'})
        data = request.get_json(force=True)
        if not data:
            return jsonify({'success': False, 'message': 'Invalid JSON body'})
        task_type = data.get('task_type')
        task_id = data.get('task_id')
        if not task_type or not task_id:
            return jsonify({'success': False, 'message': 'Missing task_type or task_id'})
        feedback = MenteeFeedback.query.filter_by(task_type=task_type, task_id=task_id).first()
        if not feedback:
            feedback = MenteeFeedback(
                mentee_id=mentee.id,
                task_type=task_type,
                task_id=task_id
            )
            db.session.add(feedback)
        feedback.mentee_id = mentee.id
        feedback.rating = int(data.get('rating')) if data.get('rating') else None
        feedback.mentor_rating = int(data.get('mentor_rating')) if data.get('mentor_rating') else None
        feedback.text = data.get('text', '')
        feedback.challenges = data.get('challenges', '')
        feedback.next_steps = data.get('nextSteps', '')
        feedback.extra = data.get('extra', '')
        feedback.created_at = datetime.utcnow()

        db.session.commit()
        mentor_id = None
        if task_type == 'master':
            t = db.session.get(MenteeTask, task_id)
            mentor_id = t.mentor_id if t else None
        else:
            t = db.session.get(PersonalTask, task_id)
            mentor_id = t.mentor_id if t else None
        new_status = compute_task_progress_status(task_type, task_id, mentee.id, mentor_id)
        return jsonify({'success': True, 'message': 'Feedback saved', 'feedback': feedback.to_dict(), 'status': new_status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/get_mentee_feedback/<task_type>/<int:task_id>')
def get_mentee_feedback(task_type, task_id):
    if "email" not in session or session.get("user_type") not in ("1", "0", "3"):
        return jsonify({'success': False, 'message': 'Unauthorized'})
    try:
        feedback = MenteeFeedback.query.filter_by(task_type=task_type, task_id=task_id).first()
        if not feedback:
            return jsonify({'success': True, 'feedback': None})
        return jsonify({'success': True, 'feedback': feedback.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ===== MENTOR TASK REFLECTION SYNC =====
@app.route('/save_mentor_reflection', methods=['POST'])
def save_mentor_reflection():
    if "email" not in session or session.get("user_type") != "1":
        return jsonify({'success': False, 'message': 'Unauthorized'})
    try:
        mentor = User.query.filter_by(email=session["email"]).first()
        if not mentor:
            return jsonify({'success': False, 'message': 'Mentor not found'})
        data = request.get_json(force=True)
        if not data:
            return jsonify({'success': False, 'message': 'Invalid JSON body'})
        task_type = data.get('task_type')
        task_id = data.get('task_id')
        if not task_type or not task_id:
            return jsonify({'success': False, 'message': 'Missing task_type or task_id'})

        reflection = MentorReflection.query.filter_by(task_type=task_type, task_id=task_id).first()
        if not reflection:
            reflection = MentorReflection(
                mentor_id=mentor.id,
                task_type=task_type,
                task_id=task_id
            )
            db.session.add(reflection)
        reflection.mentor_id = mentor.id
        reflection.text = (data.get('text') or '').strip()
        reflection.extra = (data.get('extra') or '').strip()
        reflection.created_at = datetime.utcnow()

        db.session.commit()
        mentee_id = None
        if task_type == 'master':
            t = db.session.get(MenteeTask, task_id)
            mentee_id = t.mentee_id if t else None
        else:
            t = db.session.get(PersonalTask, task_id)
            mentee_id = t.mentee_id if t else None
        new_status = compute_task_progress_status(task_type, task_id, mentee_id, mentor.id)
        return jsonify({'success': True, 'message': 'Reflection saved', 'reflection': reflection.to_dict(), 'status': new_status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/get_mentor_reflection/<task_type>/<int:task_id>')
def get_mentor_reflection(task_type, task_id):
    try:
        reflection = MentorReflection.query.filter_by(task_type=task_type, task_id=task_id).first()
        if not reflection:
            return jsonify({'success': True, 'reflection': None})
        return jsonify({'success': True, 'reflection': reflection.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ===== INSTITUTION TASK REFLECTION SYNC =====
@app.route('/save_institution_reflection', methods=['POST'])
def save_institution_reflection():
    if "email" not in session or session.get("user_type") != "3":
        return jsonify({'success': False, 'message': 'Unauthorized'})
    try:
        user = User.query.filter_by(email=session["email"]).first()
        if not user:
            return jsonify({'success': False, 'message': 'User not found'})
        inst_id = user.institution_id or user.id
        data = request.get_json(force=True)
        task_type = data.get('task_type')
        task_id = data.get('task_id')
        if not task_type or not task_id:
            return jsonify({'success': False, 'message': 'Missing task_type or task_id'})

        refl = InstitutionReflection.query.filter_by(institution_id=inst_id, task_type=task_type, task_id=task_id).first()
        if not refl:
            refl = InstitutionReflection(
                institution_id=inst_id,
                task_type=task_type,
                task_id=task_id
            )
            db.session.add(refl)
        refl.text = (data.get('text') or '').strip()
        refl.notes = (data.get('notes') or '').strip()
        refl.created_at = datetime.utcnow()
        db.session.commit()

        mentee_id = None
        mentor_id = None
        if task_type == 'master':
            t = db.session.get(MenteeTask, task_id)
            if t:
                mentee_id = t.mentee_id
                mentor_id = t.mentor_id
        else:
            t = db.session.get(PersonalTask, task_id)
            if t:
                mentee_id = t.mentee_id
                mentor_id = t.mentor_id
        new_status = compute_task_progress_status(task_type, task_id, mentee_id, mentor_id)
        return jsonify({'success': True, 'message': 'Reflection saved', 'reflection': refl.to_dict(), 'status': new_status})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/get_institution_reflection/<task_type>/<int:task_id>')
def get_institution_reflection(task_type, task_id):
    if "email" not in session or session.get("user_type") not in ("3", "0"):
        return jsonify({'success': False, 'message': 'Unauthorized'})
    try:
        user = User.query.filter_by(email=session["email"]).first()
        if not user:
            return jsonify({'success': False, 'message': 'User not found'})
        inst_id = user.institution_id or user.id
        refl = InstitutionReflection.query.filter_by(institution_id=inst_id, task_type=task_type, task_id=task_id).first()
        if not refl:
            return jsonify({'success': True, 'reflection': None})
        return jsonify({'success': True, 'reflection': refl.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# ===== MENTORSHIP RATING SYSTEM =====

def _count_skills(skill_string):
    """Count individual skills from a comma/semicolon separated skill string."""
    if not skill_string:
        return 0
    parts = [s.strip() for s in skill_string.replace(";", ",").split(",") if s.strip()]
    return len(parts)

def _check_mentorship_completed(mentee_id, mentor_id):
    """Check if a mentorship is considered completed: all tasks done or enough time has passed."""
    tasks = MenteeTask.query.filter_by(mentee_id=mentee_id, mentor_id=mentor_id).all()
    if not tasks:
        return False, 0
    completed = sum(1 for t in tasks if t.status == "completed")
    pct = round((completed / len(tasks)) * 100) if tasks else 0
    return pct >= 80 or completed == len(tasks), pct

def _compute_profile_completeness_score(user_id, user_type):
    """Return profile completeness as a 0-100 score."""
    if user_type == "1":
        result = calculate_mentor_profile_completion(user_id)
    elif user_type == "2":
        result = calculate_mentee_profile_completion(user_id)
    else:
        return 0
    return result.get("percentage", 0)

def _compute_profile_attractiveness_score(user_id, user_type):
    """Profile attractiveness based on skill count. Score = min(skill_count * 10, 100)."""
    if user_type == "1":
        profile = MentorProfile.query.filter_by(user_id=user_id).first()
        skills = profile.skills if profile else ""
    elif user_type == "2":
        profile = MenteeProfile.query.filter_by(user_id=user_id).first()
        skills = profile.key_skills if profile else ""
    else:
        return 0
    count = _count_skills(skills)
    return min(count * 10, 100)

def _compute_supervisor_review_score(mentor_id):
    """Dynamic supervisor review score based on mentor's track record.
    Returns score 0-100. Used to compute supervisor review weight dynamically:
    - 0 completed mentorships: weight=40%
    - 1-2 completed mentorships: weight=20%
    - 3+ completed mentorships: weight=0% (not factored in)
    The score itself reflects mentor quality from supervisor's perspective."""
    completed_count = 0
    total_tasks = 0
    completed_tasks = 0
    total_ratings = 0
    rating_sum = 0

    mentorships = MentorshipRequest.query.filter_by(
        mentor_id=mentor_id, final_status="approved"
    ).all()
    for mr in mentorships:
        done, _ = _check_mentorship_completed(mr.mentee_id, mr.mentor_id)
        if done:
            completed_count += 1
        pair_tasks = MenteeTask.query.filter_by(mentee_id=mr.mentee_id, mentor_id=mr.mentor_id).all()
        total_tasks += len(pair_tasks)
        completed_tasks += sum(1 for t in pair_tasks if t.status == "completed")
        for t in pair_tasks:
            tr = TaskRating.query.filter_by(task_type="master", task_id=t.id, mentor_id=mentor_id).first()
            if tr:
                total_ratings += 1
                rating_sum += tr.rating

    profile_score = _compute_profile_completeness_score(mentor_id, "1")
    task_completion_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
    avg_rating = (rating_sum / total_ratings * 20) if total_ratings > 0 else 50

    score = (profile_score * 0.3 + task_completion_rate * 0.4 + avg_rating * 0.3)
    return min(round(score), 100), completed_count

def _compute_mentorship_rating_score(mentee_id, mentor_id):
    """Compute mentee's overall mentorship rating (0-100 scale).
    Uses explicit mentorship-level rating if submitted, else averages task-level mentor_ratings."""
    explicit = MenteeFeedback.query.filter_by(
        mentee_id=mentee_id, task_type="mentorship"
    ).first()
    if explicit and explicit.mentor_rating:
        return explicit.mentor_rating * 20
    feedbacks = MenteeFeedback.query.filter(
        MenteeFeedback.mentee_id == mentee_id,
        MenteeFeedback.task_type == "master",
        MenteeFeedback.mentor_rating.isnot(None)
    ).all()
    if not feedbacks:
        return 0
    avg = sum(f.mentor_rating for f in feedbacks) / len(feedbacks)
    return round(avg * 20)

def _compute_task_performance_score(mentee_id, mentor_id):
    """Compute task performance rating from TaskRating (0-100 scale)."""
    task_ids = [t.id for t in MenteeTask.query.filter_by(
        mentee_id=mentee_id, mentor_id=mentor_id, status="completed"
    ).all()]
    if not task_ids:
        return 0
    ratings = TaskRating.query.filter(
        TaskRating.task_type == "master",
        TaskRating.task_id.in_(task_ids)
    ).all()
    if not ratings:
        return 0
    avg = sum(r.rating for r in ratings) / len(ratings)
    return round(avg * 20)

def _compute_supervisor_review_weight(completed_mentorships):
    """Dynamic weight for supervisor review based on experience."""
    if completed_mentorships >= 3:
        return 0
    elif completed_mentorships >= 1:
        return 20
    else:
        return 40

def compute_mentorship_composite_rating(mentee_id, mentor_id):
    """Compute the full composite rating for a mentorship pair.
    Returns dict with all components and the final weighted score."""
    profile_completeness = _compute_profile_completeness_score(mentor_id, "1")
    profile_attractiveness = _compute_profile_attractiveness_score(mentor_id, "1")
    sup_score, completed_count = _compute_supervisor_review_score(mentor_id)
    mentorship_rating = _compute_mentorship_rating_score(mentee_id, mentor_id)
    task_performance = _compute_task_performance_score(mentee_id, mentor_id)

    sup_weight = _compute_supervisor_review_weight(completed_count)
    other_weight = 100 - sup_weight
    remaining_weights = 20 + 20 + 20 + 40
    if remaining_weights > 0:
        pc_w = round(20 * other_weight / remaining_weights, 1)
        pa_w = round(20 * other_weight / remaining_weights, 1)
        mr_w = round(20 * other_weight / remaining_weights, 1)
        tp_w = round(40 * other_weight / remaining_weights, 1)
    else:
        pc_w = pa_w = mr_w = tp_w = 0

    final_score = (
        profile_completeness * (pc_w / 100) +
        profile_attractiveness * (pa_w / 100) +
        sup_score * (sup_weight / 100) +
        mentorship_rating * (mr_w / 100) +
        task_performance * (tp_w / 100)
    )

    return {
        "profile_completeness": profile_completeness,
        "profile_completeness_weight": round(pc_w, 1),
        "profile_attractiveness": profile_attractiveness,
        "profile_attractiveness_weight": round(pa_w, 1),
        "supervisor_review": sup_score,
        "supervisor_review_weight": sup_weight,
        "supervisor_review_completed_count": completed_count,
        "mentorship_rating": mentorship_rating,
        "mentorship_rating_weight": round(mr_w, 1),
        "task_performance": task_performance,
        "task_performance_weight": round(tp_w, 1),
        "final_score": round(final_score, 1),
        "star_rating": min(5, max(0, round(final_score / 20, 1)))
    }


@app.route("/api/mentorship_completion_status/<int:mentorship_id>")
def api_mentorship_completion_status(mentorship_id):
    """Check if a mentorship is completed and return task completion percentage."""
    if "email" not in session:
        return jsonify({"success": False, "message": "Unauthorized"})
    mr = db.session.get(MentorshipRequest, mentorship_id)
    if not mr:
        return jsonify({"success": False, "message": "Mentorship not found"})
    done, pct = _check_mentorship_completed(mr.mentee_id, mr.mentor_id)
    return jsonify({"success": True, "completed": done, "completion_pct": pct, "mentorship_id": mentorship_id})


@app.route("/api/mentorship_rating/<int:mentorship_id>")
def api_mentorship_rating(mentorship_id):
    """Get the composite rating for a mentorship."""
    if "email" not in session:
        return jsonify({"success": False, "message": "Unauthorized"})
    mr = db.session.get(MentorshipRequest, mentorship_id)
    if not mr:
        return jsonify({"success": False, "message": "Mentorship not found"})
    rating_data = compute_mentorship_composite_rating(mr.mentee_id, mr.mentor_id)
    done, pct = _check_mentorship_completed(mr.mentee_id, mr.mentor_id)
    rating_data["completed"] = done
    rating_data["completion_pct"] = pct
    return jsonify({"success": True, "rating": rating_data})


@app.route("/api/submit_mentorship_rating", methods=["POST"])
def api_submit_mentorship_rating():
    """Mentee submits an overall mentorship rating. Stores in MenteeFeedback with task_type='mentorship'."""
    if "email" not in session or session.get("user_type") != "2":
        return jsonify({"success": False, "message": "Unauthorized"})
    data = request.get_json(force=True)
    mentorship_id = data.get("mentorship_id")
    rating = data.get("rating")
    feedback = data.get("feedback", "")
    if not mentorship_id or not rating:
        return jsonify({"success": False, "message": "mentorship_id and rating required"})
    try:
        rating = int(rating)
        if rating < 1 or rating > 5:
            return jsonify({"success": False, "message": "Rating must be 1-5"})
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid rating"})
    mr = db.session.get(MentorshipRequest, mentorship_id)
    if not mr:
        return jsonify({"success": False, "message": "Mentorship not found"})
    mentee = User.query.filter_by(email=session["email"]).first()
    if not mentee or mr.mentee_id != mentee.id:
        return jsonify({"success": False, "message": "Not your mentorship"})
    done, _ = _check_mentorship_completed(mr.mentee_id, mr.mentor_id)
    if not done:
        return jsonify({"success": False, "message": "Mentorship is not yet completed"})
    existing = MenteeFeedback.query.filter_by(
        mentee_id=mentee.id, task_type="mentorship", task_id=mentorship_id
    ).first()
    if existing:
        existing.mentor_rating = rating
        existing.text = feedback
        existing.created_at = datetime.utcnow()
    else:
        fb = MenteeFeedback(
            mentee_id=mentee.id,
            task_id=mentorship_id,
            task_type="mentorship",
            mentor_rating=rating,
            text=feedback,
            created_at=datetime.utcnow()
        )
        db.session.add(fb)
    db.session.commit()
    return jsonify({"success": True, "message": "Rating submitted"})


@app.route("/api/submit_mentor_review", methods=["POST"])
def api_submit_mentor_review():
    """Mentor submits a review of the mentee. Stores in MentorReflection with task_type='mentorship'."""
    if "email" not in session or session.get("user_type") != "1":
        return jsonify({"success": False, "message": "Unauthorized"})
    data = request.get_json(force=True)
    mentorship_id = data.get("mentorship_id")
    rating = data.get("rating")
    feedback = data.get("feedback", "")
    strengths = data.get("strengths", "")
    improvements = data.get("improvements", "")
    if not mentorship_id or not rating:
        return jsonify({"success": False, "message": "mentorship_id and rating required"})
    try:
        rating = int(rating)
        if rating < 1 or rating > 5:
            return jsonify({"success": False, "message": "Rating must be 1-5"})
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid rating"})
    mr = db.session.get(MentorshipRequest, mentorship_id)
    if not mr:
        return jsonify({"success": False, "message": "Mentorship not found"})
    mentor = User.query.filter_by(email=session["email"]).first()
    if not mentor or mr.mentor_id != mentor.id:
        return jsonify({"success": False, "message": "Not your mentorship"})
    done, _ = _check_mentorship_completed(mr.mentee_id, mr.mentor_id)
    if not done:
        return jsonify({"success": False, "message": "Mentorship is not yet completed"})
    import json as _json
    review_data = _json.dumps({
        "rating": rating, "strengths": strengths,
        "improvements": improvements, "feedback": feedback
    })
    existing = MentorReflection.query.filter_by(
        mentor_id=mentor.id, task_type="mentorship", task_id=mentorship_id
    ).first()
    if existing:
        existing.text = feedback
        existing.extra = review_data
        existing.created_at = datetime.utcnow()
    else:
        refl = MentorReflection(
            mentor_id=mentor.id,
            task_id=mentorship_id,
            task_type="mentorship",
            text=feedback,
            extra=review_data,
            created_at=datetime.utcnow()
        )
        db.session.add(refl)
    db.session.commit()
    return jsonify({"success": True, "message": "Review submitted"})


@app.route("/api/get_mentorship_rating_data/<int:mentorship_id>")
def api_get_mentorship_rating_data(mentorship_id):
    """Get existing rating data for a mentorship (both mentee's and mentor's reviews)."""
    if "email" not in session:
        return jsonify({"success": False, "message": "Unauthorized"})
    mr = db.session.get(MentorshipRequest, mentorship_id)
    if not mr:
        return jsonify({"success": False, "message": "Mentorship not found"})
    mentee_fb = MenteeFeedback.query.filter_by(
        mentee_id=mr.mentee_id, task_type="mentorship", task_id=mentorship_id
    ).first()
    mentor_ref = MentorReflection.query.filter_by(
        mentor_id=mr.mentor_id, task_type="mentorship", task_id=mentorship_id
    ).first()
    import json as _json
    mentee_rating = None
    if mentee_fb:
        mentee_rating = {"rating": mentee_fb.mentor_rating, "feedback": mentee_fb.text or ""}
    mentor_review = None
    if mentor_ref:
        try:
            extra = _json.loads(mentor_ref.extra) if mentor_ref.extra else {}
        except Exception:
            extra = {}
        mentor_review = {
            "rating": extra.get("rating", 0),
            "feedback": mentor_ref.text or "",
            "strengths": extra.get("strengths", ""),
            "improvements": extra.get("improvements", "")
        }
    rating_info = compute_mentorship_composite_rating(mr.mentee_id, mr.mentor_id)
    return jsonify({
        "success": True,
        "mentee_rating": mentee_rating,
        "mentor_review": mentor_review,
        "composite": rating_info
    })


@app.route("/api/submit_supervisor_mentor_review", methods=["POST"])
def api_submit_supervisor_mentor_review():
    """Supervisor reviews and rates a mentor. Stores in InstitutionReflection with task_type='mentor_review'."""
    if "email" not in session or session.get("user_type") != "0":
        return jsonify({"success": False, "message": "Unauthorized"})
    data = request.get_json(force=True)
    mentor_id = data.get("mentor_id")
    rating = data.get("rating")
    review = data.get("review", "")
    if not mentor_id or not rating:
        return jsonify({"success": False, "message": "mentor_id and rating required"})
    try:
        rating = int(rating)
        if rating < 1 or rating > 5:
            return jsonify({"success": False, "message": "Rating must be 1-5"})
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid rating"})
    mentor = db.session.get(User, int(mentor_id))
    if not mentor:
        return jsonify({"success": False, "message": "Mentor not found"})
    supervisor = User.query.filter_by(email=session["email"]).first()
    import json as _json
    review_data = _json.dumps({
        "rating": rating, "review": review,
        "supervisor_id": supervisor.id, "supervisor_name": supervisor.name
    })
    existing = InstitutionReflection.query.filter_by(
        institution_id=supervisor.id, task_type="mentor_review", task_id=mentor_id
    ).first()
    if existing:
        existing.text = review
        existing.notes = review_data
        existing.created_at = datetime.utcnow()
    else:
        refl = InstitutionReflection(
            institution_id=supervisor.id,
            task_id=mentor_id,
            task_type="mentor_review",
            text=review,
            notes=review_data,
            created_at=datetime.utcnow()
        )
        db.session.add(refl)
    db.session.commit()
    return jsonify({"success": True, "message": "Supervisor review submitted"})


@app.route("/api/get_supervisor_mentor_review/<int:mentor_id>")
def api_get_supervisor_mentor_review(mentor_id):
    """Get supervisor review for a mentor."""
    if "email" not in session:
        return jsonify({"success": False, "message": "Unauthorized"})
    user = User.query.filter_by(email=session["email"]).first()
    import json as _json
    refl = InstitutionReflection.query.filter_by(
        task_type="mentor_review", task_id=mentor_id
    ).order_by(InstitutionReflection.created_at.desc()).first()
    if not refl:
        return jsonify({"success": True, "review": None})
    try:
        extra = _json.loads(refl.notes) if refl.notes else {}
    except Exception:
        extra = {}
    return jsonify({
        "success": True,
        "review": {
            "rating": extra.get("rating", 0),
            "review": refl.text or "",
            "supervisor_name": extra.get("supervisor_name", ""),
            "date": refl.created_at.isoformat() if refl.created_at else ""
        }
    })


@app.route("/api/get_all_supervisor_mentor_reviews")
def api_get_all_supervisor_mentor_reviews():
    """Get all supervisor reviews for all mentors (supervisor dashboard)."""
    if "email" not in session or session.get("user_type") != "0":
        return jsonify({"success": False, "message": "Unauthorized"})
    import json as _json
    reflections = InstitutionReflection.query.filter_by(task_type="mentor_review").all()
    reviews = []
    for r in reflections:
        try:
            extra = _json.loads(r.notes) if r.notes else {}
        except Exception:
            extra = {}
        mentor_user = db.session.get(User, r.task_id)
        reviews.append({
            "mentor_id": r.task_id,
            "mentor_name": mentor_user.name if mentor_user else "Unknown",
            "rating": extra.get("rating", 0),
            "review": r.text or "",
            "supervisor_name": extra.get("supervisor_name", ""),
            "date": r.created_at.isoformat() if r.created_at else ""
        })
    return jsonify({"success": True, "reviews": reviews})


@app.route("/api/get_mentor_rating_breakdown/<int:mentor_id>")
def api_get_mentor_rating_breakdown(mentor_id):
    """Get the full rating breakdown for a mentor (all components)."""
    if "email" not in session:
        return jsonify({"success": False, "message": "Unauthorized"})
    mentor = db.session.get(User, mentor_id)
    if not mentor:
        return jsonify({"success": False, "message": "Mentor not found"})
    sup_score, completed_count = _compute_supervisor_review_score(mentor_id)
    profile_comp = _compute_profile_completeness_score(mentor_id, "1")
    profile_att = _compute_profile_attractiveness_score(mentor_id, "1")
    mentorships = MentorshipRequest.query.filter_by(
        mentor_id=mentor_id, final_status="approved"
    ).all()
    avg_mentorship_rating = 0
    avg_task_perf = 0
    mr_count = 0
    tp_count = 0
    mr_sum = 0
    tp_sum = 0
    for mr in mentorships:
        mr_score = _compute_mentorship_rating_score(mr.mentee_id, mr.mentor_id)
        if mr_score > 0:
            mr_sum += mr_score
            mr_count += 1
        tp_score = _compute_task_performance_score(mr.mentee_id, mr.mentor_id)
        if tp_score > 0:
            tp_sum += tp_score
            tp_count += 1
    if mr_count > 0:
        avg_mentorship_rating = round(mr_sum / mr_count, 1)
    if tp_count > 0:
        avg_task_perf = round(tp_sum / tp_count, 1)
    sup_weight = _compute_supervisor_review_weight(completed_count)
    other_weight = 100 - sup_weight
    remaining_weights = 20 + 20 + 20 + 40
    if remaining_weights > 0:
        pc_w = round(20 * other_weight / remaining_weights, 1)
        pa_w = round(20 * other_weight / remaining_weights, 1)
        mr_w = round(20 * other_weight / remaining_weights, 1)
        tp_w = round(40 * other_weight / remaining_weights, 1)
    else:
        pc_w = pa_w = mr_w = tp_w = 0
    final_score = (
        profile_comp * (pc_w / 100) + profile_att * (pa_w / 100) +
        sup_score * (sup_weight / 100) + avg_mentorship_rating * (mr_w / 100) +
        avg_task_perf * (tp_w / 100)
    )
    return jsonify({
        "success": True,
        "breakdown": {
            "profile_completeness": profile_comp,
            "profile_completeness_weight": round(pc_w, 1),
            "profile_attractiveness": profile_att,
            "profile_attractiveness_weight": round(pa_w, 1),
            "supervisor_review": sup_score,
            "supervisor_review_weight": sup_weight,
            "completed_mentorships": completed_count,
            "mentorship_rating": avg_mentorship_rating,
            "mentorship_rating_weight": round(mr_w, 1),
            "task_performance": avg_task_perf,
            "task_performance_weight": round(tp_w, 1),
            "final_score": round(final_score, 1),
            "star_rating": min(5, max(0, round(final_score / 20, 1)))
        }
    })


@app.route("/get_supervisor_tasks_data")
def get_supervisor_tasks_data():
    if "email" not in session or session.get("user_type") != "0":
        return jsonify({"success": False, "message": "Unauthorized"})
    
    try:
        # Pre-fetch all entities to avoid N+1 query storm
        users_map = {u.id: u for u in User.query.all()}
        master_tasks_map = {m.id: m for m in MasterTask.query.all()}
        all_ratings = TaskRating.query.all()
        ratings_map = {(r.task_type, r.task_id): r for r in all_ratings}
        ratings_set = {(r.task_type, r.task_id) for r in all_ratings}
        meetings_map = {m.id: m for m in MeetingRequest.query.all()}
        all_pdata = _get_all_meeting_participants()

        personal_tasks = PersonalTask.query.all()
        mentee_tasks = MenteeTask.query.all()

        tasks = []
        now_dt = datetime.utcnow()
        default_due = now_dt + timedelta(days=30)
        
        # Process personal tasks
        for task in personal_tasks:
            mentee = users_map.get(task.mentee_id)
            mentor = users_map.get(task.mentor_id) if task.mentor_id else None
            rating_obj = ratings_map.get(('personal', task.id))
            
            due_date = task.due_date or default_due
            status = compute_task_progress_status(
                "personal", task.id, task.mentee_id, task.mentor_id or None,
                ratings_set=ratings_set, meetings_map=meetings_map, all_pdata=all_pdata
            )
            is_critical = task.priority == 'high' and status != 'done'
            
            tasks.append({
                'id': f"personal_{task.id}",
                'title': task.title,
                'description': task.description or 'No description provided',
                'dueDate': due_date.isoformat(),
                'priority': task.priority,
                'status': status,
                'progress': task.progress or 0,
                'mentorId': task.mentor_id,
                'mentorName': mentor.name if mentor else 'Self',
                'menteeId': task.mentee_id,
                'menteeName': mentee.name if mentee else 'Unknown',
                'category': 'Personal Task',
                'rating': rating_obj.rating if rating_obj else None,
                'isCritical': is_critical,
                'type': 'personal',
                'journey_phase': 'Custom Task',
                'month': 'N/A',
                'meeting_number': 'N/A'
            })
        
        # Process mentee tasks
        for task in mentee_tasks:
            master_task = master_tasks_map.get(task.task_id)
            mentee = users_map.get(task.mentee_id)
            mentor = users_map.get(task.mentor_id)
            
            if master_task and mentee and mentor:
                rating_obj = ratings_map.get(('master', task.id))
                due_date = task.due_date or default_due
                status = compute_task_progress_status(
                    "master", task.id, task.mentee_id, task.mentor_id,
                    ratings_set=ratings_set, meetings_map=meetings_map, all_pdata=all_pdata
                )
                is_overdue = due_date < now_dt and status != 'done'
                
                tasks.append({
                    'id': f"master_{task.id}",
                    'title': f"{master_task.purpose_of_call} - {master_task.month}",
                    'description': master_task.mentee_focus or 'No description provided',
                    'dueDate': due_date.isoformat(),
                    'priority': 'medium',
                    'status': status,
                    'progress': task.progress or 0,
                    'mentorId': task.mentor_id,
                    'mentorName': mentor.name,
                    'menteeId': task.mentee_id,
                    'menteeName': mentee.name,
                    'category': 'Mentorship Task',
                    'rating': rating_obj.rating if rating_obj else None,
                    'isCritical': is_overdue,
                    'type': 'master',
                    'journey_phase': master_task.journey_phase,
                    'month': master_task.month,
                    'meeting_number': task.meeting_number
                })

        # Add serial numbers to tasks for frontend display
        for i, t in enumerate(tasks, start=1):
            try:
                t['serial'] = i
            except Exception:
                pass

        mentors = [{'id': mid, 'name': mname} for mid, mname in 
                   {t.get('mentorId'): t['mentorName'] for t in tasks if t.get('mentorId')}.items()]
        mentees = [{'id': mid, 'name': mname} for mid, mname in 
                   {t.get('menteeId'): t['menteeName'] for t in tasks if t.get('menteeId')}.items()]

        return jsonify({
            "success": True,
            "tasks": tasks,
            "mentors": mentors,
            "mentees": mentees
        })
        
    except Exception as e:
        print(f"Error in get_supervisor_tasks_data: {str(e)}")
        return jsonify({
            "success": False,
            "message": str(e),
            "tasks": [],
            "mentors": [],
            "mentees": []
        })



#------------------------------------------------------------------------------------------------------------------- 
#------------------------------------------------------------------------------------------------------------------- 
#------------------------------------------------------------------------------------------------------------------- 


# ------------------ SUPERVISOR TASK MANAGEMENT ROUTES ------------------
@app.route("/supervisor_tasks")
def supervisor_tasks():
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))
    
    try:
        users_map = {u.id: u for u in User.query.all()}
        all_ratings = TaskRating.query.all()
        ratings_map = {(r.task_type, r.task_id): r for r in all_ratings}
        ratings_set = {(r.task_type, r.task_id) for r in all_ratings}
        meetings_map = {m.id: m for m in MeetingRequest.query.all()}
        all_pdata = _get_all_meeting_participants()

        # Get all tasks with proper joins
        personal_tasks = db.session.query(PersonalTask, User).join(
            User, PersonalTask.mentee_id == User.id
        ).all()
        
        mentee_tasks = db.session.query(MenteeTask, MasterTask, User).join(
            MasterTask, MenteeTask.task_id == MasterTask.id
        ).join(
            User, MenteeTask.mentee_id == User.id
        ).all()
        
        # Prepare tasks data
        all_tasks = []
        
        # Process personal tasks
        for task, user in personal_tasks:
            mentor = users_map.get(task.mentor_id) if task.mentor_id else None
            r_obj = ratings_map.get(('personal', task.id))
            status = compute_task_progress_status(
                "personal", task.id, task.mentee_id, task.mentor_id or None,
                ratings_set=ratings_set, meetings_map=meetings_map, all_pdata=all_pdata
            )
            all_tasks.append({
                'id': f"personal_{task.id}",
                'title': task.title,
                'description': task.description,
                'due_date': task.due_date,
                'priority': task.priority,
                'status': status,
                'progress': task.progress,
                'mentee_name': user.name,
                'mentor_name': mentor.name if mentor else 'Self',
                'category': 'Personal Task',
                'type': 'personal',
                'rating': r_obj.rating if r_obj else None
            })
        
        # Process mentee tasks  
        for task, master, user in mentee_tasks:
            mentor = users_map.get(task.mentor_id)
            r_obj = ratings_map.get(('master', task.id))
            status = compute_task_progress_status(
                "master", task.id, task.mentee_id, task.mentor_id,
                ratings_set=ratings_set, meetings_map=meetings_map, all_pdata=all_pdata
            )
            all_tasks.append({
                'id': f"master_{task.id}",
                'title': f"{master.purpose_of_call} - {master.month}",
                'description': master.mentee_focus,
                'due_date': task.due_date,
                'priority': 'medium',
                'status': status,
                'progress': task.progress,
                'mentee_name': user.name,
                'mentor_name': mentor.name if mentor else 'Unknown',
                'category': 'Mentorship Task',
                'type': 'master',
                'rating': r_obj.rating if r_obj else None
            })
        
        # Add serial numbers to all_tasks (dicts) for display
        for i, task in enumerate(all_tasks, start=1):
            try:
                task['serial'] = i
            except Exception:
                pass

        return render_template(
            "supervisor/supervisor_tasks.html",
            show_sidebar=True,
            profile_complete=True,
            all_tasks=all_tasks
        )
        
    except Exception as e:
        print(f"❌ Error in supervisor_tasks: {str(e)}")
        import traceback
        traceback.print_exc()
        return render_template(
            "supervisor/supervisor_tasks.html",
            show_sidebar=True,
            profile_complete=True,
            all_tasks=[]
        )
        

# ------------------ SUPERVISOR RATING VIEW ROUTES ------------------
@app.route('/supervisor_get_task_rating/<task_type>/<int:task_id>')
def supervisor_get_task_rating(task_type, task_id):
    try:
        if "email" not in session or session.get("user_type") not in ("0", "3"):
            return jsonify({'success': False, 'message': 'Unauthorized'})
        
        # Supervisor can see rating for any task
        rating = TaskRating.query.filter_by(
            task_id=task_id,
            task_type=task_type
        ).first()
        
        if rating:
            return jsonify({
                'success': True,
                'rating': {
                    'rating': rating.rating,
                    'feedback': rating.feedback,
                    'strengths': rating.strengths,
                    'improvements': rating.improvements,
                    'rated_at': rating.rated_at.isoformat()
                }
            })
        else:
            return jsonify({'success': True, 'rating': None})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route("/institution_calendar")
def institution_calendar():
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))
    
    user = User.query.filter_by(email=session["email"]).first()

    institution, institution_id, institution_name, aliases = _get_institution_details(user)

    if institution_name and not user.institution:
        user.institution = institution_name
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Direct members of the institution
    direct_mentors, direct_mentees = _get_institution_members(user, include_paired=False)
    member_user_ids = [m.id for m in direct_mentors + direct_mentees]

    # Fetch all meetings involving this institution:
    # 1) Meetings created BY this institution (requester_id = institution user)
    # 2) Meetings where a mentor/mentee from this institution is a participant
    institution_meeting_ids = set()

    # Case 1: meetings this institution created
    created = MeetingRequest.query.filter(
        MeetingRequest.requester_id == user.id
    ).all()
    for m in created:
        institution_meeting_ids.add(m.id)

    # Case 2: meetings involving a mentor/mentee from this institution
    if member_user_ids:
        linked = (
            MeetingRequest.query
            .filter(
                or_(
                    MeetingRequest.requester_id.in_(member_user_ids),
                    MeetingRequest.requested_to_id.in_(member_user_ids)
                )
            )
            .all()
        )
        for m in linked:
            institution_meeting_ids.add(m.id)

    meetings = MeetingRequest.query.filter(
        MeetingRequest.id.in_(institution_meeting_ids)
    ).order_by(
        MeetingRequest.meeting_date.asc(), MeetingRequest.meeting_time.asc()
    ).all()

    from datetime import datetime, date
    now = datetime.now()

    calendar_meetings = []
    for meeting in meetings:
        requester = db.session.get(User, meeting.requester_id)
        requested_to = db.session.get(User, meeting.requested_to_id)

        # Determine which is mentor and which is mentee by user_type
        mentee = None
        mentor = None
        if requester:
            if requester.user_type == "2":
                mentee = requester
            elif requester.user_type == "1":
                mentor = requester
        if requested_to:
            if requested_to.user_type == "2":
                mentee = requested_to
            elif requested_to.user_type == "1":
                mentor = requested_to
        # Fallback: check meeting participants data (for admin/institution scheduled meetings)
        participants_info = _get_meeting_participants(meeting.id)
        if participants_info:
            if not mentee and participants_info.get("mentee_id"):
                mentee = db.session.get(User, participants_info["mentee_id"])
            if not mentor and participants_info.get("mentor_id"):
                mentor = db.session.get(User, participants_info["mentor_id"])
        # Fallback: if types didn't resolve, use position-based default
        if not mentee and not mentor:
            mentee = requester
            mentor = requested_to
        
        meeting_datetime = datetime.combine(meeting.meeting_date, meeting.meeting_time)
        
        if meeting.status == "cancelled":
            status = "cancelled"
        elif meeting_datetime < now:
            status = "completed"
        else:
            status = "upcoming"
        
        calendar_meetings.append({
            "id": meeting.id,
            "title": meeting.meeting_title,
            "date": meeting_datetime.strftime("%Y-%m-%dT%H:%M:%S") if meeting_datetime else "",
            "time": meeting.meeting_time.strftime("%I:%M %p") if meeting.meeting_time else "",
            "duration": meeting.meeting_duration,
            "mentee": mentee.name if mentee else "Unknown Mentee",
            "mentee_email": mentee.email if mentee else "",
            "mentor": mentor.name if mentor else "Unknown Mentor",
            "mentor_email": mentor.email if mentor else "",
            "type": "Video Call",
            "status": status,
            "description": meeting.meeting_description or "No description provided",
            "meet_link": meeting.meet_link,
            "created_at": meeting.created_at.strftime("%Y-%m-%d %H:%M:%S") if meeting.created_at else ""
        })
    
    # Direct members of the institution
    direct_mentors, direct_mentees = _get_institution_members(user, include_paired=False)
    direct_mentor_ids = set(m.id for m in direct_mentors)
    direct_mentee_ids = set(m.id for m in direct_mentees)

    # Build active mentorship pairs for this institution (for dual-view filtering)
    # Include mentorships where mentee is from this institution (mentor may be external)
    # OR mentor is from this institution (mentee may be external)
    mentorship_conditions = []
    if direct_mentee_ids:
        mentorship_conditions.append(MentorshipRequest.mentee_id.in_(direct_mentee_ids))
    if direct_mentor_ids:
        mentorship_conditions.append(MentorshipRequest.mentor_id.in_(direct_mentor_ids))

    if mentorship_conditions:
        active_mentorships = MentorshipRequest.query.filter(
            or_(*mentorship_conditions),
            MentorshipRequest.final_status == "approved"
        ).all()
    else:
        active_mentorships = []

    mentee_to_mentors = {}
    mentor_to_mentees = {}
    all_connected_mentor_ids = set()
    all_connected_mentee_ids = set()

    for mr in active_mentorships:
        mentee_id_str = str(mr.mentee_id)
        mentor_id_str = str(mr.mentor_id)
        mentee_to_mentors.setdefault(mentee_id_str, []).append(mentor_id_str)
        mentor_to_mentees.setdefault(mentor_id_str, []).append(mentee_id_str)
        all_connected_mentor_ids.add(mr.mentor_id)
        all_connected_mentee_ids.add(mr.mentee_id)

    # All mentors for dropdown: direct mentors + external mentors paired with this institution's mentees
    all_mentor_ids = direct_mentor_ids | all_connected_mentor_ids
    existing_mentors_dict = {m.id: m for m in direct_mentors}
    missing_mentor_ids = [mid for mid in all_mentor_ids if mid not in existing_mentors_dict]
    if missing_mentor_ids:
        external_mentors = User.query.filter(User.id.in_(missing_mentor_ids)).all()
        for m in external_mentors:
            existing_mentors_dict[m.id] = m
    dropdown_mentors = list(existing_mentors_dict.values())
    dropdown_mentors.sort(key=lambda u: (u.name or "").lower())

    # All mentees for dropdown: direct mentees + external mentees paired with this institution's mentors
    all_mentee_ids = direct_mentee_ids | all_connected_mentee_ids
    existing_mentees_dict = {m.id: m for m in direct_mentees}
    missing_mentee_ids = [mid for mid in all_mentee_ids if mid not in existing_mentees_dict]
    if missing_mentee_ids:
        external_mentees = User.query.filter(User.id.in_(missing_mentee_ids)).all()
        for m in external_mentees:
            existing_mentees_dict[m.id] = m
    dropdown_mentees = list(existing_mentees_dict.values())
    dropdown_mentees.sort(key=lambda u: (u.name or "").lower())

    return render_template(
        "institution/institution_calendar.html",
        show_sidebar=True,
        meetings=calendar_meetings,
        mentors=dropdown_mentors,
        mentees=dropdown_mentees,
        direct_mentor_ids=[str(mid) for mid in direct_mentor_ids],
        direct_mentee_ids=[str(mid) for mid in direct_mentee_ids],
        institution_id=institution_id,
        institution_name=institution_name,
        mentee_to_mentors=mentee_to_mentors,
        mentor_to_mentees=mentor_to_mentees
    )


# ---------------meeting details----------------
@app.route("/mentee_meeting_details")
def mentee_meeting_details():
    if "email" not in session or session.get("user_type") != "2":
        return redirect(url_for("signin"))

    # Get logged-in mentee
    mentee = User.query.filter_by(email=session["email"]).first()

    # Fetch all meetings created by this mentee
    meetings = MeetingRequest.query.filter_by(requester_id=mentee.id).order_by(
        MeetingRequest.meeting_date.desc(),
        MeetingRequest.meeting_time.desc()
    ).all()

    all_participants = _get_all_meeting_participants()
    extra_meeting_ids = []
    for mid, pdata in all_participants.items():
        if pdata.get("mentee_id") == mentee.id:
            extra_meeting_ids.append(mid)

    extra_meetings = []
    if extra_meeting_ids:
        extra_meetings = MeetingRequest.query.filter(
            MeetingRequest.id.in_(extra_meeting_ids),
            ~MeetingRequest.id.in_([m.id for m in meetings])
        ).order_by(
            MeetingRequest.meeting_date.desc(),
            MeetingRequest.meeting_time.desc()
        ).all()

    all_meetings = list(meetings) + list(extra_meetings)

    return render_template(
        "mentee/mentee_meeting_details.html",
        show_sidebar=True,
        meetings=all_meetings
    )

@app.route("/mentor_meeting_details")
def mentor_meeting_details():
    if "email" not in session or session.get("user_type") != "1":
        return redirect(url_for("signin"))

    # Get logged-in mentee
    mentor = User.query.filter_by(email=session["email"]).first()

    # Fetch all meetings created by this mentor
    meetings = MeetingRequest.query.filter_by(requested_to_id=mentor.id).order_by(
        MeetingRequest.meeting_date.desc(),
        MeetingRequest.meeting_time.desc()
    ).all()

    all_participants = _get_all_meeting_participants()
    extra_meeting_ids = []
    for mid, pdata in all_participants.items():
        if pdata.get("mentor_id") == mentor.id:
            extra_meeting_ids.append(mid)

    extra_meetings = []
    if extra_meeting_ids:
        extra_meetings = MeetingRequest.query.filter(
            MeetingRequest.id.in_(extra_meeting_ids),
            ~MeetingRequest.id.in_([m.id for m in meetings])
        ).order_by(
            MeetingRequest.meeting_date.desc(),
            MeetingRequest.meeting_time.desc()
        ).all()

    all_meetings = list(meetings) + list(extra_meetings)

    return render_template(
        "mentor/mentor_meeting_details.html",
        show_sidebar=True,
        meetings=all_meetings
    )

# ------------------- RESCHEDULE MEETING -------------------
@app.route("/reschedule_meeting/<int:meeting_id>", methods=["POST"])
def reschedule_meeting(meeting_id):
    if "email" not in session or session.get("user_type") != "1":
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    try:
        data = request.get_json()
        new_date = data.get("new_date")
        new_time = data.get("new_time")
        reason = data.get("reason", "").strip()

        if not new_date or not new_time:
            return jsonify({"success": False, "message": "Please provide new date and time"}), 400

        mentor = User.query.filter_by(email=session["email"]).first()
        meeting = MeetingRequest.query.get(meeting_id)

        if not meeting:
            return jsonify({"success": False, "message": "Meeting not found"}), 404

        if meeting.requested_to_id != mentor.id:
            return jsonify({"success": False, "message": "You can only reschedule your own meetings"}), 403

        # Parse new date and time
        new_meeting_date = datetime.strptime(new_date, "%Y-%m-%d").date()
        new_meeting_time = datetime.strptime(new_time, "%H:%M").time()

        # Calculate original meeting datetime
        original_datetime = datetime.combine(meeting.meeting_date, meeting.meeting_time)
        now = datetime.now()

        # Check if rescheduling within 8 hours of original meeting time
        time_until_meeting = original_datetime - now
        hours_until_meeting = time_until_meeting.total_seconds() / 3600

        # If less than 8 hours until meeting, reason is mandatory
        if hours_until_meeting <= 8 and hours_until_meeting > 0:
            if not reason:
                return jsonify({
                    "success": False, 
                    "message": "Reason is required when rescheduling within 8 hours of the meeting",
                    "urgent": True
                }), 400

        # Store original date/time before updating
        if not meeting.original_date:  # Only store first original values
            meeting.original_date = meeting.meeting_date
            meeting.original_time = meeting.meeting_time

        # Update meeting with new date/time
        meeting.meeting_date = new_meeting_date
        meeting.meeting_time = new_meeting_time
        meeting.is_rescheduled = True
        meeting.reschedule_reason = reason if reason else None
        meeting.rescheduled_at = datetime.utcnow()
        meeting.rescheduled_by_id = mentor.id
        meeting.status = "rescheduled"

        # Update Google Calendar event if exists
        if meeting.gcal_event_id:
            try:
                service = get_calendar_service()
                
                # Calculate new start and end times
                new_start_datetime = datetime.combine(new_meeting_date, new_meeting_time)
                new_end_datetime = new_start_datetime + timedelta(minutes=meeting.meeting_duration)
                
                event_update = {
                    "start": {"dateTime": new_start_datetime.isoformat(), "timeZone": MEETING_TIMEZONE},
                    "end": {"dateTime": new_end_datetime.isoformat(), "timeZone": MEETING_TIMEZONE},
                }
                
                service.events().patch(
                    calendarId=CALENDAR_ID,
                    eventId=meeting.gcal_event_id,
                    body=event_update,
                    sendUpdates="all"
                ).execute()
            except Exception as e:
                print(f"Error updating Google Calendar: {str(e)}")
                # Continue even if calendar update fails

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Meeting rescheduled successfully",
            "new_date": new_meeting_date.strftime("%Y-%m-%d"),
            "new_time": new_meeting_time.strftime("%I:%M %p")
        })

    except Exception as e:
        db.session.rollback()
        print(f"Error rescheduling meeting: {str(e)}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

# ------------------- CANCEL MEETING -------------------
@app.route("/cancel_meeting/<int:meeting_id>", methods=["POST"])
def cancel_meeting(meeting_id):
    if "email" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    user_type = session.get("user_type")
    if user_type not in ("0", "1"):
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    try:
        data = request.get_json()
        reason = data.get("reason", "").strip()

        if not reason:
            return jsonify({"success": False, "message": "Please provide a reason for cancellation"}), 400

        user = User.query.filter_by(email=session["email"]).first()
        meeting = MeetingRequest.query.get(meeting_id)

        if not meeting:
            return jsonify({"success": False, "message": "Meeting not found"}), 404

        if user_type == "1" and meeting.requested_to_id != user.id:
            return jsonify({"success": False, "message": "You can only cancel your own meetings"}), 403

        meeting.status = "cancelled"
        meeting.reschedule_reason = reason
        meeting.rescheduled_at = datetime.utcnow()
        meeting.rescheduled_by_id = user.id

        if meeting.gcal_event_id:
            try:
                service = get_calendar_service()
                if service:
                    service.events().delete(
                        calendarId=CALENDAR_ID,
                        eventId=meeting.gcal_event_id,
                        sendUpdates="all"
                    ).execute()
            except Exception as e:
                print(f"Error deleting Google Calendar event: {str(e)}")

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Meeting cancelled successfully"
        })

    except Exception as e:
        db.session.rollback()
        print(f"Error cancelling meeting: {str(e)}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

# ---------------- Supervisor - All Meeting Details ----------------
@app.route("/supervisor_meeting_details")
def supervisor_meeting_details():
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))

    # Fetch all meetings in ascending order (oldest first)
    meetings = (
        MeetingRequest.query
        .order_by(MeetingRequest.meeting_date.asc(), MeetingRequest.meeting_time.asc())
        .all()
    )

    # Get current date for timing calculations
    from datetime import datetime, date
    today = date.today()
    now = datetime.now()

    # Prepare formatted meeting data with mentee & mentor info
    meeting_data = []
    for meeting in meetings:
        mentee = User.query.get(meeting.requester_id)
        mentor = User.query.get(meeting.requested_to_id)

        # Calculate timing category
        meeting_datetime = datetime.combine(meeting.meeting_date, meeting.meeting_time)
        is_upcoming = meeting_datetime > now

        meeting_data.append({
            "id": meeting.id,
            "title": meeting.meeting_title,
            "description": meeting.meeting_description,
            "date": meeting.meeting_date.strftime("%d-%m-%Y"),
            "time": meeting.meeting_time.strftime("%I:%M %p"),
            "duration": meeting.meeting_duration,
            "status": meeting.status,
            "mentee_name": mentee.name if mentee else "Unknown",
            "mentee_email": mentee.email if mentee else "N/A",
            "mentor_name": mentor.name if mentor else "Unknown",
            "mentor_email": mentor.email if mentor else "N/A",
            "created_at": meeting.created_at.strftime("%d-%m-%Y %I:%M %p") if meeting.created_at else "",
            "is_upcoming": is_upcoming,
            "meet_link": meeting.meet_link,
        })

    return render_template(
        "supervisor/supervisor_meeting_details.html",
        show_sidebar=True,
        meetings=meeting_data
    )

# ------------------- HANDLE MENTORSHIP REQUEST ------------------
@app.route("/request_mentorship", methods=["POST"])
def request_mentorship(): 
    if "email" not in session or str(session.get("user_type")) != "2":
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    try:
        # Get mentee (current user)
        mentee = User.query.filter_by(email=session["email"]).first()
        if not mentee:
            return jsonify({"success": False, "message": "User not found"}), 404
        
        # Check parent consent status ONLY for under-18 mentees
        mentee_profile = MenteeProfile.query.filter_by(user_id=mentee.id).first()
        if mentee_profile and mentee_profile.dob and is_under_18(mentee_profile.dob):
            if mentee_profile.parent_consent_status == "pending":
                return jsonify({
                    "success": False, 
                    "message": "You need parent/guardian approval before requesting mentorship. Please check your email or update your parent's email in your profile."
                }), 403
            
            if mentee_profile.parent_consent_status == "rejected":
                return jsonify({
                    "success": False, 
                    "message": "Your parent/guardian has not approved your participation. Please contact support if you need assistance."
                }), 403
        
        data = request.get_json(silent=True)
        if not data and request.form:
            data = request.form.to_dict()
        if not data:
            return jsonify({"success": False, "message": "Invalid request data"}), 400

        mentor_id = data.get("mentor_id")
        purpose = data.get("purpose")
        mentor_type = data.get("mentor_type")
        term = data.get("term")
        duration_months = data.get("duration_months")
        why_need_mentor = data.get("why_need_mentor")
        linkedin_profile = (data.get("linkedin_profile") or "").strip()

        # Validate required fields
        if not all([mentor_id, purpose, mentor_type, term, duration_months, why_need_mentor]):
            return jsonify({"success": False, "message": "Missing required fields"}), 400

        # Validate and convert mentor_id to integer
        try:
            mentor_id = int(mentor_id)
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": "Invalid mentor ID"}), 400

        # Validate duration_months is a positive integer
        try:
            if isinstance(duration_months, str):
                import re
                nums = re.findall(r'\d+', duration_months)
                duration_months = int(nums[0]) if nums else int(duration_months)
            else:
                duration_months = int(duration_months)
            if duration_months <= 0:
                return jsonify({"success": False, "message": "Duration must be a positive number"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": "Invalid duration value"}), 400

        # Verify mentor exists
        mentor = db.session.get(User, mentor_id)
        if not mentor:
            # Fallback in case mentor_profile id was passed instead of user_id
            m_prof = db.session.get(MentorProfile, mentor_id)
            if m_prof:
                mentor = db.session.get(User, m_prof.user_id)
                if mentor:
                    mentor_id = mentor.id
        if not mentor:
            return jsonify({"success": False, "message": "Mentor not found"}), 404

        # Check if user is trying to request themselves as mentor
        if mentee.id == mentor_id:
            return jsonify({"success": False, "message": "Cannot request mentorship from yourself"}), 400
    
        # Check for existing pending request to same mentor
        existing_request = MentorshipRequest.query.filter_by(
            mentee_id=mentee.id,
            mentor_id=mentor_id,
        ).all()
        
        # loop through existing requests to check status
        for req in existing_request:
            if req.mentor_status == "pending" or req.supervisor_status == "pending":
                return jsonify({"success": False, "message": "You already have a pending request with this mentor."}), 400
            if req.mentor_status == "accepted" and req.supervisor_status == "approved" and req.final_status == "approved":
                return jsonify({"success": False, "message": "You are already assigned to this mentor."}), 400

        # Create new mentorship request
        new_request = MentorshipRequest(
            mentee_id=mentee.id,
            mentor_id=mentor_id,
            purpose=str(purpose).strip()[:1000] if purpose else "",
            mentor_type=str(mentor_type).strip()[:20] if mentor_type else "",
            term=str(term).strip()[:20] if term else "",
            duration_months=duration_months,
            why_need_mentor=str(why_need_mentor).strip() if why_need_mentor else "",
            linkedin_profile=str(linkedin_profile).strip()[:500] if linkedin_profile else None,
            mentor_status="pending",
            supervisor_status="pending",
            final_status="pending"
        )
        
        db.session.add(new_request)
        db.session.commit()

        # Send in-app notification to mentor
        try:
            create_notification(
                mentor_id,
                f"You have a new mentorship request from {mentee.name or 'a mentee'}.",
                link="/mentor_mentorship_request"
            )
        except Exception as notif_err:
            app.logger.warning(f"Failed to create mentor notification: {notif_err}")

        return jsonify({
            "success": True, 
            "message": "Mentorship request sent successfully!",
            "request_id": new_request.id
        }), 200

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        app.logger.error(f"Error in request_mentorship: {str(e)}")
        return jsonify({"success": False, "message": f"Could not submit request: {str(e)}"}), 500

@app.route("/mentor_response", methods=["POST"])
def mentor_response():
    # Support both form POST and JSON AJAX
    if request.is_json:
        data = request.get_json()
        request_id = data.get("request_id")
        action = data.get("action")
    else:
        request_id = request.form.get("request_id")
        action = request.form.get("action")

    is_ajax = request.is_json

    if not request_id or not action:
        if is_ajax:
            return jsonify({"success": False, "message": "Invalid request!"}), 400
        flash("Invalid request!", "error")
        return redirect(url_for("mentordashboard"))

    # Fetch mentorship request
    mentorship_request = MentorshipRequest.query.get(int(request_id))
    if not mentorship_request:
        if is_ajax:
            return jsonify({"success": False, "message": "Request not found!"}), 404
        flash("Request not found!", "error")
        return redirect(url_for("mentordashboard"))

    # Ensure mentor is logged in
    mentor = None
    if "email" in session and session.get("user_type") == "1":
        mentor = User.query.filter_by(email=session["email"]).first()

    if not mentor or mentorship_request.mentor_id != mentor.id:
        if is_ajax:
            return jsonify({"success": False, "message": "Not your request!"}), 403
        flash("This is not your request or you are not logged in as mentor!", "error")
        return redirect(url_for("mentordashboard"))

    # Update status
    mentorship_request.mentor_status = "accepted" if action == "accept" else "rejected"

    # For anchor mentors: auto-approve and assign tasks when mentor accepts
    assigned_tasks = []
    if action == "accept" and mentorship_request.mentor_type == "anchor":
        mentorship_request.supervisor_status = "approved"
        mentorship_request.final_status = "approved"
        if mentorship_request.duration_months == 12:
            try:
                assigned_tasks = assign_master_tasks_to_mentorship(mentorship_request)
            except Exception as e:
                print(f"Task assignment error for anchor mentor: {e}")

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("DB Commit Error:", e)
        if is_ajax:
            return jsonify({"success": False, "message": "Something went wrong."}), 500
        flash("Something went wrong while updating the request.", "error")
        return redirect(url_for("mentordashboard"))

    # Notify the mentee about the mentor's response
    if mentorship_request.mentee:
        if action == "accept":
            if assigned_tasks:
                create_notification(
                    mentorship_request.mentee.id,
                    f"Anchor mentor ({mentor.name}) accepted your request. {len(assigned_tasks)} tasks have been assigned.",
                    url_for("my_mentors")
                )
            else:
                create_notification(
                    mentorship_request.mentee.id,
                    f"A mentor ({mentor.name}) accepted your mentorship request.",
                    url_for("my_mentors")
                )
        else:
            create_notification(
                mentorship_request.mentee.id,
                f"Your mentorship request to {mentor.name} was not accepted.",
                url_for("my_mentors")
            )

    if is_ajax:
        return jsonify({"success": True, "message": f"Request {action}ed successfully!"})

    flash(f"Request {action}ed successfully!", "success")

    # For anchor mentorships, also send connection notifications and emails
    if action == "accept" and mentorship_request.mentor_type == "anchor":
        notify_mentorship_connection(mentorship_request)
        send_mentorship_connected_email(mentorship_request)

    return redirect(url_for("mentor_mentorship_request"))

#--------------x----- PROFILE PICTURE AT TOP ------------------
@app.context_processor
def inject_user_profile_pic():
    if "email" in session:
        user = User.query.filter_by(email=session["email"]).first()
        profile_pic = None
        if user:
            if session.get("user_type") == "1":  # Mentor
                profile = MentorProfile.query.filter_by(user_id=user.id).first()
                profile_pic = profile.profile_picture if profile else None
            elif session.get("user_type") == "2":  # Mentee
                profile = MenteeProfile.query.filter_by(user_id=user.id).first()
                profile_pic = profile.profile_picture if profile else None
            elif session.get("user_type") == "0":  # Supervisor
                profile = SupervisorProfile.query.filter_by(user_id=user.id).first()
                profile_pic = profile.profile_picture if profile else None
            elif session.get("user_type") == "3":  # Institution
                profile = Institution.query.filter_by(user_id=user.id).first()
                profile_pic = profile.profile_picture if profile else None
        return dict(current_user_profile_pic=profile_pic)
    return dict(current_user_profile_pic=None)

@app.context_processor
def inject_notifications():
    """Provide unread notification count + latest notifications to every template."""
    if "email" not in session:
        return dict(unread_notifications=0, latest_notifications=[])
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return dict(unread_notifications=0, latest_notifications=[])
    unread_count = Notification.query.filter_by(user_id=user.id, is_read=False).count()
    latest = Notification.query.filter_by(user_id=user.id).order_by(
        Notification.created_at.desc()
    ).limit(5).all()
    return dict(unread_notifications=unread_count, latest_notifications=latest)

@app.route("/notifications")
def notifications_page():
    if "email" not in session:
        return redirect(url_for("signin"))
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("signin"))
    all_notifications = Notification.query.filter_by(user_id=user.id).order_by(
        Notification.created_at.desc()
    ).all()
    return render_template(
        "notifications.html",
        notifications=all_notifications,
        show_sidebar=True
    )

@app.route("/notifications/read_all", methods=["POST"])
def notifications_read_all():
    if "email" not in session:
        return jsonify({"success": False}), 401
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return jsonify({"success": False}), 401
    try:
        Notification.query.filter_by(user_id=user.id, is_read=False).update({"is_read": True})
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        print("Mark read error:", e)
        return jsonify({"success": False}), 500

@app.route("/editmentorprofile", methods=["GET", "POST"])
def editmentorprofile():
    if "email" not in session or session.get("user_type") != "1":
        return redirect(url_for("signin"))

    # Current user
    user = User.query.filter_by(email=session["email"]).first()
    profile = MentorProfile.query.filter_by(user_id=user.id).first()
    
    # Get institutions for dropdown
    institutions = Institution.query.filter_by(status="active").all()

    if request.method == "POST":
        # Create profile if not exists
        if not profile:
            profile = MentorProfile(user_id=user.id)
            db.session.add(profile)

        # No mandatory fields validation - mentor can save partial profile

        # Update institution if changed
        new_institution = request.form.get("institution")

        if new_institution and new_institution != user.institution:
            user.institution = new_institution
            db.session.add(user)

        if new_institution == "Other":
            other_institution = request.form.get("other_institution_name")
            if other_institution:
                user.institution = other_institution
                db.session.add(user)

       # Save form data to mentor profile
        # Handle "Other" option for profession
        profession = request.form.get("profession")
        if profession == "Other":
            other_profession = request.form.get("other_profession")
            profile.profession = other_profession if other_profession else profession
        else:
            profile.profession = profession
        
        profile.skills = request.form.get("skills")
        profile.role = request.form.get("role")
        
        # Handle "Other" option for industry_sector
        industry_sector = request.form.get("industry_sector")
        if industry_sector == "Other":
            other_industry_sector = request.form.get("other_industry_sector")
            profile.industry_sector = other_industry_sector if other_industry_sector else industry_sector
        else:
            profile.industry_sector = industry_sector
        
        profile.organisation = request.form.get("organisation")
        profile.years_of_experience = request.form.get("years_of_experience")
        
        # Handle WhatsApp with country code - combine them
        whatsapp_country_code = request.form.get("whatsapp_country_code", "+1")
        whatsapp_number = request.form.get("whatsapp")
        if whatsapp_number:
            # Combine country code and number
            profile.whatsapp = f"{whatsapp_country_code} {whatsapp_number}"
        else:
            profile.whatsapp = None
        
        # Handle "Other" option for country
        country = request.form.get("country")
        if country == "Other":
            other_country = request.form.get("other_country")
            country = other_country if other_country else country
        
        city = request.form.get("city")
        profile.location = f"{city}, {country}" if city and country else city or country
        
        # Handle multiple language selection with "Other" option
        languages = request.form.getlist("language")
        other_language = request.form.get("other_language")
        if "Other" in languages and other_language:
            languages = [lang for lang in languages if lang != "Other"]
            languages.append(other_language)
        profile.language = ", ".join(languages) if languages else None
        
        # Social links
        profile.linkedin_link = request.form.get("linkedin_link")
        profile.github_link = request.form.get("github_link")
        profile.portfolio_link = request.form.get("portfolio_link")
        profile.other_social_link = request.form.get("other_social_link")
        
        # Mentorship preferences
        mentorship_topics = request.form.getlist("mentorship_topics")
        profile.mentorship_topics = ", ".join(mentorship_topics) if mentorship_topics else None
        
        mentorship_types = request.form.getlist("mentorship_type_preference")
        profile.mentorship_type_preference = ", ".join(mentorship_types) if mentorship_types else None
        
        profile.preferred_communication = request.form.get("preferred_communication")
        profile.availability = request.form.get("availability")
        profile.connect_frequency = request.form.get("connect_frequency")
        profile.preferred_duration = request.form.get("preferred_duration")
        
        # Mentor philosophy
        profile.why_mentor = request.form.get("why_mentor")
        profile.mentorship_philosophy = request.form.get("mentorship_philosophy")
        profile.mentorship_motto = request.form.get("mentorship_motto")
        
        profile.additional_info = request.form.get("additional_info")

        # Educational Information
        profile.highest_qualification = request.form.get("highest_qualification")
        profile.degree_name = request.form.get("degree_name")
        profile.field_of_study = request.form.get("field_of_study")
        profile.university_name = request.form.get("university_name")
        profile.graduation_year = request.form.get("graduation_year")
        profile.academic_status = request.form.get("academic_status")
        profile.certifications = request.form.get("certifications")
        profile.research_work = request.form.get("research_work")
        
        # Set education field (legacy field) based on new educational fields
        # This ensures backward compatibility with the old field
        if profile.highest_qualification or profile.degree_name:
            education_parts = []
            if profile.degree_name:
                education_parts.append(profile.degree_name)
            if profile.field_of_study:
                education_parts.append(f"in {profile.field_of_study}")
            if profile.highest_qualification:
                education_parts.append(f"({profile.highest_qualification})")
            profile.education = " ".join(education_parts) if education_parts else "Not specified"
        else:
            profile.education = "Not specified"

        # Handle profile picture upload
        file = request.files.get("profile_picture")
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            profile.profile_picture = filename

        # Handle criminal certificate upload (PDF only)
        criminal_cert_file = request.files.get("criminal_certificate")
        if criminal_cert_file and criminal_cert_file.filename:
            if criminal_cert_file.filename.lower().endswith('.pdf'):
                cert_filename = secure_filename(criminal_cert_file.filename)
                # Add timestamp to avoid filename conflicts
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                cert_filename = f"criminal_cert_{user.id}_{timestamp}_{cert_filename}"
                criminal_cert_file.save(os.path.join(app.config["UPLOAD_FOLDER"], cert_filename))
                profile.criminal_certificate = cert_filename
                print(f"✅ Criminal certificate uploaded: {cert_filename}")
            else:
                flash("Criminal Certificate must be a PDF file", "error")
                return redirect(url_for("editmentorprofile"))

        try:
            db.session.commit()
            # Clear any saved form data from session on successful save
            session.pop('mentor_form_data', None)
            flash("✅ Profile updated successfully!", "success")
            print("✅ Database commit successful!")
            return redirect(url_for("mentorprofile"))
        except Exception as e:
            db.session.rollback()
            flash(f"❌ Error updating profile: {str(e)}", "error")
            print(f"❌ Database commit failed: {str(e)}")

    # GET request – pre-fill form with existing data
    # Check if there's saved form data from failed validation
    form_data = session.pop('mentor_form_data', None)
    
    # Parse location to get city and country separately
    location = profile.location if profile else ""
    city = ""
    country = ""
    if location and ", " in location:
        parts = location.split(", ", 1)
        city = parts[0]
        country = parts[1] if len(parts) > 1 else ""
    else:
        city = location
    
    # Parse WhatsApp to get country code and number separately
    whatsapp_full = profile.whatsapp if profile else ""
    whatsapp_country_code = "+1"  # Default
    whatsapp_number = ""
    
    if whatsapp_full:
        # Try to split by space to separate country code and number
        parts = whatsapp_full.split(" ", 1)
        if len(parts) == 2 and parts[0].startswith("+"):
            whatsapp_country_code = parts[0]
            whatsapp_number = parts[1]
        else:
            # If no space or doesn't start with +, treat entire string as number
            whatsapp_number = whatsapp_full
    
    # Use form_data if available (from failed validation), otherwise use profile data
    return render_template(
        "mentor/editmentorprofile.html",
        full_name=user.name,
        email=user.email,
        institution=form_data.get('institution') if form_data else user.institution,
        institutions=institutions,
        profession=form_data.get('profession') if form_data else (profile.profession if profile else ""),
        other_profession=form_data.get('other_profession') if form_data else "",
        skills=form_data.get('skills') if form_data else (profile.skills if profile else ""),
        role=form_data.get('role') if form_data else (profile.role if profile else ""),
        industry_sector=form_data.get('industry_sector') if form_data else (profile.industry_sector if profile else ""),
        other_industry_sector=form_data.get('other_industry_sector') if form_data else "",
        organisation=form_data.get('organisation') if form_data else (profile.organisation if profile else ""),
        years_of_experience=form_data.get('years_of_experience') if form_data else (profile.years_of_experience if profile else ""),
        whatsapp=form_data.get('whatsapp') if form_data else whatsapp_number,
        whatsapp_country_code=form_data.get('whatsapp_country_code') if form_data else whatsapp_country_code,
        location=location,
        city=form_data.get('city') if form_data else city,
        country=form_data.get('country') if form_data else country,
        other_country=form_data.get('other_country') if form_data else "",
        education=profile.education if profile else "",
        language=", ".join(form_data.get('language', [])) if form_data else (profile.language if profile else ""),
        other_language=form_data.get('other_language') if form_data else "",
        linkedin_link=form_data.get('linkedin_link') if form_data else (profile.linkedin_link if profile else ""),
        github_link=form_data.get('github_link') if form_data else (profile.github_link if profile else ""),
        portfolio_link=form_data.get('portfolio_link') if form_data else (profile.portfolio_link if profile else ""),
        other_social_link=form_data.get('other_social_link') if form_data else (profile.other_social_link if profile else ""),
        mentorship_topics=", ".join(form_data.get('mentorship_topics', [])) if form_data else ((profile.mentorship_topics or "") if profile else ""),
        mentorship_type_preference=", ".join(form_data.get('mentorship_type_preference', [])) if form_data else ((profile.mentorship_type_preference or "") if profile else ""),
        preferred_communication=form_data.get('preferred_communication') if form_data else (profile.preferred_communication if profile else ""),
        availability=form_data.get('availability') if form_data else (profile.availability if profile else ""),
        connect_frequency=form_data.get('connect_frequency') if form_data else (profile.connect_frequency if profile else ""),
        preferred_duration=form_data.get('preferred_duration') if form_data else (profile.preferred_duration if profile else ""),
        why_mentor=form_data.get('why_mentor') if form_data else (profile.why_mentor if profile else ""),
        mentorship_philosophy=form_data.get('mentorship_philosophy') if form_data else (profile.mentorship_philosophy if profile else ""),
        mentorship_motto=form_data.get('mentorship_motto') if form_data else (profile.mentorship_motto if profile else ""),
        additional_info=form_data.get('additional_info') if form_data else (profile.additional_info if profile else ""),
        profile_picture=profile.profile_picture if profile else None,
        criminal_certificate=profile.criminal_certificate if profile else None,
        # Educational Information
        highest_qualification=form_data.get('highest_qualification') if form_data else (profile.highest_qualification if profile else ""),
        degree_name=form_data.get('degree_name') if form_data else (profile.degree_name if profile else ""),
        field_of_study=form_data.get('field_of_study') if form_data else (profile.field_of_study if profile else ""),
        university_name=form_data.get('university_name') if form_data else (profile.university_name if profile else ""),
        graduation_year=form_data.get('graduation_year') if form_data else (profile.graduation_year if profile else ""),
        academic_status=form_data.get('academic_status') if form_data else (profile.academic_status if profile else ""),
        certifications=form_data.get('certifications') if form_data else (profile.certifications if profile else ""),
        research_work=form_data.get('research_work') if form_data else (profile.research_work if profile else "")
    )


#-----------------edit mentee profile-------------------
@app.route("/editmenteeprofile", methods=["GET", "POST"])
def editmenteeprofile():
    if "email" not in session or session.get("user_type") != "2":
        return redirect(url_for("signin"))

    # Current user
    user = User.query.filter_by(email=session["email"]).first()
    profile = MenteeProfile.query.filter_by(user_id=user.id).first()
    
    # Get institutions for dropdown
    institutions = Institution.query.filter_by(status="active").all()

    if request.method == "POST":
        # Check if this is an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
                  request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html
        
        # Get "Who am I?" selection
        who_am_i = request.form.get("who_am_i", "").strip()
        
        # Validate "Who am I?" is selected
        if not who_am_i:
            error_msg = "Please select 'Who am I?'"
            if is_ajax:
                return jsonify({"success": False, "message": error_msg}), 400
            flash(error_msg, "error")
            return redirect(url_for("editmenteeprofile"))
        
        # Define mandatory fields for each category
        mandatory_fields_by_category = {
            'school_student': ['school_name'],
            'university_student': ['institution_name'],
            'seeking_internship': ['institution_name'],
            'young_professional': ['current_role', 'industry', 'years_experience', 'current_organization'],
            'exploring': ['last_role', 'restart_field', 'support_expected']
        }
        
        # Common mandatory fields for all categories
        common_mandatory = ['mobile_number', 'mentorship_expectations', 'institution']
        
        # General details mandatory fields
        general_details_mandatory = ['city', 'state', 'country', 'institution']
        
        # Validate common mandatory fields
        missing_fields = []
        for field in common_mandatory:
            value = request.form.get(field, "").strip()
            if not value:
                missing_fields.append(field.replace('_', ' ').title())
        
        # Validate general details mandatory fields
        for field in general_details_mandatory:
            value = request.form.get(field, "").strip()
            if not value:
                missing_fields.append(field.replace('_', ' ').title())
        
        # Validate terms agreement
        if not request.form.get('terms_agreement'):
            missing_fields.append('Terms & Conditions Agreement')
        
        # Validate GDPR agreement
        if not request.form.get('gdpr_agreement'):
            missing_fields.append('GDPR Agreement')
        
        # Validate profile picture (only if no existing picture)
        if not profile or not profile.profile_picture:
            if 'profile_picture' not in request.files or not request.files['profile_picture'].filename:
                missing_fields.append('Profile Picture')
        
        # Validate category-specific mandatory fields (ONLY for selected category)
        category_fields = mandatory_fields_by_category.get(who_am_i, [])
        for field in category_fields:
            value = request.form.get(field, "").strip()
            if not value:
                missing_fields.append(field.replace('_', ' ').title())
        
        # If validation fails, show error
        if missing_fields:
            error_msg = f"Please fill all mandatory fields: {', '.join(missing_fields)}"
            if is_ajax:
                return jsonify({"success": False, "message": error_msg, "missing_fields": missing_fields}), 400
            flash(error_msg, "error")
            return redirect(url_for("editmenteeprofile"))
        
        # Create profile if not exists
        if not profile:
            profile = MenteeProfile(user_id=user.id)
            db.session.add(profile)

        # Save common fields
        profile.who_am_i = who_am_i
        profile.dob = request.form.get("dob")
        
        # Check if mentee is under 18 and handle parent consent
        parent_email = request.form.get("parent_email", "").strip()
        if profile.dob and is_under_18(profile.dob):
            # Mentee is under 18, parent consent required
            if parent_email:
                profile.parent_email = parent_email
                
                # Generate consent token if not already generated
                if not profile.parent_consent_token:
                    profile.parent_consent_token = generate_consent_token()
                    profile.parent_consent_status = "pending"
                    
                    # Send consent email to parent
                    parent_name = request.form.get("parent_name", "Parent/Guardian")
                    print(f"🔔 Attempting to send parent consent email to: {parent_email}")
                    print(f"   Parent Name: {parent_name}")
                    print(f"   Mentee Name: {user.name}")
                    print(f"   Token: {profile.parent_consent_token}")
                    
                    email_sent = send_parent_consent_email(
                        parent_email=parent_email,
                        parent_name=parent_name,
                        mentee_name=user.name,
                        consent_token=profile.parent_consent_token
                    )
                    
                    if email_sent:
                        print(f"✅ Parent consent email sent successfully to {parent_email}")
                    else:
                        print(f"❌ Failed to send parent consent email to {parent_email}")
        else:
            # Mentee is 18 or older, auto-approve
            profile.parent_consent_status = "approved"
        
        profile.mobile_number = request.form.get("mobile_number")
        profile.mobile_country_code = request.form.get("mobile_country_code", "+1")
        profile.whatsapp_number = request.form.get("whatsapp_number")
        profile.whatsapp_country_code = request.form.get("whatsapp_country_code", "+1")
        profile.parent_mobile = request.form.get("parent_mobile")
        profile.parent_mobile_country_code = request.form.get("parent_mobile_country_code", "+1")
        profile.school_college_name = request.form.get("school_college_name")
        profile.stream = request.form.get("stream")
        profile.goal = request.form.get("goal")
        profile.mentorship_expectations = request.form.get("mentorship_expectations")
        profile.linkedin_link = request.form.get("linkedin_link")
        # Save "Yes" only if both terms and GDPR are agreed
        terms_agreed = request.form.get("terms_agreement")
        gdpr_agreed = request.form.get("gdpr_agreement")
        profile.terms_agreement = "Yes" if (terms_agreed and gdpr_agreed) else "No"
        
        # Save general details
        profile.father_name = request.form.get("father_name")
        profile.parent_name = request.form.get("parent_name")
        profile.comments = request.form.get("comments")
        profile.address_line1 = request.form.get("address_line1")
        profile.address_line2 = request.form.get("address_line2")
        profile.city = request.form.get("city")
        profile.state = request.form.get("state")
        profile.postal_code = request.form.get("postal_code")
        profile.country = request.form.get("country")
        
        # Save institution field
        institution_value = request.form.get("institution")
        profile.institution = institution_value
        if institution_value == "Other":
            profile.institution_other = request.form.get("institution_other")
        else:
            profile.institution_other = None

        # SCHOOL STUDENT fields
        if who_am_i == "school_student":
            profile.school_name = request.form.get("school_name")
            profile.class_year = request.form.get("class_year")
            profile.school_board = request.form.get("school_board")
            profile.course_stream = request.form.get("course_stream")
            profile.favourite_subject = request.form.get("favourite_subject")
            profile.career_interest = request.form.get("career_interest")
            profile.govt_private = request.form.get("govt_private")

        # UNIVERSITY STUDENT fields
        elif who_am_i == "university_student":
            profile.institution_name = request.form.get("institution_name")
            profile.education_level = request.form.get("education_level")
            profile.course_stream = request.form.get("course_stream")
            profile.class_year = request.form.get("class_year")
            profile.favourite_subject = request.form.get("favourite_subject")
            profile.career_interest = request.form.get("career_interest")

        # SEEKING INTERNSHIP fields
        elif who_am_i == "seeking_internship":
            profile.education_level = request.form.get("education_level")
            profile.course_stream = request.form.get("course_stream")
            profile.institution_name = request.form.get("institution_name")
            profile.career_interest = request.form.get("career_interest")
            profile.key_skills = request.form.get("key_skills")
            profile.career_goal = request.form.get("career_goal")

        # YOUNG PROFESSIONAL fields
        elif who_am_i == "young_professional":
            profile.current_role = request.form.get("current_role")
            profile.industry = request.form.get("industry")
            profile.years_experience = request.form.get("years_experience")
            profile.current_organization = request.form.get("current_organization")
            profile.key_skills = request.form.get("key_skills")
            profile.career_goal = request.form.get("career_goal")

        # EXPLORING fields
        elif who_am_i == "exploring":
            profile.education_level = request.form.get("education_level")
            profile.last_role = request.form.get("last_role")
            profile.career_interest = request.form.get("career_interest")
            profile.restart_field = request.form.get("restart_field")
            profile.support_expected = request.form.get("support_expected")

        # Handle profile picture upload
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"mentee_{profile.id}_{file.filename}")
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                profile.profile_picture = filename

        db.session.commit()
        
        # Check if parent consent email was sent
        parent_consent_sent = False
        if profile.dob and is_under_18(profile.dob) and profile.parent_consent_status == "pending":
            parent_consent_sent = True
        
        # Return JSON response for AJAX requests
        if is_ajax:
            message = "Mentee profile updated successfully!"
            if parent_consent_sent:
                message += " A consent email has been sent to your parent/guardian."
            return jsonify({
                "success": True, 
                "message": message,
                "redirect_url": url_for("menteeprofile"),
                "parent_consent_sent": parent_consent_sent
            }), 200
        
        # Traditional response for non-AJAX requests
        flash("Mentee profile updated successfully!", "success")
        if parent_consent_sent:
            flash("A consent email has been sent to your parent/guardian. You need their approval before connecting with mentors.", "info")
        return redirect(url_for("menteeprofile"))

    # GET request – pre-fill form with existing data
    return render_template(
        "mentee/editmenteeprofile.html",
        full_name=user.name,
        email=user.email,
        institutions=institutions,
        dob=profile.dob if profile else "",
        mobile_number=profile.mobile_number if profile else "",
        mobile_country_code=profile.mobile_country_code if profile and profile.mobile_country_code else "+1",
        whatsapp_number=profile.whatsapp_number if profile else "",
        whatsapp_country_code=profile.whatsapp_country_code if profile and profile.whatsapp_country_code else "+1",
        who_am_i=profile.who_am_i if profile and profile.who_am_i else None,
        # General details
        father_name=profile.father_name if profile else "",
        parent_name=profile.parent_name if profile else "",
        parent_email=profile.parent_email if profile else "",
        address_line1=profile.address_line1 if profile else "",
        address_line2=profile.address_line2 if profile else "",
        city=profile.city if profile else "",
        state=profile.state if profile else "",
        postal_code=profile.postal_code if profile else "",
        country=profile.country if profile else "",
        institution=profile.institution if profile else "",
        institution_other=profile.institution_other if profile else "",
        # New common fields
        parent_mobile=profile.parent_mobile if profile else "",
        parent_mobile_country_code=profile.parent_mobile_country_code if profile and profile.parent_mobile_country_code else "+1",
        school_college_name=profile.school_college_name if profile else "",
        stream=profile.stream if profile else "",
        goal=profile.goal if profile else "",
        govt_private=profile.govt_private if profile else "",
        # Other fields
        education_level=profile.education_level if profile else "",
        institution_name=profile.institution_name if profile else "",
        board_university=profile.board_university if profile else "",
        course_stream=profile.course_stream if profile else "",
        class_year=profile.class_year if profile else "",
        favourite_subject=profile.favourite_subject if profile else "",
        career_interest=profile.career_interest if profile else "",
        school_name=profile.school_name if profile else "",
        school_board=profile.school_board if profile else "",
        school_passing_year=profile.school_passing_year if profile else "",
        current_role=profile.current_role if profile else "",
        industry=profile.industry if profile else "",
        years_experience=profile.years_experience if profile else "",
        current_organization=profile.current_organization if profile else "",
        key_skills=profile.key_skills if profile else "",
        career_goal=profile.career_goal if profile else "",
        startup_stage=profile.startup_stage if profile else "",
        startup_name=profile.startup_name if profile else "",
        startup_industry=profile.startup_industry if profile else "",
        team_size=profile.team_size if profile else "",
        main_challenge=profile.main_challenge if profile else "",
        mentorship_type=profile.mentorship_type if profile else "",
        freelance_skill=profile.freelance_skill if profile else "",
        freelance_experience=profile.freelance_experience if profile else "",
        freelance_platforms=profile.freelance_platforms if profile else "",
        freelance_challenge=profile.freelance_challenge if profile else "",
        last_role=profile.last_role if profile else "",
        career_break_reason=profile.career_break_reason if profile else "",
        restart_field=profile.restart_field if profile else "",
        support_expected=profile.support_expected if profile else "",
        mentorship_expectations=profile.mentorship_expectations if profile else "",
        linkedin_link=profile.linkedin_link if profile else "",
        terms_agreement=profile.terms_agreement if profile else "",
        profile_picture=profile.profile_picture if profile else None
    )

@app.route("/edit_supervisor_profile", methods=["GET", "POST"])
def editsupervisorprofile():
    if "email" not in session or session.get("user_type") != "0":  
        return redirect(url_for("signin"))

    user = User.query.filter_by(email=session["email"]).first()
    profile = SupervisorProfile.query.filter_by(user_id=user.id).first()
    
    # Get institutions for dropdown
    institutions = Institution.query.filter_by(status="active").all()

    if request.method == "POST":
        if not profile:
            profile = SupervisorProfile(user_id=user.id)
            db.session.add(profile)

        # Validate all mandatory fields
        mandatory_fields = {
            "organisation_or_college": request.form.get("organisation_or_college"),
            "whatsapp_number": request.form.get("whatsapp_number"),
            "location": request.form.get("location"),
            "role": request.form.get("role"),
            "additional_info": request.form.get("additional_info"),
        }
        
        # Check for empty fields
        missing_fields = []
        for field_name, field_value in mandatory_fields.items():
            if not field_value:
                missing_fields.append(field_name.replace("_", " ").title())
        
        if missing_fields:
            flash(f"Please fill all mandatory fields: {', '.join(missing_fields)}", "error")
            return redirect(url_for("editsupervisorprofile"))

        # Update institution if changed
        new_institution = request.form.get("institution")
        if new_institution and new_institution != user.institution:
            user.institution = new_institution
            db.session.add(user)

        profile.organisation = request.form.get("organisation_or_college")
        profile.whatsapp = request.form.get("whatsapp_number")
        profile.location = request.form.get("location")
        profile.role = request.form.get("role")
        profile.additional_info = request.form.get("additional_info")

        # Profile picture handling
        file = request.files.get("profile_picture")
        if file and allowed_file(file.filename):
            filename = f"{user.id}_{int(datetime.now().timestamp())}{secure_filename(file.filename)}"
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            profile.profile_picture = filename
            
        db.session.add(profile)
        db.session.commit()
        flash("Profile updated successfully!", "success")
        return redirect(url_for("supervisorprofile"))

    return render_template(
        "supervisor/editsupervisorprofile.html",
        full_name=user.name,
        email=user.email,
        institution=user.institution,  # Pass current institution
        institutions=institutions,     # Pass institutions list
        organisation_or_college=profile.organisation if profile else "",
        whatsapp_number=profile.whatsapp if profile else "",
        location=profile.location if profile else "",
        role=profile.role if profile else "",
        additional_info=profile.additional_info if profile else "",
        profile_picture=profile.profile_picture if profile else None
    )

# Remove duplicate code below


# ------------------ PROFILE ------------------
@app.route("/profile")
def profile():
    if "email" not in session:
        return redirect(url_for("signin"))

    user_type = session.get("user_type")
    
    if user_type == "1":
        return redirect(url_for("mentorprofile"))
    elif user_type == "2":
        return redirect(url_for("menteeprofile"))
    elif user_type == "0":
        return redirect(url_for("supervisorprofile"))
    elif user_type == "3":
        return redirect(url_for("institutionprofile"))

# ------------------ CERTIFICATE ------------------
@app.route("/my_certificate")
def my_certificate():
    """Generate and display user certificate"""
    if "email" not in session:
        flash("Please login first!", "error")
        return redirect(url_for("signin"))
    
    # Get current user
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        flash("User not found!", "error")
        return redirect(url_for("signin"))
    
    # Format registration date
    if user.created_at:
        registration_date = user.created_at.strftime("%B %d, %Y")
    elif user.oauth_created_at:
        registration_date = user.oauth_created_at.strftime("%B %d, %Y")
    else:
        registration_date = "Registration date not available"
    
    user_type = session.get("user_type")
    
    # Build selectable data lists
    connections_list = []
    sessions_list = []
    tasks_list = []
    
    if user_type == "1":  # Mentor
        # Active mentees
        active_mentorships = MentorshipRequest.query.filter_by(
            mentor_id=user.id, final_status="approved"
        ).all()
        for mr in active_mentorships:
            mentee = User.query.get(mr.mentee_id)
            if mentee:
                connections_list.append({
                    "id": mr.id,
                    "name": mentee.name,
                    "type": "mentee"
                })
        
        # Sessions
        sessions = MeetingRequest.query.filter_by(
            requested_to_id=user.id, status="approved"
        ).all()
        for s in sessions:
            requester = User.query.get(s.requester_id)
            session_date = s.date.strftime("%b %d, %Y") if s.date else "TBD"
            sessions_list.append({
                "id": s.id,
                "title": s.title or "Meeting",
                "date": session_date,
                "with": requester.name if requester else "Unknown"
            })
        
        # Tasks
        mentee_tasks = MenteeTask.query.filter_by(mentor_id=user.id).all()
        for t in mentee_tasks:
            mentee = User.query.get(t.mentee_id)
            task_name = t.master_task.purpose_of_call if t.master_task else f"Task #{t.meeting_number}"
            tasks_list.append({
                "id": t.id,
                "title": task_name,
                "status": compute_task_progress_status("master", t.id, t.mentee_id, t.mentor_id),
                "with": mentee.name if mentee else "Unknown"
            })
        
        personal_tasks = PersonalTask.query.filter_by(mentor_id=user.id).all()
        for t in personal_tasks:
            tasks_list.append({
                "id": f"p{t.id}",
                "title": t.title,
                "status": compute_task_progress_status("personal", t.id, t.mentee_id, t.mentor_id or None),
                "with": "Personal"
            })
        
        connected_label = "Active Mentees"
        sessions_label = "Sessions Conducted"
        
    elif user_type == "2":  # Mentee
        # Active mentors
        active_mentorships = MentorshipRequest.query.filter_by(
            mentee_id=user.id, final_status="approved"
        ).all()
        for mr in active_mentorships:
            mentor = User.query.get(mr.mentor_id)
            if mentor:
                connections_list.append({
                    "id": mr.id,
                    "name": mentor.name,
                    "type": "mentor"
                })
        
        # Sessions
        sessions = MeetingRequest.query.filter_by(
            requester_id=user.id, status="approved"
        ).all()
        for s in sessions:
            target = User.query.get(s.requested_to_id)
            session_date = s.date.strftime("%b %d, %Y") if s.date else "TBD"
            sessions_list.append({
                "id": s.id,
                "title": s.title or "Meeting",
                "date": session_date,
                "with": target.name if target else "Unknown"
            })
        
        # Tasks
        mentee_tasks = MenteeTask.query.filter_by(mentee_id=user.id).all()
        for t in mentee_tasks:
            mentor = User.query.get(t.mentor_id)
            task_name = t.master_task.purpose_of_call if t.master_task else f"Task #{t.meeting_number}"
            tasks_list.append({
                "id": t.id,
                "title": task_name,
                "status": compute_task_progress_status("master", t.id, t.mentee_id, t.mentor_id),
                "with": mentor.name if mentor else "Unknown"
            })
        
        personal_tasks = PersonalTask.query.filter_by(mentee_id=user.id).all()
        for t in personal_tasks:
            tasks_list.append({
                "id": f"p{t.id}",
                "title": t.title,
                "status": compute_task_progress_status("personal", t.id, t.mentee_id, t.mentor_id or None),
                "with": "Personal"
            })
        
        connected_label = "Active Mentors"
        sessions_label = "Sessions Attended"
    else:
        connected_label = ""
        sessions_label = ""
    
    # Mentorship stats (for backward compat)
    mentorship_stats = {
        "connected_count": len(connections_list),
        "connected_type": connected_label,
        "sessions_count": len(sessions_list),
        "sessions_type": sessions_label
    }
    
    # Task stats
    completed_tasks = sum(1 for t in tasks_list if t["status"] == "completed")
    in_progress_tasks = sum(1 for t in tasks_list if t["status"] == "in-progress")
    task_stats = {
        "total": len(tasks_list),
        "completed": completed_tasks,
        "in_progress": in_progress_tasks,
        "pending": len(tasks_list) - completed_tasks - in_progress_tasks
    }

    # Detailed mentorship info for page 2
    mentorship_details = []
    if user_type == "1":
        for mr in active_mentorships:
            mentee = User.query.get(mr.mentee_id)
            mentorship_details.append({
                "id": mr.id,
                "partner": mentee.name if mentee else "Unknown",
                "purpose": mr.purpose or "N/A",
                "mentor_type": (mr.mentor_type or "N/A").capitalize(),
                "term": ("Long-term" if mr.term == "long" else "Short-term") if mr.term else "N/A",
                "duration": f"{mr.duration_months} months" if mr.duration_months else "N/A",
                "status": (mr.final_status or "pending").capitalize(),
                "started": mr.created_at.strftime("%b %d, %Y") if mr.created_at else "N/A"
            })
    elif user_type == "2":
        for mr in active_mentorships:
            mentor = User.query.get(mr.mentor_id)
            mentorship_details.append({
                "id": mr.id,
                "partner": mentor.name if mentor else "Unknown",
                "purpose": mr.purpose or "N/A",
                "mentor_type": (mr.mentor_type or "N/A").capitalize(),
                "term": ("Long-term" if mr.term == "long" else "Short-term") if mr.term else "N/A",
                "duration": f"{mr.duration_months} months" if mr.duration_months else "N/A",
                "status": (mr.final_status or "pending").capitalize(),
                "started": mr.created_at.strftime("%b %d, %Y") if mr.created_at else "N/A"
            })

    # Task ratings for page 2
    task_ratings = []
    if user_type == "1":
        ratings = TaskRating.query.filter_by(mentor_id=user.id).all()
    elif user_type == "2":
        ratings = TaskRating.query.filter_by(mentee_id=user.id).all()
    else:
        ratings = []
    for r in ratings:
        mentee_user = User.query.get(r.mentee_id)
        mentor_user = User.query.get(r.mentor_id)
        stars = "★" * r.rating + "☆" * (5 - r.rating)
        task_ratings.append({
            "task_id": r.task_id,
            "task_type": r.task_type,
            "mentee": mentee_user.name if mentee_user else "Unknown",
            "mentor": mentor_user.name if mentor_user else "Unknown",
            "rating": r.rating,
            "stars": stars,
            "feedback": r.feedback or "—",
            "strengths": r.strengths or "—",
            "improvements": r.improvements or "—",
            "rated_at": r.rated_at.strftime("%b %d, %Y") if r.rated_at else "N/A"
        })

    # Determine back URL
    if user_type == "1":
        back_url = url_for("mentordashboard")
    elif user_type == "2":
        back_url = url_for("menteedashboard")
    elif user_type == "0":
        back_url = url_for("supervisordashboard")
    elif user_type == "3":
        back_url = url_for("institutiondashboard")
    else:
        back_url = url_for("home")
    
    return render_template(
        "certificate.html",
        user_name=user.name,
        user_type=user.user_type,
        user_id=user.id,
        registration_date=registration_date,
        mentorship_stats=mentorship_stats,
        task_stats=task_stats,
        connections_list=connections_list,
        sessions_list=sessions_list,
        tasks_list=tasks_list,
        mentorship_details=mentorship_details,
        task_ratings=task_ratings,
        back_url=back_url
    )

# --------- CHANGE PASSWORD ROUTE ---------
@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if "email" not in session:
        flash("Please login first!", "error")
        return redirect(url_for("signin"))
    
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        
        # Get current user
        user = User.query.filter_by(email=session["email"]).first()
        
        if not user:
            flash("User not found!", "error")
            return redirect(url_for("change_password"))
        
        # Verify current password
        if not check_password_hash(user.password, current_password):
            flash("Current password is incorrect!", "error")
            return redirect(url_for("change_password"))
        
        # Check if new passwords match
        if new_password != confirm_password:
            flash("New passwords do not match!", "error")
            return redirect(url_for("change_password"))
        
        # Check if new password is same as current
        if check_password_hash(user.password, new_password):
            flash("New password must be different from current password!", "error")
            return redirect(url_for("change_password"))
        
        # Update password
        user.password = generate_password_hash(new_password, method='pbkdf2:sha256', salt_length=8)
        db.session.commit()
        
        flash("✅ Password changed successfully!", "success")
        return redirect(url_for("profile"))
    
    return render_template("change_password.html")

#--------------route for all profiles----------------
@app.route("/mentor_profile")
def mentorprofile(): 
    if "email" in session and session.get("user_type") == "1":
        # Fetch current user
        user = User.query.filter_by(email=session["email"]).first()
        profile = MentorProfile.query.filter_by(user_id=user.id).first()

        # Fetch institution details to get its profile picture
        institution_details = None
        if user.institution_id:
            institution_details = Institution.query.filter_by(id=user.institution_id).first()
        elif user.institution:
            institution_details = Institution.query.filter_by(name=user.institution).first()
        
        institution_profile_picture = institution_details.profile_picture if institution_details else None

        # Connected mentees (fully approved requests)
        connected_reqs = MentorshipRequest.query.filter_by(
            mentor_id=user.id,
            
            supervisor_status="approved",
            final_status="approved"
        ).all()
        connected_mentees = [req.mentee for req in connected_reqs if req.mentee]
        connected_mentees_count = len(connected_mentees)

        return render_template(
            "mentor/mentorprofile.html",
            show_sidebar=False,
            full_name=user.name,
            email=user.email,
            institution=user.institution,
            profession=profile.profession if profile else "",
            organisation=profile.organisation if profile else "",
            industry_sector=profile.industry_sector if profile else "",
            role=profile.role if profile else "",
            whatsapp=profile.whatsapp if profile else "",
            location=profile.location if profile else "",
            education=profile.education if profile else "",
            language=profile.language if profile else "",
            availability=profile.availability if profile else "",
            connect_frequency=profile.connect_frequency if profile else "",
            preferred_communication=profile.preferred_communication if profile else "",
            other_social_link=profile.other_social_link if profile else "",
            why_mentor=profile.why_mentor if profile else "",
            additional_info=profile.additional_info if profile else "",
            years_of_experience=profile.years_of_experience if profile else "",
            skills=profile.skills if profile else "",
            linkedin_link=profile.linkedin_link if profile else "",
            github_link=profile.github_link if profile else "",
            portfolio_link=profile.portfolio_link if profile else "",
            mentorship_topics=profile.mentorship_topics if profile else "",
            mentorship_type_preference=profile.mentorship_type_preference if profile else "",
            mentorship_philosophy=profile.mentorship_philosophy if profile else "",
            mentorship_motto=profile.mentorship_motto if profile else "",
            preferred_duration=profile.preferred_duration if profile else "",
            profile_picture=profile.profile_picture if profile else None,
            criminal_certificate=profile.criminal_certificate if profile else None,
            institution_profile_picture=institution_profile_picture,
            # Educational Information
            highest_qualification=profile.highest_qualification if profile else "",
            degree_name=profile.degree_name if profile else "",
            field_of_study=profile.field_of_study if profile else "",
            university_name=profile.university_name if profile else "",
            graduation_year=profile.graduation_year if profile else "",
            academic_status=profile.academic_status if profile else "",
            certifications=profile.certifications if profile else "",
            research_work=profile.research_work if profile else "",
            connected_mentees=connected_mentees,
            connected_mentees_count=connected_mentees_count
        )
    return redirect(url_for("signin"))

@app.route("/mentee_profile")
def menteeprofile():
    if "email" in session and session.get("user_type") == "2":
        user = User.query.filter_by(email=session["email"]).first()
        profile = MenteeProfile.query.filter_by(user_id=user.id).first()

        # Calculate age from DOB
        age = calculate_age(profile.dob if profile else None)

        # Fetch institution details to get its profile picture
        institution_details = None
        if user.institution_id:
            institution_details = Institution.query.filter_by(id=user.institution_id).first()
        elif user.institution:
            institution_details = Institution.query.filter_by(name=user.institution).first()
        
        institution_profile_picture = institution_details.profile_picture if institution_details else None

        # Connected mentors (fully approved requests)
        connected_reqs = MentorshipRequest.query.filter_by(
            mentee_id=user.id,
            
            supervisor_status="approved",
            final_status="approved"
        ).all()
        connected_mentors = [req.mentor for req in connected_reqs if req.mentor]
        connected_mentors_count = len(connected_mentors)

        return render_template(
            "mentee/menteeprofile.html",
            show_sidebar=False,
            full_name=user.name,
            email=user.email,
            institution=user.institution,
            age=age,  # Pass age instead of dob
            dob=profile.dob if profile else "",  # Keep dob for edit form
            profile_picture=profile.profile_picture if profile else None,
            institution_profile_picture=institution_profile_picture,
            # Who am I
            who_am_i=profile.who_am_i if profile else None,
            # Contact Info
            mobile_number=profile.mobile_number if profile else "",
            mobile_country_code=profile.mobile_country_code if profile and profile.mobile_country_code else "+1",
            whatsapp_number=profile.whatsapp_number if profile else "",
            whatsapp_country_code=profile.whatsapp_country_code if profile and profile.whatsapp_country_code else "+1",
            parent_name=profile.parent_name if profile else "",
            parent_mobile=profile.parent_mobile if profile else "",
            parent_mobile_country_code=profile.parent_mobile_country_code if profile and profile.parent_mobile_country_code else "+1",
            # Common fields for all categories
            school_college_name=profile.school_college_name if profile else "",
            stream=profile.stream if profile else "",
            goal=profile.goal if profile else "",
            govt_private=profile.govt_private if profile else "",
            # School Student fields
            school_name=profile.school_name if profile else "",
            class_year=profile.class_year if profile else "",
            school_board=profile.school_board if profile else "",
            course_stream=profile.course_stream if profile else "",
            favourite_subject=profile.favourite_subject if profile else "",
            career_interest=profile.career_interest if profile else "",
            # University Student fields
            institution_name=profile.institution_name if profile else "",
            education_level=profile.education_level if profile else "",
            # Seeking Internship fields
            key_skills=profile.key_skills if profile else "",
            career_goal=profile.career_goal if profile else "",
            # Young Professional fields
            current_role=profile.current_role if profile else "",
            industry=profile.industry if profile else "",
            years_experience=profile.years_experience if profile else "",
            current_organization=profile.current_organization if profile else "",
            # Exploring fields
            last_role=profile.last_role if profile else "",
            restart_field=profile.restart_field if profile else "",
            support_expected=profile.support_expected if profile else "",
            # Common fields
            mentorship_expectations=profile.mentorship_expectations if profile else "",
            comments=profile.comments if profile else "",
            terms_agreement=profile.terms_agreement if profile else "",
            connected_mentors=connected_mentors,
            connected_mentors_count=connected_mentors_count
        )
    return redirect(url_for("signin"))

@app.route("/supervisor_profile")
def supervisorprofile():
    # Ensure user is logged in and is a supervisor
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))

    # Fetch current user
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("signin"))

    # Fetch supervisor profile
    profile = SupervisorProfile.query.filter_by(user_id=user.id).first()

    return render_template(
        "supervisor/supervisorprofile.html",
        show_sidebar=False,
        full_name=user.name,
        email=user.email,
        organisation_or_college=profile.organisation if profile else "",
        whatsapp_number=profile.whatsapp if profile else "",
        location=profile.location if profile else "",
        role=profile.role if profile else "",
        additional_info=profile.additional_info if profile else "",
        profile_picture=profile.profile_picture if profile else None
    )

# View Mentor Profile (for institution admin)
@app.route("/view_mentor_profile/<int:mentor_id>")
def view_mentor_profile(mentor_id):
    # Allow institution admins to view mentor profiles
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))
    
    user = User.query.get(mentor_id)
    if not user or user.user_type != "1":
        flash("Mentor not found!", "error")
        return redirect(url_for("institution_mentors"))
    
    profile = MentorProfile.query.filter_by(user_id=mentor_id).first()
    
    return render_template(
        "mentor/mentorprofile.html",
        show_sidebar=False,
        full_name=user.name,
        email=user.email,
        institution=user.institution,
        profession=profile.profession if profile else "",
        organisation=profile.organisation if profile else "",
        whatsapp=profile.whatsapp if profile else "",
        location=profile.location if profile else "",
        education=profile.education if profile else "",
        language=profile.language if profile else "",
        availability=profile.availability if profile else "",
        connect_frequency=profile.connect_frequency if profile else "",
        preferred_communication=profile.preferred_communication if profile else "",
        other_social_link=profile.other_social_link if profile else "",
        why_mentor=profile.why_mentor if profile else "",
        additional_info=profile.additional_info if profile else "",
        years_of_experience=profile.years_of_experience if profile else "",
        skills=profile.skills if profile else "",
        linkedin_link=profile.linkedin_link if profile else "",
        github_link=profile.github_link if profile else "",
        portfolio_link=profile.portfolio_link if profile else "",
        mentorship_topics=profile.mentorship_topics if profile else "",
        mentorship_type_preference=profile.mentorship_type_preference if profile else "",
        mentorship_philosophy=profile.mentorship_philosophy if profile else "",
        mentorship_motto=profile.mentorship_motto if profile else "",
        profile_picture=profile.profile_picture if profile else None
    )

# View Mentee Profile (for institution admin)
@app.route("/view_mentee_profile/<int:mentee_id>")
def view_mentee_profile(mentee_id):
    # Allow institution admins to view mentee profiles
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))
    
    user = User.query.get(mentee_id)
    if not user or user.user_type != "2":
        flash("Mentee not found!", "error")
        return redirect(url_for("institution_mentees"))
    
    profile = MenteeProfile.query.filter_by(user_id=mentee_id).first()
    
    dob_formatted = ""
    if profile and profile.dob:
        try:
            dob_formatted = datetime.strptime(profile.dob, "%Y-%m-%d").strftime("%d-%m-%Y")
        except ValueError:
            dob_formatted = profile.dob
    
    # Fetch institution details to get its profile picture
    institution_details = None
    if user.institution_id:
        institution_details = Institution.query.filter_by(id=user.institution_id).first()
    elif user.institution:
        institution_details = Institution.query.filter_by(name=user.institution).first()

    institution_profile_picture = institution_details.profile_picture if institution_details else None
    
    return render_template(
        "mentee/menteeprofile.html",
        show_sidebar=False,
        full_name=user.name,
        email=user.email,
        institution=user.institution,
        dob=dob_formatted,
        school_college_name=profile.school_college_name if profile else "",
        mobile_number=profile.mobile_number if profile else "",
        whatsapp_number=profile.whatsapp_number if profile else "",
        govt_private=profile.govt_private if profile else "",
        stream=profile.stream if profile else "",
        class_year=profile.class_year if profile else "",
        favourite_subject=profile.favourite_subject if profile else "",
        goal=profile.goal if profile else "",
        parent_name=profile.parent_name if profile else "",
        parent_mobile=profile.parent_mobile if profile else "",
        comments=profile.comments if profile else "",
        terms_agreement=profile.terms_agreement if profile else "",
        profile_picture=profile.profile_picture if profile else None,
        institution_profile_picture=institution_profile_picture
    )
# ------------------ APPROVE/REJECT MENTORSHIP REQUESTS ------------------
@app.route("/supervisor_response", methods=["POST"])
def supervisor_response():
    if "email" not in session or session.get("user_type") != "0":
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    request_id = request.form.get("request_id")
    action = request.form.get("action")
    
    if not request_id or not action:
        flash("Invalid request!", "error")
        return redirect(url_for("view_requests"))
    
    # Fetch mentorship request
    mentorship_request = MentorshipRequest.query.get(int(request_id))
    if not mentorship_request:
        flash("Request not found!", "error")
        return redirect(url_for("view_requests"))
    
    # Update status based on action
    if action == "approve":
        flash("Mentorship request approved!", "success")
        
        # Assign tasks if 12-month duration
        assigned_tasks = []
        if mentorship_request.duration_months == 12:
            try:
                assigned_tasks = assign_master_tasks_to_mentorship(mentorship_request)
                if assigned_tasks:
                    flash(f"Mentorship approved! {len(assigned_tasks)} tasks assigned.", "success")
                else:
                    flash("Mentorship approved! But no tasks were assigned.", "warning")
            except Exception as e:
                flash(f"Mentorship approved but task assignment failed: {str(e)}", "warning")
                print("Task assignment error:", e)
        else:
            flash("Mentorship request approved!", "success")

        # Re-set status AFTER task assignment (assign function may rollback session)
        mentorship_request.supervisor_status = "approved"
        mentorship_request.final_status = "approved"

    elif action == "reject":
        mentorship_request.supervisor_status = "rejected"
        mentorship_request.final_status = "rejected"
        flash("Mentorship request rejected!", "success")

        # Notify the mentee about the rejection
        try:
            if mentorship_request.mentee:
                create_notification(
                    mentorship_request.mentee.id,
                    "Your mentorship request was rejected by the supervisor.",
                    url_for("my_mentors")
                )
            if mentorship_request.mentor:
                create_notification(
                    mentorship_request.mentor.id,
                    f"Mentorship with a mentee was rejected by the supervisor.",
                    url_for("my_mentees")
                )
        except Exception as e:
            print("Notification error:", e)
    else:
        flash("Invalid action!", "error")
        return redirect(url_for("view_requests"))
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash("Something went wrong while updating the request.", "error")
        print("DB Commit Error:", e)
        return redirect(url_for("view_requests"))

    # Post-commit notifications (wrapped in try-except so they don't crash the request)
    if action == "approve":
        try:
            notify_mentorship_connection(mentorship_request)
        except Exception as e:
            print("notify_mentorship_connection error:", e)
        try:
            send_mentorship_connected_email(mentorship_request)
        except Exception as e:
            print("send_mentorship_connected_email error:", e)
    return redirect(url_for("view_requests", status="approved" if action == "approve" else "rejected"))


# ------------------ ALL MENTORSHIPS PAGE ------------------
@app.route("/supervisor_all_mentorships")
def supervisor_all_mentorships():
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))
    
    user = User.query.filter_by(email=session["email"]).first()
    profile_complete = check_profile_complete(user.id, "0")
    
    # Get ALL mentorship requests with eager loading to avoid N+1 queries
    all_mentorships = MentorshipRequest.query.options(
        joinedload(MentorshipRequest.mentor).joinedload(User.mentor_profile),
        joinedload(MentorshipRequest.mentee).joinedload(User.mentee_profile)
    ).order_by(
        (MentorshipRequest.final_status == "pending").desc(),
        (MentorshipRequest.final_status == "approved").desc(),
        MentorshipRequest.created_at.desc()
    ).all()
    
    # Pre-fetch all tasks and meetings for these mentorships to avoid N+1 queries
    mentorship_ids = [m.id for m in all_mentorships]
    
    # Build sets of (mentee_id, mentor_id) pairs from mentorships for matching
    mentorship_pairs = {(m.mentee_id, m.mentor_id) for m in all_mentorships}
    mentee_ids_set = {m.mentee_id for m in all_mentorships}
    mentor_ids_set = {m.mentor_id for m in all_mentorships}
    
    # Fetch all tasks for these mentorships (MenteeTask has mentee_id + mentor_id, no mentorship_request_id)
    tasks = MenteeTask.query.filter(
        MenteeTask.mentee_id.in_(mentee_ids_set),
        MenteeTask.mentor_id.in_(mentor_ids_set)
    ).all() if mentorship_ids else []
    
    # Group tasks by (mentee_id, mentor_id) pair
    tasks_by_pair = {}
    for task in tasks:
        tasks_by_pair.setdefault((task.mentee_id, task.mentor_id), []).append(task)
    
    # Fetch all meetings for these mentorships (MeetingRequest has requester_id + requested_to_id)
    all_meeting_pairs = set()
    for m in all_mentorships:
        all_meeting_pairs.add((m.mentee_id, m.mentor_id))
        all_meeting_pairs.add((m.mentor_id, m.mentee_id))
    
    all_requester_ids = list({p[0] for p in all_meeting_pairs})
    all_requested_ids = list({p[1] for p in all_meeting_pairs})
    
    meetings = MeetingRequest.query.filter(
        MeetingRequest.requester_id.in_(all_requester_ids),
        MeetingRequest.requested_to_id.in_(all_requested_ids)
    ).all() if mentorship_ids else []
    
    # Group meetings by (requester_id, requested_to_id) pair
    meetings_by_pair = {}
    for meeting in meetings:
        meetings_by_pair.setdefault((meeting.requester_id, meeting.requested_to_id), []).append(meeting)
    
    # Get all mentor/mentee IDs for profile queries
    mentor_ids = [m.mentor_id for m in all_mentorships]
    mentee_ids = [m.mentee_id for m in all_mentorships]
    
    # Fetch all profiles in bulk
    mentor_profiles = {p.user_id: p for p in MentorProfile.query.filter(MentorProfile.user_id.in_(mentor_ids)).all()} if mentor_ids else {}
    mentee_profiles = {p.user_id: p for p in MenteeProfile.query.filter(MenteeProfile.user_id.in_(mentee_ids)).all()} if mentee_ids else {}
    
    # Get all mentors and mentees in bulk
    mentors = {u.id: u for u in User.query.filter(User.id.in_(mentor_ids)).all()} if mentor_ids else {}
    mentees = {u.id: u for u in User.query.filter(User.id.in_(mentee_ids)).all()} if mentee_ids else {}
    
    mentorships_data = []
    for mentorship in all_mentorships:
        mentor = mentors.get(mentorship.mentor_id)
        mentee = mentees.get(mentorship.mentee_id)
        mentor_profile = mentor_profiles.get(mentorship.mentor_id)
        mentee_profile = mentee_profiles.get(mentorship.mentee_id)
        pair = (mentorship.mentee_id, mentorship.mentor_id)
        tasks = tasks_by_pair.get(pair, [])
        # Meetings can be in either direction
        meetings = meetings_by_pair.get(pair, []) + meetings_by_pair.get((mentorship.mentor_id, mentorship.mentee_id), [])
        
        mentorships_data.append({
            "request": mentorship,
            "mentor": mentor,
            "mentor_profile": mentor_profile,
            "mentee": mentee,
            "mentee_profile": mentee_profile,
            "tasks": tasks,
            "meetings": meetings,
            "tasks_completed": len([t for t in tasks if compute_task_progress_status("master", t.id, t.mentee_id, t.mentor_id) == "done"]),
            "tasks_total": len(tasks),
            "meetings_completed": len([m for m in meetings if m.status == "approved"]),
            "meetings_total": len(meetings),
            "rating": compute_mentorship_composite_rating(mentorship.mentee_id, mentorship.mentor_id) if mentor else None
        })
    
    return render_template(
        "supervisor/supervisor_all_mentorships.html",
        show_sidebar=True,
        user_email=session["email"],
        mentorships_data=mentorships_data,
        profile_complete=profile_complete
    )

# ---------- Google Calendar Service Account Config ----------
CALENDAR_SERVICE_SCOPES = ["https://www.googleapis.com/auth/calendar"]
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
DELEGATED_EMAIL = os.environ.get("GOOGLE_DELEGATED_EMAIL", "info@wazireducationsociety.com")  # Organization calendar email
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", DELEGATED_EMAIL)  # Calendar where meetings are created
MEETING_TIMEZONE = os.environ.get("GOOGLE_MEETING_TIMEZONE", "Asia/Kolkata")  # Fallback timezone for calendar events

def get_calendar_service():
    """Return Google Calendar API service, or None if credentials are unavailable.

    Tries service_account.json first, then falls back to the GOOGLE_* variables
    loaded from .env. Never raises: callers treat None as "calendar unavailable"
    so meeting scheduling keeps working without Google Calendar integration.
    """
    try:
        if os.path.exists(SERVICE_ACCOUNT_FILE):
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=CALENDAR_SERVICE_SCOPES
            )
        else:
            private_key = os.environ.get("GOOGLE_PRIVATE_KEY", "")
            client_email = os.environ.get("GOOGLE_CLIENT_EMAIL", "")
            if not private_key or not client_email:
                app.logger.warning(
                    "Google Calendar unavailable: service_account.json not found and "
                    "GOOGLE_CLIENT_EMAIL/GOOGLE_PRIVATE_KEY missing from environment"
                )
                return None
            service_account_info = {
                "type": "service_account",
                "project_id": os.environ.get("GOOGLE_PROJECT_ID", ""),
                "private_key_id": os.environ.get("GOOGLE_PRIVATE_KEY_ID", ""),
                "private_key": private_key.replace("\\n", "\n"),
                "client_email": client_email,
                "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
                "auth_uri": os.environ.get(
                    "GOOGLE_AUTH_URI", "https://accounts.google.com/o/oauth2/auth"
                ),
                "token_uri": os.environ.get(
                    "GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token"
                ),
                "auth_provider_x509_cert_url": os.environ.get(
                    "GOOGLE_AUTH_PROVIDER_CERT_URL",
                    "https://www.googleapis.com/oauth2/v1/certs",
                ),
                "client_x509_cert_url": os.environ.get("GOOGLE_CLIENT_CERT_URL", ""),
            }
            creds = service_account.Credentials.from_service_account_info(
                service_account_info, scopes=CALENDAR_SERVICE_SCOPES
            )
        delegated_creds = creds.with_subject(DELEGATED_EMAIL)
        service = build("calendar", "v3", credentials=delegated_creds)
        return service
    except Exception as e:
        app.logger.error(f"Could not initialize Google Calendar service: {e}")
        return None

# ---------- Microsoft Graph API for Teams Meetings ----------
MS_TENANT_ID = os.environ.get("MS_TENANT_ID", "")
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET", "")
MS_USER_EMAIL = os.environ.get("MS_USER_EMAIL", "info@wazireducationsociety.com")

def get_ms_graph_token():
    """Obtain an OAuth2 access token for Microsoft Graph using client_credentials flow."""
    if not MS_TENANT_ID or not MS_CLIENT_ID or not MS_CLIENT_SECRET:
        return None
    try:
        token_url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token"
        resp = http_requests.post(token_url, data={
            "grant_type": "client_credentials",
            "client_id": MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default"
        }, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("access_token")
        app.logger.error(f"MS Graph token error: {resp.status_code} {resp.text}")
    except Exception as e:
        app.logger.error(f"MS Graph token request failed: {e}")
    return None

def create_teams_online_meeting(title, start_utc, end_utc, attendee_emails):
    """Create a Microsoft Teams online meeting via Graph API and return the join URL."""
    token = get_ms_graph_token()
    if not token:
        return None
    try:
        url = f"https://graph.microsoft.com/v1.0/users/{MS_USER_EMAIL}/onlineMeetings"
        body = {
            "subject": title,
            "startDateTime": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDateTime": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lobbyBypassSettings": {
                "enabled": True,
                "scope": "everyone"
            }
        }
        resp = http_requests.post(url, json=body, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }, timeout=30)
        if resp.status_code in (200, 201):
            meeting_data = resp.json()
            return meeting_data.get("joinWebUrl")
        app.logger.error(f"Teams meeting creation failed: {resp.status_code} {resp.text}")
    except Exception as e:
        app.logger.error(f"Teams meeting creation error: {e}")
    return None

#-------------------creat meeting request---------------------------------
@app.route("/mentee_create_meeting_request/<int:mentor_id>", methods=["GET"])
def mentee_create_meeting_request(mentor_id):
    if "email" not in session:
        return redirect(url_for("signin"))

    mentee = User.query.filter_by(email=session["email"]).first()

    if not mentee:
        return redirect(url_for("signin"))

    # Get all active mentors for this mentee
    active_mentorships = MentorshipRequest.query.filter_by(
        mentee_id=mentee.id,
        final_status="approved"
    ).all()
    
    all_active_mentors = []
    mentor_types = {}
    for mr in active_mentorships:
        m = User.query.get(mr.mentor_id)
        if m:
            all_active_mentors.append(m)
            mentor_types[m.id] = mr.mentor_type

    # Check if the mentee has an active (approved) mentorship with this mentor
    active_mentorship = MentorshipRequest.query.filter_by(
        mentee_id=mentee.id,
        mentor_id=mentor_id,
        supervisor_status="approved",
        final_status="approved"
    ).first()

    if not active_mentorship:
        flash("You don't have an active mentorship with this mentor yet. Connect with a mentor first.", "error")
        return redirect(url_for("my_mentors"))

    mentor = User.query.get(mentor_id)

    if not mentor:
        flash("Mentor not found", "error")
        return redirect(url_for("my_mentors"))

    # Tasks currently being worked on in this mentorship (not completed yet),
    # so the mentee can pick one to discuss during the meeting
    running_tasks = MenteeTask.query.filter(
        MenteeTask.mentee_id == mentee.id,
        MenteeTask.mentor_id == mentor.id,
        MenteeTask.status.in_(["pending", "in-progress"])
    ).order_by(MenteeTask.meeting_number.asc()).all()

    # All active institutions for the institute selection dropdown
    all_institutions = Institution.query.filter_by(status="active").all()

    return render_template(
        "mentee/mentee_create_meeting_request.html",
        mentee=mentee,
        mentor=mentor,
        all_active_mentors=all_active_mentors,
        mentor_types=mentor_types,
        active_mentorship=active_mentorship,
        running_tasks=running_tasks,
        all_institutions=all_institutions
    )

@app.route("/get_tasks_for_mentorship")
def get_tasks_for_mentorship():
    """Return tasks for a given (mentee_id, mentor_id) pair as JSON."""
    if "email" not in session or session.get("user_type") != "0":
        return jsonify({"error": "Unauthorized"}), 401

    mentee_id = request.args.get("mentee_id", type=int)
    mentor_id = request.args.get("mentor_id", type=int)

    if not mentee_id or not mentor_id:
        return jsonify({"tasks": []})

    tasks = MenteeTask.query.filter_by(
        mentee_id=mentee_id,
        mentor_id=mentor_id
    ).all()

    task_list = []
    for t in tasks:
        master = t.master_task
        task_list.append({
            "id": t.id,
            "meeting_number": t.meeting_number,
            "month": t.month,
            "status": compute_task_progress_status("master", t.id, t.mentee_id, t.mentor_id),
            "due_date": t.due_date.strftime("%b %d, %Y") if t.due_date else "",
            "purpose": master.purpose_of_call if master else "",
            "mentor_focus": master.mentor_focus if master else "",
            "mentee_focus": master.mentee_focus if master else ""
        })

    return jsonify({"tasks": task_list})

@app.route("/get_external_mentors/<int:mentee_id>")
def get_external_mentors(mentee_id):
    """Return all mentors from OTHER institutes (not the current institution's mentors)."""
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return jsonify({"mentors": []})

    _, inst_id, _, _ = _get_institution_details(user)

    all_mentors = User.query.filter_by(user_type="1").all()
    result = []
    for m in all_mentors:
        if inst_id and m.institution_id == inst_id:
            continue
        m_inst_name = ""
        if m.institution_id:
            inst = Institution.query.get(m.institution_id)
            if inst:
                m_inst_name = inst.name
        if not m_inst_name:
            m_inst_name = getattr(m, "institution", "") or ""
        if not m_inst_name and hasattr(m, "mentor_profile") and m.mentor_profile:
            m_inst_name = getattr(m.mentor_profile, "university_name", "") or ""
        result.append({
            "id": m.id,
            "name": m.name,
            "email": m.email,
            "institution": m_inst_name,
            "institution_id": m.institution_id or ""
        })

    return jsonify({"mentors": result})

@app.route("/create_meeting_ajax", methods=["POST"])
def create_meeting_ajax():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request body"}), 400
    title = data.get("title")
    date = data.get("date")
    start_time = data.get("start_time")
    duration = data.get("duration")  # duration in minutes
    timezone = data.get("timezone", "Asia/Kolkata")  # default to IST if not provided
    mentor_id = data.get("mentor_id")
    mentee_id = data.get("mentee_id")
    institution_id = data.get("institution_id")
    task_id = data.get("task_id")
    mentorship_id = data.get("mentorship_id")

    def _safe_int(v):
        try:
            return int(v) if v is not None and str(v).strip() != "" else None
        except (ValueError, TypeError):
            return None

    # Determine the requested_to participant (mentor, mentee, or institution)
    mentor_user = User.query.get(_safe_int(mentor_id)) if _safe_int(mentor_id) else None
    mentee_user = User.query.get(_safe_int(mentee_id)) if _safe_int(mentee_id) else None
    institution_user = User.query.get(_safe_int(institution_id)) if _safe_int(institution_id) else None

    requested_to = mentor_user or mentee_user or institution_user
    requested_to_type = "mentor" if mentor_user else ("mentee" if mentee_user else ("institution" if institution_user else None))

    platform = (data.get("platform") or "google").strip().lower()
    custom_link = (data.get("custom_link") or "").strip()
    if platform not in ("google", "teams", "custom"):
        platform = "google"

    missing_fields = []
    if not mentor_id and not mentee_id:
        missing_fields.append("Mentor")
        missing_fields.append("Mentee")
    elif not mentor_id:
        missing_fields.append("Mentor")
    elif not mentee_id:
        missing_fields.append("Mentee")

    if not title or not str(title).strip():
        missing_fields.append("Meeting Title")
    if not date or not str(date).strip():
        missing_fields.append("Meeting Date")
    if not start_time or not str(start_time).strip():
        missing_fields.append("Meeting Time")
    if not duration or not str(duration).strip():
        missing_fields.append("Duration")
    if not timezone or not str(timezone).strip():
        missing_fields.append("Time Zone")
    if platform == "custom" and not custom_link:
        missing_fields.append("Meeting Link (for Other platform)")

    if missing_fields:
        if len(missing_fields) == 1:
            return jsonify({"error": f"{missing_fields[0]} is required. Please fill it in."}), 400
        else:
            return jsonify({"error": f"Please fill in the required fields: {', '.join(missing_fields)}."}), 400

    if _safe_int(mentor_id) and _safe_int(mentee_id):
        active_connection = MentorshipRequest.query.filter(
            MentorshipRequest.mentor_id == _safe_int(mentor_id),
            MentorshipRequest.mentee_id == _safe_int(mentee_id),
            MentorshipRequest.final_status == "approved"
        ).first()
        if not active_connection:
            return jsonify({"error": "No active mentorship connection found between this Mentor and Mentee. Meetings can only be scheduled for connected pairs."}), 400

    supervisor = User.query.filter_by(email=session["email"]).first()

    if not supervisor:
        return jsonify({"error": "User session not found. Please log in again."}), 404

    # Calculate start and end datetime
    try:
        start_datetime = dt.datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid date or time format. Please check your selection."}), 400

    try:
        duration_minutes = int(duration)
        if duration_minutes <= 0:
            return jsonify({"error": "Duration must be a positive number."}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid duration selected."}), 400

    # ✅ VALIDATION: Check if meeting date/time is in the past
    current_datetime = dt.datetime.now()
    if start_datetime <= current_datetime:
        return jsonify({"error": "Cannot create meeting for past or current date/time. Please select a future date and time."}), 400

    end_datetime = start_datetime + dt.timedelta(minutes=duration_minutes)
    start_str = start_datetime.isoformat()
    end_str = end_datetime.isoformat()

    # Build task context for description (must be before calendar event creation)
    task_context = ""
    if task_id:
        try:
            mentee_task = MenteeTask.query.get(int(task_id))
            if mentee_task and mentee_task.master_task:
                mt = mentee_task.master_task
                task_context = (
                    f"\n\n--- Task to Discuss ---\n"
                    f"Meeting #{mentee_task.meeting_number} ({mentee_task.month})\n"
                    f"Purpose: {mt.purpose_of_call}\n"
                    f"Mentor Focus: {mt.mentor_focus}\n"
                    f"Mentee Focus: {mt.mentee_focus}\n"
                    f"Status: {mentee_task.status}"
                )
        except Exception:
            pass

    meet_link = None
    gcal_event_id = None
    calendar_warning = None
    calendar_add_link = None
    teams_calendar_link = None

    # Resolve all participant User objects for attendees list
    mentor_user = User.query.get(int(mentor_id)) if mentor_id else None
    mentee_user = User.query.get(int(mentee_id)) if mentee_id else None

    if platform == "google":
        service = get_calendar_service()
        if service:
            try:
                # Build attendees list: always include supervisor + requested_to
                # Then add mentor/mentee if they aren't the same as requested_to
                attendees = [
                    {"email": supervisor.email},
                    {"email": requested_to.email}
                ]
                if mentor_user and mentor_user.email != requested_to.email:
                    attendees.append({"email": mentor_user.email})
                if mentee_user and mentee_user.email != requested_to.email:
                    attendees.append({"email": mentee_user.email})

                event = {
                    "summary": title,
                    "description": f"Meeting created by {supervisor.name} ({supervisor.email}) in {timezone} timezone{task_context}",
                    "start": {"dateTime": start_str, "timeZone": timezone},
                    "end": {"dateTime": end_str, "timeZone": timezone},
                    "attendees": attendees,
                    "reminders": {
                        "useDefault": False,
                        "overrides": [
                            {"method": "email", "minutes": 60},
                            {"method": "popup", "minutes": 10}
                        ]
                    },
                    "guestsCanSeeOtherGuests": True,
                    "guestsCanInviteOthers": False,
                    "guestsCanModify": False,
                    "conferenceData": {
                        "createRequest": {
                            "conferenceSolutionKey": {"type": "hangoutsMeet"},
                            "requestId": f"meet-{int(dt.datetime.utcnow().timestamp())}"
                        }
                    }
                }

                event = service.events().insert(
                    calendarId=CALENDAR_ID,
                    body=event,
                    conferenceDataVersion=1,
                    sendUpdates="all"
                ).execute()

                meet_link = event.get("hangoutLink")
                gcal_event_id = event.get("id")
            except Exception as e:
                app.logger.error(f"Google Calendar event creation failed: {e}")
                calendar_warning = ("Meeting request saved, but the Google Meet link could "
                                    "not be generated due to a calendar integration error.")
        else:
            calendar_warning = ("Meeting request saved without a Google Meet link because "
                                "calendar integration is not configured.")

        all_emails = [supervisor.email, requested_to.email]
        if mentor_user and mentor_user.email not in all_emails:
            all_emails.append(mentor_user.email)
        if mentee_user and mentee_user.email not in all_emails:
            all_emails.append(mentee_user.email)

        calendar_add_link = (
            "https://calendar.google.com/calendar/render?"
            + urlencode({
                "action": "TEMPLATE",
                "text": title,
                "dates": f"{start_datetime.strftime('%Y%m%dT%H%M%S')}/{end_datetime.strftime('%Y%m%dT%H%M%S')}",
                "details": f"Meeting scheduled via Mentor Connect. Supervisor: {supervisor.email} | Participant: {requested_to.email}",
                "add": ",".join(all_emails),
                "ctz": timezone,
            })
        )
    elif platform == "custom":
        meet_link = custom_link if custom_link else None
    else:
        tzobj = dt.timezone.utc
        try:
            from zoneinfo import ZoneInfo
            try:
                tzobj = ZoneInfo(timezone)
            except Exception:
                tzobj = dt.timezone.utc
        except ImportError:
            tzobj = dt.timezone.utc

        start_utc = start_datetime.replace(tzinfo=tzobj).astimezone(dt.timezone.utc)
        end_utc = end_datetime.replace(tzinfo=tzobj).astimezone(dt.timezone.utc)

        all_emails_teams = [supervisor.email, requested_to.email]
        if mentor_user and mentor_user.email not in all_emails_teams:
            all_emails_teams.append(mentor_user.email)
        if mentee_user and mentee_user.email not in all_emails_teams:
            all_emails_teams.append(mentee_user.email)

        teams_meet_link = create_teams_online_meeting(title, start_utc, end_utc, all_emails_teams)
        if teams_meet_link:
            meet_link = teams_meet_link
        else:
            calendar_warning = (
                "Meeting saved without a Teams join link. Microsoft Graph API is not configured. "
                "Set MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, and MS_USER_EMAIL environment "
                "variables to enable automatic Teams meeting link generation."
            )

    try:
        meeting = MeetingRequest(
                requester_id=supervisor.id,
                requested_to_id=requested_to.id,
                meeting_title=title,
                meeting_description=f"Meeting scheduled by Supervisor {supervisor.name}.{task_context}",
                meeting_date=start_datetime.date(),
                meeting_time=start_datetime.time(),
                meeting_duration=duration_minutes,
                meet_link=meet_link,
                gcal_event_id=gcal_event_id,
                status="pending"
        )

        db.session.add(meeting)
        db.session.commit()

        if mentee_id and mentor_id:
            try:
                participants_data = {
                    "mentee_id": int(mentee_id),
                    "mentor_id": int(mentor_id),
                    "created_by": supervisor.id,
                    "created_by_name": supervisor.name
                }
                if task_id:
                    participants_data["task_id"] = task_id
                    participants_data["task_type"] = "master"
                _save_meeting_participants(meeting.id, participants_data)
            except Exception as e:
                app.logger.error(f"Failed to save meeting participants: {e}")

        # Send meeting link notification to all participants via email
        _send_meeting_link_email(
            meeting=meeting,
            meet_link=meet_link,
            calendar_add_link=calendar_add_link,
            teams_calendar_link=teams_calendar_link,
            platform=platform,
            title=title,
            start_datetime=start_datetime,
            timezone=timezone,
            mentor_id=mentor_id,
            mentee_id=mentee_id,
            supervisor=supervisor,
            requested_to=requested_to
        )
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to save meeting request: {e}")
        return jsonify({"error": "Could not save the meeting request. Please try again."}), 500

    payload = {
        "message": "Meeting Created ✅",
        "meet_link": meet_link,
        "calendar_add_link": calendar_add_link,
        "teams_calendar_link": teams_calendar_link,
        "platform": platform,
        "title": title,
        "start": start_str,
        "end": end_str,
        "timezone": timezone,
        "supervisor_email": supervisor.email,
        "participant_email": requested_to.email,
        "mentor_email": mentor_user.email if mentor_user else requested_to.email,
        "mentee_email": mentee_user.email if mentee_user else ""
    }
    if calendar_warning:
        payload["warning"] = calendar_warning
    return jsonify(payload)

@app.route("/debug_oauth")
def debug_oauth():
    """Debug route to check OAuth users in database"""
    if "email" not in session:
        return "Not logged in"
    
    users = User.query.all()
    
    html = "<h1>OAuth Debug Info</h1>"
    html += f"<p>Total users: {len(users)}</p>"
    html += "<table border='1' cellpadding='10'>"
    html += "<tr><th>ID</th><th>Name</th><th>Email</th><th>Google ID</th><th>OAuth Provider</th><th>User Type</th><th>Created At</th></tr>"
    
    for user in users:
        html += f"<tr>"
        html += f"<td>{user.id}</td>"
        html += f"<td>{user.name}</td>"
        html += f"<td>{user.email}</td>"
        html += f"<td>{user.google_id or 'N/A'}</td>"
        html += f"<td>{user.oauth_provider or 'N/A'}</td>"
        html += f"<td>{user.user_type or 'Not selected'}</td>"
        html += f"<td>{user.oauth_created_at or 'N/A'}</td>"
        html += f"</tr>"
    
    html += "</table>"
    html += "<p><a href='/'>Back to home</a></p>"
    
    return html


def debug_profile():
    if "email" not in session:
        return "Not logged in"
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return "User not found"
    
    user_type = session.get('user_type')
    profile_complete = check_profile_complete(user.id, user_type)
    
    return f"""
    <h1>Profile Debug Info</h1>
    <p>User: {user.name} ({user.email})</p>
    <p>User Type: {user_type}</p>
    <p>Profile Complete: {profile_complete}</p>
    <p>Should Show Popup: {user_type in ['1', '2'] and not profile_complete}</p>
    <a href="/">Back to home</a>
    """

@app.route("/test_create_profile")
def test_create_profile():
    if "email" not in session:
        return "Not logged in"
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return "User not found"
    
    user_type = session.get('user_type')
    
    if user_type == "1":
        # Create a basic mentor profile
        profile = MentorProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            profile = MentorProfile(user_id=user.id, profession="Test Profession")
            db.session.add(profile)
            db.session.commit()
            return "Mentor profile created! Profile should now be complete."
        else:
            return "Mentor profile already exists"
    
    elif user_type == "2":
        # Create a basic mentee profile
        profile = MenteeProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            profile = MenteeProfile(user_id=user.id, school_college_name="Test School")
            db.session.add(profile)
            db.session.commit()
            return "Mentee profile created! Profile should now be complete."
        else:
            return "Mentee profile already exists"
    
    return "Not a mentor or mentee"

# ------------------ LOGOUT ------------------
@app.route("/logout")
def logout():
    session.clear()   
    flash("You have been logged out!", "info")
    return redirect(url_for("signin"))


@app.route("/view_mastertask_data")
def view_mastertask_data():
    """View all MasterTask data in a structured format"""
    if "email" not in session:
        return redirect(url_for("signin"))

    # Fetch all meetings ordered by meeting number
    meetings = MasterTask.query.order_by(MasterTask.meeting_number).all()
    
    # Get unique values for filters
    months = sorted({meeting.month for meeting in meetings})
    phases = sorted({meeting.journey_phase for meeting in meetings})
    
    return render_template(
        "view_mastertask_data.html",
        meetings=meetings,
        months=months,
        phases=phases,
        last_updated=datetime.now().strftime("%d-%m-%Y %H:%M")
    )



def create_sample_institutions():
    """Create sample institutions for testing"""
    institutions = [
        {"name": "Delhi University", "city": "Delhi", "country": "India"},
        {"name": "IIT Delhi", "city": "Delhi", "country": "India"},
        {"name": "Amity University", "city": "Noida", "country": "India"},
        {"name": "Other"}
    ]
    
    for inst_data in institutions:
        existing = Institution.query.filter_by(name=inst_data["name"]).first()
        if not existing:
            institution = Institution(
                name=inst_data["name"],
                city=inst_data.get("city", ""),
                country=inst_data.get("country", "")
            )
            db.session.add(institution)
    
    db.session.commit()

# ==================== CHAT FEATURE ROUTES ====================

@app.route("/chat")
def chat():
    """Main chat page - display conversations"""
    if "email" not in session:
        return redirect(url_for("signin"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("signin"))
    
    return render_template(
        "chat.html",
        show_sidebar=True,
        user_email=session["email"],
        user_name=session.get("user_name", user.name),
        user_type=session.get("user_type"),
        current_user_profile_pic=None  # Will be populated from profile
    )

@app.route("/new-chat")
def new_chat():
    """New chat selection page"""
    if "email" not in session:
        return redirect(url_for("signin"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("signin"))
    
    return render_template(
        "new_chat.html",
        show_sidebar=True,
        user_email=session["email"],
        user_name=session.get("user_name", user.name),
        user_type=session.get("user_type"),
        current_user_profile_pic=None
    )

@app.route("/chat-contacts")
def chat_contacts():
    """Contact browser for selecting chat recipients"""
    if "email" not in session:
        return redirect(url_for("signin"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("signin"))
    
    user_type = session.get("user_type")
    
    # Get available contacts based on user type
    available_contacts = []
    
    if user_type == "2":  # Mentee
        # Can chat with mentors and supervisors
        mentors = User.query.filter_by(user_type="1").all()
        supervisors = User.query.filter_by(user_type="0").all()
        available_contacts = mentors + supervisors
    
    elif user_type == "1":  # Mentor
        # Can chat with mentees and supervisors
        mentees = User.query.filter_by(user_type="2").all()
        supervisors = User.query.filter_by(user_type="0").all()
        available_contacts = mentees + supervisors
    
    elif user_type == "0":  # Supervisor
        # Can chat with mentees, mentors, and institutions
        mentees = User.query.filter_by(user_type="2").all()
        mentors = User.query.filter_by(user_type="1").all()
        institutions = User.query.filter_by(user_type="3").all()
        available_contacts = mentees + mentors + institutions
    
    elif user_type == "3":  # Institution
        # Can chat with supervisors only
        supervisors = User.query.filter_by(user_type="0").all()
        available_contacts = supervisors
    
    return render_template(
        "chat_contacts.html",
        show_sidebar=True,
        user_email=session["email"],
        user_name=session.get("user_name", user.name),
        user_type=user_type,
        available_contacts=available_contacts,
        current_user_profile_pic=None
    )

@app.route("/customer-support")
def customer_support():
    """Redirect to chat with a supervisor for customer support"""
    if "email" not in session:
        flash("Please sign in to contact customer support", "info")
        return redirect(url_for("signin"))
    
    user_id = session.get("user_id")
    user_type = session.get("user_type")
    
    # Get first available supervisor
    supervisor = User.query.filter_by(user_type="0").first()
    
    if not supervisor:
        flash("No supervisors available at the moment. Please try again later or email us at info@wazireducationsocity.com", "error")
        return redirect(url_for("signin"))
    
    try:
        # Check if conversation already exists
        conversation = ChatConversation.query.filter(
            db.or_(
                db.and_(
                    ChatConversation.participant1_id == min(user_id, supervisor.id),
                    ChatConversation.participant2_id == max(user_id, supervisor.id)
                )
            ),
            ChatConversation.conversation_type == "direct"
        ).first()
        
        # If no conversation exists, create one
        if not conversation:
            conversation = ChatConversation(
                conversation_type="direct",
                participant1_id=min(user_id, supervisor.id),
                participant2_id=max(user_id, supervisor.id)
            )
            db.session.add(conversation)
            db.session.commit()
        
        # Redirect to chat page with conversation ID
        return redirect(url_for("chat") + f"?conversation_id={conversation.id}")
    
    except Exception as e:
        print(f"Error creating support conversation: {e}")
        flash("Unable to start chat. Please try again or email us at info@wazireducationsocity.com", "error")
        return redirect(url_for("signin"))

#--------------INSTITUTION PROFILE ROUTES------------------

@app.route("/institutionprofile")
def institutionprofile():
    """View institution profile"""
    if "email" not in session or session.get("user_type") != "3":
        return redirect(url_for("signin"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("signin"))
    
    # Get institution profile
    institution = Institution.query.filter_by(user_id=user.id).first()
    
    if not institution:
        flash("Institution profile not found.", "error")
        return redirect(url_for("institutiondashboard"))
    
    return render_template(
        "institution/institutionprofile.html",
        show_sidebar=False,
        institution_name=user.name,  # Always from user.name (signup_details table)
        email=user.email,    # Always from user.email (signup_details table)
        institution_type=institution.institution_type or "",
        email_domain=institution.email_domain or "",
        website=institution.website or "",
        address=institution.address or "",
        city=institution.city or "",
        state=institution.state or "",
        country=institution.country or "",
        contact_person=institution.contact_person or "",
        contact_phone=institution.contact_phone or "",
        status=institution.status or "active",
        profile_picture=institution.profile_picture or None,
        institution_details=institution,
        full_name=user.name  # Institution name from signup
    )


# ============================================================
# CHAT SYSTEM ROUTES
# ============================================================

def check_chat_access(user_id, other_user_id, user_type):
    """
    Check if a user can chat with another user based on roles.
    
    Rules:
    - Mentee (2) can chat with: assigned mentor (1), supervisor (0)
    - Mentor (1) can chat with: assigned mentees (2), supervisor (0)
    - Supervisor (0) can chat with: any mentor (1), any mentee (2)
    - Institution (3) can chat with: supervisors (0)
    
    Returns: (allowed: bool, reason: str)
    """
    other_user = User.query.get(other_user_id)
    if not other_user:
        return False, "User not found"
    
    other_type = other_user.user_type
    
    # Mentee (2) rules
    if user_type == "2":
        if other_type == "0":  # Can chat with supervisor
            return True, "Mentee can chat with supervisor"
        elif other_type == "1":  # Can chat with assigned mentor only
            # Check if there's an approved mentorship
            mentorship = MentorshipRequest.query.filter_by(
                mentee_id=user_id,
                mentor_id=other_user_id,
                final_status="approved"
            ).first()
            if mentorship:
                return True, "Mentee can chat with assigned mentor"
            return False, "Not assigned to this mentor"
        return False, "Mentee cannot chat with this user type"
    
    # Mentor (1) rules
    elif user_type == "1":
        if other_type == "0":  # Can chat with supervisor
            return True, "Mentor can chat with supervisor"
        elif other_type == "2":  # Can chat with assigned mentees only
            # Check if there's an approved mentorship
            mentorship = MentorshipRequest.query.filter_by(
                mentee_id=other_user_id,
                mentor_id=user_id,
                final_status="approved"
            ).first()
            if mentorship:
                return True, "Mentor can chat with assigned mentee"
            return False, "Not assigned to this mentee"
        return False, "Mentor cannot chat with this user type"
    
    # Supervisor (0) rules
    elif user_type == "0":
        if other_type in ["1", "2"]:  # Can chat with any mentor or mentee
            return True, "Supervisor can chat with any mentor or mentee"
        return False, "Supervisor cannot chat with this user type"
    
    # Institution (3) rules
    elif user_type == "3":
        if other_type == "0":  # Can chat with supervisors
            return True, "Institution can chat with supervisor"
        return False, "Institution cannot chat with this user type"
    
    return False, "Invalid user type"


def get_or_create_conversation(user_id, other_user_id):
    """
    Get existing conversation or create a new one between two users.
    """
    # Check if conversation already exists
    conversation = ChatConversation.query.filter(
        db.or_(
            db.and_(
                ChatConversation.participant1_id == user_id,
                ChatConversation.participant2_id == other_user_id
            ),
            db.and_(
                ChatConversation.participant1_id == other_user_id,
                ChatConversation.participant2_id == user_id
            )
        ),
        ChatConversation.conversation_type == "direct"
    ).first()
    
    if conversation:
        return conversation
    
    # Create new conversation
    conversation = ChatConversation(
        conversation_type="direct",
        participant1_id=min(user_id, other_user_id),
        participant2_id=max(user_id, other_user_id)
    )
    db.session.add(conversation)
    db.session.commit()
    return conversation


@app.route("/api/chat/current-user", methods=["GET"])
def get_current_user():
    """
    Get the current user's ID and info.
    """
    if "email" not in session or "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    user_type = session.get("user_type")
    user_name = session.get("user_name")
    
    return jsonify({
        "success": True,
        "user_id": user_id,
        "user_type": user_type,
        "user_name": user_name
    })


@app.route("/api/chat/conversations", methods=["GET"])
def get_conversations():
    """
    Get all conversations for the current user.
    """
    if "email" not in session or "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    user_type = session.get("user_type")
    
    try:
        # Get all conversations where user is a participant
        conversations = ChatConversation.query.filter(
            db.or_(
                ChatConversation.participant1_id == user_id,
                ChatConversation.participant2_id == user_id
            ),
            ChatConversation.conversation_type == "direct"
        ).order_by(ChatConversation.updated_at.desc()).all()
        
        result = []
        for conv in conversations:
            # Get the other participant
            other_user_id = conv.participant2_id if conv.participant1_id == user_id else conv.participant1_id
            other_user = User.query.get(other_user_id)
            
            # Get last message
            last_message = ChatMessage.query.filter_by(
                conversation_id=conv.id
            ).order_by(ChatMessage.created_at.desc()).first()
            
            # Count unread messages
            unread_count = ChatMessage.query.filter_by(
                conversation_id=conv.id,
                is_read=False
            ).filter(ChatMessage.sender_id != user_id).count()
            
            result.append({
                "id": conv.id,
                "other_user_id": other_user_id,
                "other_user_name": other_user.name,
                "other_user_type": other_user.user_type,
                "last_message": last_message.content if last_message else None,
                "last_message_time": last_message.created_at.isoformat() + 'Z' if last_message else None,  # Add 'Z' to indicate UTC
                "unread_count": unread_count,
                "updated_at": conv.updated_at.isoformat() + 'Z'  # Add 'Z' to indicate UTC
            })
        
        return jsonify({"success": True, "conversations": result})
    
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/chat/start/<int:other_user_id>", methods=["POST"])
def start_conversation(other_user_id):
    """
    Start or get a conversation with another user.
    Checks access control before allowing.
    """
    if "email" not in session or "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    user_type = session.get("user_type")
    
    try:
        # Check access control
        allowed, reason = check_chat_access(user_id, other_user_id, user_type)
        if not allowed:
            return jsonify({"success": False, "message": reason}), 403
        
        # Get or create conversation
        conversation = get_or_create_conversation(user_id, other_user_id)
        
        return jsonify({
            "success": True,
            "conversation_id": conversation.id,
            "message": "Conversation started"
        })
    
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/chat/messages/<int:conversation_id>", methods=["GET"])
def get_messages(conversation_id):
    """
    Get all messages in a conversation.
    Includes pagination support.
    """
    if "email" not in session or "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    
    try:
        conversation = ChatConversation.query.get_or_404(conversation_id)
        
        # Check if user is a participant
        if not (conversation.participant1_id == user_id or conversation.participant2_id == user_id):
            return jsonify({"success": False, "message": "Access denied"}), 403
        
        # Get messages with pagination
        messages_query = ChatMessage.query.filter_by(
            conversation_id=conversation_id
        ).order_by(ChatMessage.created_at.asc())
        
        total = messages_query.count()
        messages = messages_query.paginate(page=page, per_page=per_page).items
        
        result = []
        for msg in messages:
            result.append({
                "id": msg.id,
                "sender_id": msg.sender_id,
                "sender_name": msg.sender.name,
                "content": msg.content,
                "is_read": msg.is_read,
                "created_at": msg.created_at.isoformat() + 'Z'  # Add 'Z' to indicate UTC
            })
        
        return jsonify({
            "success": True,
            "messages": result,
            "total": total,
            "page": page,
            "per_page": per_page
        })
    
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/chat/send", methods=["POST"])
def send_message():
    """
    Send a message in a conversation.
    """
    if "email" not in session or "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    data = request.get_json()
    
    conversation_id = data.get("conversation_id")
    content = data.get("content", "").strip()
    
    if not content:
        return jsonify({"success": False, "message": "Message cannot be empty"}), 400
    
    try:
        conversation = ChatConversation.query.get_or_404(conversation_id)
        
        # Check if user is a participant
        if not (conversation.participant1_id == user_id or conversation.participant2_id == user_id):
            return jsonify({"success": False, "message": "Access denied"}), 403
        
        # Create message
        message = ChatMessage(
            conversation_id=conversation_id,
            sender_id=user_id,
            content=content
        )
        db.session.add(message)
        
        # Update conversation timestamp
        conversation.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message_id": message.id,
            "created_at": message.created_at.isoformat() + 'Z'  # Add 'Z' to indicate UTC
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/chat/mark-read/<int:conversation_id>", methods=["POST"])
def mark_messages_read(conversation_id):
    """
    Mark all messages in a conversation as read.
    """
    if "email" not in session or "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    
    try:
        conversation = ChatConversation.query.get_or_404(conversation_id)
        
        # Check if user is a participant
        if not (conversation.participant1_id == user_id or conversation.participant2_id == user_id):
            return jsonify({"success": False, "message": "Access denied"}), 403
        
        # Mark all unread messages from other user as read
        ChatMessage.query.filter(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.sender_id != user_id,
            ChatMessage.is_read == False
        ).update({
            ChatMessage.is_read: True,
            ChatMessage.read_at: datetime.utcnow()
        })
        
        db.session.commit()
        
        return jsonify({"success": True, "message": "Messages marked as read"})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/chat/allowed-contacts", methods=["GET"])
def get_allowed_contacts():
    """
    Get list of users the current user can chat with based on their role.
    """
    if "email" not in session or "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    user_id = session.get("user_id")
    user_type = session.get("user_type")
    
    try:
        allowed_contacts = []
        
        if user_type == "2":  # Mentee
            # Get assigned mentor
            mentorship = MentorshipRequest.query.filter_by(
                mentee_id=user_id,
                final_status="approved"
            ).first()
            
            if mentorship:
                mentor = User.query.get(mentorship.mentor_id)
                if mentor:
                    allowed_contacts.append({
                        "id": mentor.id,
                        "name": mentor.name,
                        "type": "1",
                        "role": "My Mentor"
                    })
            
            # Get supervisors
            supervisors = User.query.filter_by(user_type="0").all()
            for supervisor in supervisors:
                allowed_contacts.append({
                    "id": supervisor.id,
                    "name": supervisor.name,
                    "type": "0",
                    "role": "Supervisor"
                })
        
        elif user_type == "1":  # Mentor
            # Get assigned mentees
            mentorships = MentorshipRequest.query.filter_by(
                mentor_id=user_id,
                final_status="approved"
            ).all()
            
            for mentorship in mentorships:
                mentee = User.query.get(mentorship.mentee_id)
                if mentee:
                    allowed_contacts.append({
                        "id": mentee.id,
                        "name": mentee.name,
                        "type": "2",
                        "role": "My Mentee"
                    })
            
            # Get supervisors
            supervisors = User.query.filter_by(user_type="0").all()
            for supervisor in supervisors:
                allowed_contacts.append({
                    "id": supervisor.id,
                    "name": supervisor.name,
                    "type": "0",
                    "role": "Supervisor"
                })
        
        elif user_type == "0":  # Supervisor
            # Can chat with any mentor or mentee
            mentors = User.query.filter_by(user_type="1").all()
            for mentor in mentors:
                allowed_contacts.append({
                    "id": mentor.id,
                    "name": mentor.name,
                    "type": "1",
                    "role": "Mentor"
                })
            
            mentees = User.query.filter_by(user_type="2").all()
            for mentee in mentees:
                allowed_contacts.append({
                    "id": mentee.id,
                    "name": mentee.name,
                    "type": "2",
                    "role": "Mentee"
                })
        
        elif user_type == "3":  # Institution
            # Can chat with supervisors
            supervisors = User.query.filter_by(user_type="0").all()
            for supervisor in supervisors:
                allowed_contacts.append({
                    "id": supervisor.id,
                    "name": supervisor.name,
                    "type": "0",
                    "role": "Supervisor"
                })
        
        return jsonify({
            "success": True,
            "contacts": allowed_contacts
        })
    
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ==================== PROFILE COMPLETION REMINDER SYSTEM ====================

def calculate_mentee_profile_completion(mentee_id, profile_obj=None):
    """
    Calculate profile completion percentage for mentees - tracks meaningful profile fields
    """
    profile = profile_obj if profile_obj is not None else MenteeProfile.query.filter_by(user_id=mentee_id).first()
    
    if not profile:
        return {
            'percentage': 0,
            'missing_fields': ['Complete your entire profile'],
            'completed_fields': 0,
            'total_fields': 1
        }
    
    # Define meaningful profile fields for mentee completion
    all_fields = {
        'Profile Photo': profile.profile_picture,
        'Mobile Number': profile.mobile_number,
        'WhatsApp Number': profile.whatsapp_number,
        'School/College Name': profile.school_college_name,
        'Stream': profile.stream,
        'Goal': profile.goal,
        'City': profile.city,
        'Country': profile.country,
        'Mentorship Expectations': profile.mentorship_expectations,
        'LinkedIn Link': profile.linkedin_link,
        'Institution': profile.institution,
        'Who Am I': profile.who_am_i,
    }
    
    completed_fields = sum(1 for field in all_fields.values() if field)
    total_fields = len(all_fields)
    missing_fields = [field_name for field_name, field_value in all_fields.items() if not field_value]
    percentage = (completed_fields * 100) // total_fields if total_fields > 0 else 0
    
    return {
        'percentage': min(percentage, 100),
        'missing_fields': missing_fields,
        'completed_fields': completed_fields,
        'total_fields': total_fields
    }

# Email Template Variations

EMAIL_TEMPLATES = {
    'friendly': {
        'subject_templates': [
            "Hey {name}! Your profile is {percent}% complete 🎯",
            "Quick reminder: Complete your {type} profile! ✨",
            "{name}, we'd love to see your complete profile! 💫",
            "Getting close! Your profile is {percent}% done 🚀",
        ],
        'body_template': """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #f8f9fa; padding: 20px; border-radius: 8px;">
    <h2 style="color: #2563eb; margin-bottom: 10px;">Hey {name}! 👋</h2>
    <p style="color: #64748b; font-size: 16px; line-height: 1.6;">
        We noticed your {type} profile is <strong>{percent}% complete</strong> ({completed}/{total} fields filled).
    </p>
    
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 15px; border-radius: 6px; margin: 20px 0; text-align: center;">
        <p style="font-size: 18px; font-weight: bold; margin: 0;">You're just {remaining} steps away from a complete profile!</p>
    </div>
    
    <p style="color: #64748b; font-size: 14px; margin: 15px 0;"><strong>Missing fields:</strong></p>
    <ul style="color: #64748b; line-height: 1.8;">
        {missing_fields_list}
    </ul>
    
    <p style="color: #64748b; margin: 20px 0;">
        <strong>Why complete your profile?</strong><br>
        ✅ Better mentor/mentee matching<br>
        ✅ Increase visibility on our platform<br>
        ✅ More connection requests & opportunities<br>
        ✅ Build stronger trust with the community
    </p>
    
    <div style="text-align: center; margin: 30px 0;">
        <a href="{profile_link}" style="background: #2563eb; color: white; padding: 12px 30px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">
            Complete Your Profile →
        </a>
    </div>
    
    {improvement_note}
    
    <p style="color: #94a3b8; font-size: 12px; margin-top: 20px; text-align: center;">
        You're doing great! Every field you add makes your profile stronger. 💪
    </p>
</div>
"""
    },
    'professional': {
        'subject_templates': [
            "Profile Completion Status: {percent}% - Action Required",
            "{name}, Complete Your {type} Profile",
            "Action Item: Profile Completion ({percent}%)",
        ],
        'body_template': """
<div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; background: white; padding: 30px; border: 1px solid #e2e8f0; border-radius: 4px;">
    <h2 style="color: #1e293b; margin-bottom: 15px;">Profile Completion Status</h2>
    
    <p style="color: #475569; font-size: 15px; line-height: 1.7; margin-bottom: 20px;">
        Dear {name},<br><br>
        This is a professional reminder that your {type} profile is currently <strong>{percent}% complete</strong> ({completed} of {total} required fields).
    </p>
    
    <table style="width: 100%; border-collapse: collapse; margin: 20px 0; background: #f1f5f9;">
        <tr style="background: #e2e8f0;">
            <td style="padding: 10px; border: 1px solid #cbd5e1;">Completed Fields</td>
            <td style="padding: 10px; border: 1px solid #cbd5e1; text-align: center; font-weight: bold;">{completed}/{total}</td>
        </tr>
        <tr>
            <td style="padding: 10px; border: 1px solid #cbd5e1;">Completion Percentage</td>
            <td style="padding: 10px; border: 1px solid #cbd5e1; text-align: center; font-weight: bold; color: #2563eb;">{percent}%</td>
        </tr>
        <tr style="background: #fef3c7;">
            <td style="padding: 10px; border: 1px solid #cbd5e1;">Outstanding Items</td>
            <td style="padding: 10px; border: 1px solid #cbd5e1; text-align: center; font-weight: bold; color: #d97706;">{remaining}</td>
        </tr>
    </table>
    
    <p style="color: #475569; font-weight: bold; margin-top: 20px; margin-bottom: 10px;">Outstanding Fields:</p>
    <ul style="color: #475569; line-height: 2;">
        {missing_fields_list}
    </ul>
    
    <div style="background: #f0f9ff; border-left: 4px solid #0284c7; padding: 15px; margin: 20px 0;">
        <p style="color: #0c4a6e; margin: 0;"><strong>Benefits of Profile Completion:</strong></p>
        <ul style="color: #0c4a6e; margin: 10px 0; padding-left: 20px;">
            <li>Enhanced visibility in mentor/mentee discovery</li>
            <li>Improved matching algorithm accuracy</li>
            <li>Increased trust and credibility</li>
            <li>Better recommendations from our system</li>
        </ul>
    </div>
    
    <div style="text-align: center; margin: 30px 0;">
        <a href="{profile_link}" style="background: #1e40af; color: white; padding: 12px 35px; border-radius: 4px; text-decoration: none; font-weight: bold; display: inline-block;">
            Update Profile
        </a>
    </div>
    
    {improvement_note}
    
    <p style="color: #64748b; font-size: 13px; margin-top: 25px; border-top: 1px solid #e2e8f0; padding-top: 15px; text-align: center;">
        This is an automated message from Mentors Connect platform.
    </p>
</div>
"""
    },
    'motivational': {
        'subject_templates': [
            "You're {percent}% of the way there! 🌟",
            "{name}, You Can Do It! Complete Your Profile 💪",
            "Almost there! Your profile is {percent}% complete",
        ],
        'body_template': """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 12px; color: white;">
    <h2 style="margin-top: 0; margin-bottom: 15px; font-size: 28px;">You're Almost There! 🎉</h2>
    
    <p style="font-size: 16px; line-height: 1.8; margin-bottom: 20px;">
        {name}, you're already <strong>{percent}% complete</strong> with your {type} profile!<br>
        That's <strong>{completed} out of {total}</strong> fields - fantastic progress! 🚀
    </p>
    
    <div style="background: rgba(255,255,255,0.1); padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center;">
        <p style="font-size: 14px; margin: 0; opacity: 0.9;">Just {remaining} more items to reach 100%!</p>
        <p style="font-size: 32px; margin: 10px 0; font-weight: bold; letter-spacing: 2px;">━━━━</p>
    </div>
    
    <p style="font-size: 15px; font-weight: bold; margin: 20px 0;">Here's what's left:</p>
    <ul style="font-size: 14px; line-height: 2;">
        {missing_fields_list}
    </ul>
    
    <div style="background: rgba(255,255,255,0.15); padding: 18px; border-radius: 8px; margin: 25px 0;">
        <p style="font-weight: bold; margin-top: 0; margin-bottom: 10px;">🌟 Imagine when your profile is complete:</p>
        <ul style="font-size: 14px; line-height: 1.9; margin: 0; padding-left: 20px;">
            <li>Stand out in our community</li>
            <li>Get matched with perfect connections</li>
            <li>Build meaningful relationships</li>
            <li>Unlock your full potential</li>
        </ul>
    </div>
    
    <div style="text-align: center; margin: 30px 0;">
        <a href="{profile_link}" style="background: white; color: #667eea; padding: 14px 40px; border-radius: 8px; text-decoration: none; font-weight: bold; display: inline-block; font-size: 16px;">
            Complete It Now! ⚡
        </a>
    </div>
    
    {improvement_note}
    
    <p style="font-size: 13px; margin-top: 20px; text-align: center; opacity: 0.9;">
        We believe in you! You've got this! 💫
    </p>
</div>
"""
    },
    'achievement': {
        'subject_templates': [
            "{name}, You've Achieved {percent}% Profile Completion!",
            "Achievement Unlocked: {percent}% Profile Complete",
            "Great Progress! {percent}% Complete",
        ],
        'body_template': """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); padding: 30px; border-radius: 10px; color: white; text-align: center; margin-bottom: 20px;">
        <div style="font-size: 60px; margin: 0;">🏆</div>
        <h2 style="margin: 10px 0; font-size: 24px;">Achievement Unlocked!</h2>
        <p style="margin: 10px 0; font-size: 18px; font-weight: bold;">{percent}% Profile Complete</p>
    </div>
    
    <p style="color: #333; font-size: 16px; line-height: 1.7; text-align: center;">
        Congratulations, {name}!<br>
        You've made excellent progress on your {type} profile.
    </p>
    
    <div style="background: #f0f4f8; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <h3 style="color: #2563eb; margin-top: 0;">Progress Summary</h3>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; text-align: center;">
            <div style="background: white; padding: 15px; border-radius: 6px;">
                <p style="margin: 0; color: #64748b; font-size: 12px;">Fields Completed</p>
                <p style="margin: 5px 0; font-size: 24px; font-weight: bold; color: #10b981;">{completed}/{total}</p>
            </div>
            <div style="background: white; padding: 15px; border-radius: 6px;">
                <p style="margin: 0; color: #64748b; font-size: 12px;">Remaining</p>
                <p style="margin: 5px 0; font-size: 24px; font-weight: bold; color: #f59e0b;">{remaining}</p>
            </div>
        </div>
    </div>
    
    <p style="color: #333; font-weight: bold; margin: 20px 0; font-size: 15px;">Next Steps to 100%:</p>
    <ul style="color: #555; line-height: 2; font-size: 14px;">
        {missing_fields_list}
    </ul>
    
    <div style="background: #ecfdf5; border: 2px solid #10b981; padding: 15px; border-radius: 6px; margin: 20px 0;">
        <p style="color: #065f46; margin: 0;"><strong>💡 Quick Tip:</strong> Completing the remaining fields will boost your profile visibility by up to 40% on our platform!</p>
    </div>
    
    <div style="text-align: center; margin: 25px 0;">
        <a href="{profile_link}" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; padding: 13px 35px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">
            Complete Remaining Fields →
        </a>
    </div>
    
    {improvement_note}
    
    <p style="color: #999; font-size: 12px; text-align: center; margin-top: 20px;">
        You're in the top {percentile}% of most complete profiles!
    </p>
</div>
"""
    },
    'community': {
        'subject_templates': [
            "{name}, Help Us Strengthen Our Community! 🤝",
            "Our Community Loves Complete Profiles Like Yours 💖",
            "{name}, Join Our Complete Profile Club!",
        ],
        'body_template': """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: white; padding: 30px;">
    <div style="text-align: center; margin-bottom: 30px;">
        <div style="font-size: 50px; margin-bottom: 10px;">🤝</div>
        <h2 style="color: #1e40af; margin: 0; font-size: 24px;">You're Part of Our Community</h2>
    </div>
    
    <p style="color: #4b5563; font-size: 15px; line-height: 1.8;">
        Dear {name},<br><br>
        Our Mentors Connect community thrives when members like you share complete and authentic information. Your profile is <strong>{percent}% complete</strong>, and you're already making an impact!
    </p>
    
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <h3 style="margin-top: 0; font-size: 16px;">Community Benefits You Unlock</h3>
        <ul style="margin: 0; padding-left: 20px; line-height: 2;">
            <li><strong>Discovery:</strong> Better visibility among {peers}</li>
            <li><strong>Connection:</strong> Meaningful interactions with the community</li>
            <li><strong>Growth:</strong> More opportunities aligned with your goals</li>
            <li><strong>Trust:</strong> Build credibility within our platform</li>
        </ul>
    </div>
    
    <p style="color: #4b5563; font-weight: bold; margin: 20px 0; font-size: 14px;">To complete your community profile, please add:</p>
    <div style="background: #f9fafb; padding: 15px; border-radius: 6px; border-left: 4px solid #667eea;">
        <ul style="color: #4b5563; margin: 0; padding-left: 20px; line-height: 1.8;">
            {missing_fields_list}
        </ul>
    </div>
    
    <div style="background: #fef3c7; border: 1px solid #fcd34d; padding: 15px; border-radius: 6px; margin: 20px 0;">
        <p style="color: #92400e; margin: 0;"><strong>✨ Fun Fact:</strong> Members with complete profiles receive {rate}% more connection requests and opportunities!</p>
    </div>
    
    <div style="text-align: center; margin: 30px 0;">
        <a href="{profile_link}" style="background: #667eea; color: white; padding: 13px 35px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block;">
            Join the Complete Profile Community
        </a>
    </div>
    
    {improvement_note}
    
    <p style="color: #9ca3af; font-size: 13px; text-align: center; margin-top: 25px;">
        Thank you for being part of Mentors Connect! 🌟
    </p>
</div>
"""
    }
}

def generate_profile_completion_email(user_id, user_type):
    """
    Generate personalized profile completion reminder email
    Returns: (subject, html_content, email_style, missing_fields_list)
    """
    user = User.query.get(user_id)
    if not user:
        return None
    
    # Calculate completion based on user type
    if user_type == "1":  # Mentor
        stats = calculate_mentor_profile_completion(user_id)
        profile_type = "mentor"
        edit_route = "editmentorprofile"
    else:  # Mentee (user_type == "2")
        stats = calculate_mentee_profile_completion(user_id)
        profile_type = "mentee"
        edit_route = "editmenteeprofile"
    
    # Don't send if 100% complete
    if stats['percentage'] == 100:
        return None
    
    # Get previous reminder to check for improvement
    last_reminder = ProfileCompletionReminder.query.filter_by(
        user_id=user_id,
        user_type=user_type
    ).order_by(ProfileCompletionReminder.sent_at.desc()).first()
    
    previous_percentage = last_reminder.completion_percentage if last_reminder else None
    improvement_note = ""
    if previous_percentage and stats['percentage'] > previous_percentage:
        improvement_note = f"""
        <div style="background: #d1fae5; border-left: 4px solid #10b981; padding: 12px; margin: 20px 0; border-radius: 4px;">
            <p style="color: #065f46; margin: 0; font-weight: bold;">🎯 Great Progress! Your profile improved from {previous_percentage}% to {stats['percentage']}% since last week!</p>
        </div>
        """
    
    # Select random email style
    email_style = random.choice(list(EMAIL_TEMPLATES.keys()))
    template = EMAIL_TEMPLATES[email_style]
    
    # Generate subject
    subject_template = random.choice(template['subject_templates'])
    subject = subject_template.format(
        name=user.name,
        percent=stats['percentage'],
        type=profile_type
    )
    
    # Build missing fields list
    missing_fields_html = "\n".join([
        f"<li>• {field}</li>" for field in stats['missing_fields'][:8]  # Show max 8
    ])
    
    # Generate body
    body_template = template['body_template']
    profile_link = url_for('mentordashboard' if user_type == "1" else 'menteedashboard', _external=True)
    
    html_content = body_template.format(
        name=user.name,
        type=profile_type,
        percent=stats['percentage'],
        completed=stats['completed_fields'],
        total=stats['total_fields'],
        remaining=stats['total_fields'] - stats['completed_fields'],
        missing_fields_list=missing_fields_html,
        profile_link=profile_link,
        improvement_note=improvement_note,
        peers="mentees" if user_type == "1" else "mentors",
        rate="25-40",
        percentile="top",
    )
    
    return {
        'subject': subject,
        'html_content': html_content,
        'email_style': email_style,
        'missing_fields': stats['missing_fields'],
        'completion_percentage': stats['percentage'],
        'completed_fields': stats['completed_fields'],
        'total_fields': stats['total_fields'],
        'previous_percentage': previous_percentage
    }

def send_email_reminder(user_email, subject, html_content):
    """
    Send email reminder using SMTP - uses app's existing email configuration
    """
    try:
        # Use app's existing email configuration (same as OTP emails)
        SENDER_EMAIL = SMTP_EMAIL  # From line 284
        SENDER_PASSWORD = SMTP_PASSWORD  # From line 286
        REMINDER_SMTP_SERVER = SMTP_SERVER  # From line 281
        REMINDER_SMTP_PORT = SMTP_PORT  # From line 283
        
        # For development/testing - can be disabled
        if not SENDER_PASSWORD:
            print(f"⚠️ Email service not configured. Would send to: {user_email}")
            print(f"Subject: {subject}")
            return True
        
        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = user_email
        
        # Attach HTML content
        part = MIMEText(html_content, "html")
        msg.attach(part)
        
        # Send email
        with smtplib.SMTP(REMINDER_SMTP_SERVER, REMINDER_SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, [user_email], msg.as_string())
        
        print(f"✅ Reminder email sent successfully to {user_email}")
        return True
    except Exception as e:
        print(f"❌ Error sending email to {user_email}: {str(e)}")
        return False

def send_profile_completion_reminders(force_send=False):
    """
    Scheduled job to send profile completion reminders
    
    Args:
        force_send (bool): If True, bypass "already sent today" check (for manual triggers)
    """
    print("\n🔔 Starting Profile Completion Reminder Job...")
    if force_send:
        print("   ⚡ FORCE MODE: Sending to all eligible users (bypassing daily limit)")
    
    # Check if reminders are enabled
    settings = ReminderSettings.query.first()
    if not settings or not settings.is_enabled:
        print("⚠️ Profile completion reminders are disabled.")
        return
    
    # Get all mentors and mentees
    mentors = User.query.filter_by(user_type="1").all()
    mentees = User.query.filter_by(user_type="2").all()
    
    print(f"📊 Found {len(mentors)} mentors and {len(mentees)} mentees")
    
    sent_count = 0
    skipped_count = 0
    
    for user_group, user_type, group_name in [(mentors, "1", "mentors"), (mentees, "2", "mentees")]:
        print(f"\n📧 Processing {group_name}...")
        
        for user in user_group:
            try:
                # Generate email
                email_data = generate_profile_completion_email(user.id, user_type)
                
                if not email_data:
                    # 100% complete or error, skip
                    skipped_count += 1
                    continue
                
                print(f"   📨 {user.name} ({user.email}) - {email_data['completion_percentage']}% complete")
                
                # Skip "already sent today" check if force_send is True
                if not force_send:
                    # Check if user already received reminder today
                    today = datetime.utcnow().date()
                    today_reminder = ProfileCompletionReminder.query.filter(
                        ProfileCompletionReminder.user_id == user.id,
                        ProfileCompletionReminder.user_type == user_type,
                        db.func.date(ProfileCompletionReminder.sent_at) == today
                    ).first()
                    
                    if today_reminder:
                        print(f"      ⏭️  Already sent today, skipping")
                        skipped_count += 1
                        continue
                
                # Send email
                success = send_email_reminder(
                    user.email,
                    email_data['subject'],
                    email_data['html_content']
                )
                
                if success:
                    # Save reminder log
                    reminder = ProfileCompletionReminder(
                        user_id=user.id,
                        user_type=user_type,
                        completion_percentage=email_data['completion_percentage'],
                        completed_fields=email_data['completed_fields'],
                        total_fields=email_data['total_fields'],
                        missing_fields=json.dumps(email_data['missing_fields']),
                        email_subject=email_data['subject'],
                        email_style=email_data['email_style'],
                        email_content=email_data['html_content'],
                        previous_percentage=email_data['previous_percentage']
                    )
                    db.session.add(reminder)
                    sent_count += 1
                    print(f"      ✅ Email sent!")
                else:
                    print(f"      ❌ Email sending failed")
                    skipped_count += 1
            except Exception as e:
                print(f"❌ Error processing user {user.id}: {str(e)}")
                import traceback
                traceback.print_exc()
                skipped_count += 1
        
        db.session.commit()
    
    # Update last run timestamp
    settings.last_run = datetime.utcnow()
    db.session.commit()
    
    print(f"\n✅ Reminder job completed: {sent_count} sent, {skipped_count} skipped")

# Initialize scheduler (will be started in a background worker in production)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler()

def init_scheduler():
    """Initialize and start the scheduler"""
    if not scheduler.running:
        # Get frequency from settings, default to 24 hours
        settings = ReminderSettings.query.first()
        frequency_hours = settings.frequency_hours if settings else 24
        
        scheduler.add_job(
            send_profile_completion_reminders,
            trigger=IntervalTrigger(hours=frequency_hours),
            id='profile_completion_reminder',
            name='Profile Completion Reminder',
            replace_existing=True
        )
        scheduler.start()
        print("✅ Profile Completion Reminder Scheduler initialized")

# Admin Routes for Reminder Management

@app.route("/admin/reminder_settings", methods=["GET", "POST"])
def admin_reminder_settings():
    """Admin page to manage reminder system"""
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))
    
    settings = ReminderSettings.query.first()
    if not settings:
        settings = ReminderSettings()
        db.session.add(settings)
        db.session.commit()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "update_settings":
            settings.is_enabled = request.form.get("is_enabled") == "on"
            settings.frequency_hours = int(request.form.get("frequency_hours", 24))
            settings.min_completion_for_reminder = int(request.form.get("min_completion_for_reminder", 0))
            db.session.commit()
            
            # Reinitialize scheduler with new frequency
            init_scheduler()
            flash("Reminder settings updated successfully!", "success")
        
        elif action == "trigger_now":
            send_profile_completion_reminders(force_send=True)
            flash("Profile completion reminders sent!", "success")
        
        return redirect(url_for("admin_reminder_settings"))
    
    # Get reminder statistics
    total_reminders_sent = ProfileCompletionReminder.query.count()
    reminders_today = ProfileCompletionReminder.query.filter(
        db.func.date(ProfileCompletionReminder.sent_at) == datetime.utcnow().date()
    ).count()
    
    return render_template(
        "admin/reminder_settings.html",
        show_sidebar=True,
        settings=settings,
        total_reminders_sent=total_reminders_sent,
        reminders_today=reminders_today
    )

@app.route("/admin/reminder_logs")
def admin_reminder_logs():
    """View history of sent reminders"""
    if "email" not in session or session.get("user_type") != "0":
        return redirect(url_for("signin"))
    
    page = request.args.get("page", 1, type=int)
    reminders = ProfileCompletionReminder.query.order_by(
        ProfileCompletionReminder.sent_at.desc()
    ).paginate(page=page, per_page=20)
    
    return render_template(
        "admin/reminder_logs.html",
        show_sidebar=True,
        reminders=reminders
    )

@app.route("/user/reminder_logs")
def user_reminder_logs():
    """User can view their own reminder history"""
    if "email" not in session:
        return redirect(url_for("signin"))
    
    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("signin"))
    user_type = session.get("user_type")
    
    reminders = ProfileCompletionReminder.query.filter_by(
        user_id=user.id,
        user_type=user_type
    ).order_by(ProfileCompletionReminder.sent_at.desc()).all()
    
    if user_type == "1":
        completion_info = calculate_mentor_profile_completion(user.id)
    elif user_type == "2":
        completion_info = calculate_mentee_profile_completion(user.id)
    else:
        completion_info = {'percentage': 100, 'missing_fields': [], 'completed_fields': 0, 'total_fields': 0}

    return render_template(
        "user/reminder_logs.html",
        show_sidebar=True,
        reminders=reminders,
        completion_percentage=completion_info.get('percentage', 0),
        completion_info=completion_info,
        user=user
    )


@app.route("/api/reminder/<int:reminder_id>/content")
def get_reminder_content(reminder_id):
    """API endpoint to get email content of a reminder"""
    reminder = ProfileCompletionReminder.query.get(reminder_id)
    
    if not reminder:
        return jsonify({"error": "Reminder not found"}), 404
    
    # Check authorization - admin or owner
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_type = session.get("user_type")
    current_user = User.query.filter_by(email=session["email"]).first()
    
    # Allow admin or the user themselves
    is_admin = user_type == "0"
    is_owner = reminder.user_id == current_user.id
    
    if not (is_admin or is_owner):
        return jsonify({"error": "Forbidden"}), 403
    
    # Get the user who received the reminder
    user = User.query.get(reminder.user_id)
    
    return jsonify({
        "recipient_name": user.name if user else "Unknown",
        "subject": reminder.email_subject,
        "content": reminder.email_content,
        "completion_percentage": reminder.completion_percentage,
        "email_style": reminder.email_style,
        "sent_at": reminder.sent_at.isoformat()
    })


# ============================================================
# RESOURCES HUB - NOTES
# ============================================================

def get_mentor_options_for_mentee(mentee_user):
    """
    Return a list of mentor dicts a mentee can call/tag in a note.
    Shows ONLY the active (accepted) mentors connected to this mentee.
    """
    mentors = []
    seen = set()

    accepted_requests = MentorshipRequest.query.filter_by(
        mentee_id=mentee_user.id,
        
        supervisor_status="approved",
        final_status="approved"
    ).all()

    for req in accepted_requests:
        if req.mentor and req.mentor.id not in seen:
            seen.add(req.mentor.id)
            mentors.append({
                "id": req.mentor.id,
                "name": req.mentor.name,
                "email": req.mentor.email,
                "is_active": True
            })

    return mentors


def _build_tagged_content(title, content, mentor_id, institution_id, mentee_tag_id, supervisor_tag_id):
    """Prepend tag metadata to content."""
    import json as _json
    tags = {}
    if mentor_id:
        tags["mentor"] = int(mentor_id)
    if institution_id:
        tags["inst"] = int(institution_id)
    if mentee_tag_id:
        tags["mentee"] = int(mentee_tag_id)
    if supervisor_tag_id:
        tags["supervisor"] = int(supervisor_tag_id)
    if tags:
        return _TAG_PREFIX + _json.dumps(tags) + "\n" + content
    return content


@app.route("/resources")
def resources_hub():
    """Resources Hub page: Notes panel where mentees, mentors, institutions, and supervisors can share and sync notes."""
    if "email" not in session:
        return redirect(url_for("signin"))

    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return redirect(url_for("signin"))

    user_type = session.get("user_type")
    tag_options = []
    institution_options = []
    mentee_tag_options = []
    supervisor_tag_options = []

    # Get active mentee IDs for mentor
    mentee_ids = set()
    if user_type == "1":
        mentee_ids = {r.mentee_id for r in MentorshipRequest.query.filter_by(
            mentor_id=user.id,
            supervisor_status="approved",
            final_status="approved"
        ).all()}

    user_inst_id = user.institution_id
    if user_type == "3" and not user_inst_id:
        inst_rec = Institution.query.filter_by(user_id=user.id).first()
        if inst_rec:
            user_inst_id = inst_rec.id

    if user_type == "2":
        tag_options = get_mentor_options_for_mentee(user)
        mentee_tag_options = [{"id": m.id, "name": m.name} for m in User.query.filter_by(user_type="2").all()]
        supervisor_tag_options = [{"id": m.id, "name": m.name} for m in User.query.filter_by(user_type="0").all()]
        if user.institution_id:
            inst = Institution.query.get(user.institution_id)
            if inst:
                institution_options = [{"id": inst.id, "name": inst.name}]

    elif user_type == "1":
        tag_options = [{"id": m.id, "name": m.name, "email": m.email} for m in User.query.filter_by(user_type="1").all()]
        mentee_tag_options = [{"id": m.id, "name": m.name} for m in User.query.filter_by(user_type="2").all()]
        supervisor_tag_options = [{"id": m.id, "name": m.name} for m in User.query.filter_by(user_type="0").all()]
        if user.institution_id:
            inst = Institution.query.get(user.institution_id)
            if inst:
                institution_options = [{"id": inst.id, "name": inst.name}]

    elif user_type == "3":
        tag_options = [{"id": m.id, "name": m.name, "email": m.email} for m in User.query.filter_by(user_type="1").all()]
        mentee_tag_options = [{"id": m.id, "name": m.name} for m in User.query.filter_by(user_type="2").all()]
        supervisor_tag_options = [{"id": m.id, "name": m.name} for m in User.query.filter_by(user_type="0").all()]
        inst_id_to_fetch = user.institution_id or user_inst_id
        if inst_id_to_fetch:
            inst = Institution.query.get(inst_id_to_fetch)
            if inst:
                institution_options = [{"id": inst.id, "name": inst.name}]

    else:
        # Supervisor
        tag_options = [{"id": m.id, "name": m.name, "email": m.email, "institution_id": m.institution_id} for m in User.query.filter_by(user_type="1").all()]
        mentee_tag_options = [{"id": m.id, "name": m.name, "institution_id": m.institution_id} for m in User.query.filter_by(user_type="2").all()]
        supervisor_tag_options = [{"id": m.id, "name": m.name} for m in User.query.filter_by(user_type="0").all()]
        institution_options = [{"id": inst.id, "name": inst.name} for inst in Institution.query.all()]

    # Query all notes and filter those that belong to or tag this user/account
    all_notes = ResourceNote.query.order_by(ResourceNote.updated_at.desc(), ResourceNote.created_at.desc()).all()
    notes = []
    for note in all_notes:
        # 1. Author can always see their own note
        if note.mentee_id == user.id:
            notes.append(note)
            continue

        # 2. Supervisor sees all notes
        if user_type == "0":
            notes.append(note)
            continue

        tags = note.tags_dict

        # 3. Tagged Mentor
        if user_type == "1" and (note.mentor_id == user.id or tags.get("mentor") == user.id):
            notes.append(note)
            continue

        # 4. Tagged Mentee
        if user_type == "2" and tags.get("mentee") == user.id:
            notes.append(note)
            continue

        # 5. Tagged Supervisor
        if tags.get("supervisor") == user.id:
            notes.append(note)
            continue

        # 6. Tagged Institution
        if user_type == "3" and user_inst_id:
            if note.institution_id == user_inst_id or tags.get("inst") == user_inst_id:
                notes.append(note)
                continue

        # 7. Mentors see notes from their active mentees
        if user_type == "1" and note.mentee_id in mentee_ids:
            notes.append(note)
            continue

    # Attach resolved entities for display and frontend interaction
    for n in notes:
        t = n.tags_dict
        m_id = n.mentor_id or t.get("mentor")
        n.tagged_mentor_user = User.query.get(int(m_id)) if m_id else None
        e_id = t.get("mentee")
        n.tagged_mentee_user = User.query.get(int(e_id)) if e_id else None
        s_id = t.get("supervisor")
        n.tagged_supervisor_user = User.query.get(int(s_id)) if s_id else None
        i_id = n.institution_id or t.get("inst")
        n.tagged_institution_obj = Institution.query.get(int(i_id)) if i_id else None

    return render_template(
        "resources_hub.html",
        notes=notes,
        tag_options=tag_options,
        institution_options=institution_options,
        mentee_tag_options=mentee_tag_options,
        supervisor_tag_options=supervisor_tag_options,
        user_type=user_type,
        can_write=True,
        current_user=user,
        now=datetime.utcnow(),
        show_sidebar=True,
        profile_complete=check_profile_complete(user.id, user_type) if user_type in ["0", "1", "2", "3"] else True
    )


@app.route("/notes/create", methods=["POST"])
def create_note():
    if "email" not in session:
        return jsonify({"error": "Please sign in first."}), 401

    user_type = session.get("user_type")
    if user_type not in ("0", "1", "2", "3"):
        return jsonify({"error": "Invalid user type."}), 403

    user = User.query.filter_by(email=session["email"]).first()
    if not user:
        return jsonify({"error": "User not found."}), 404

    title = (request.form.get("title") or "").strip()
    content = (request.form.get("content") or "").strip()
    mentor_id = request.form.get("mentor_id") or request.form.get("tag_mentor_id")
    institution_id = request.form.get("institution_id")
    mentee_tag_id = request.form.get("mentee_tag_id")
    supervisor_tag_id = request.form.get("supervisor_tag_id")

    if not title:
        return jsonify({"error": "Note title is required."}), 400
    if not content:
        return jsonify({"error": "Note content is required."}), 400

    mentor = None
    if mentor_id and str(mentor_id).isdigit():
        mentor = User.query.get(int(mentor_id))
        if not mentor or mentor.user_type != "1":
            return jsonify({"error": "Selected mentor is not valid."}), 400

    institution = None
    if institution_id and str(institution_id).isdigit():
        institution = Institution.query.get(int(institution_id))
        if not institution:
            return jsonify({"error": "Selected institution is not valid."}), 400
        if user.user_type != "0" and user.institution_id != institution.id:
            return jsonify({"error": "You can only tag your own institution."}), 403

    tagged_content = _build_tagged_content(title, content, mentor_id, institution_id, mentee_tag_id, supervisor_tag_id)

    note = ResourceNote(
        mentee_id=user.id,
        mentor_id=mentor.id if mentor else None,
        institution_id=institution.id if institution else None,
        title=title,
        content=tagged_content,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.session.add(note)
    db.session.commit()

    message = "Note saved."
    if mentor:
        message = f"Note saved. {mentor.name} has been called/tagged."
    if institution:
        message += f" Institution {institution.name} tagged."

    return jsonify({"success": True, "message": message})


@app.route("/notes/update/<int:note_id>", methods=["POST"])
def update_note(note_id):
    if "email" not in session:
        return jsonify({"error": "Please sign in first."}), 401

    note = ResourceNote.query.get(note_id)
    if not note:
        return jsonify({"error": "Note not found."}), 404

    user = User.query.filter_by(email=session["email"]).first()
    user_type = session.get("user_type")
    if not user:
        return jsonify({"error": "User not found."}), 404

    tags = note.tags_dict
    is_author = (note.mentee_id == user.id)
    is_tagged_mentor = (note.mentor_id == user.id or tags.get("mentor") == user.id)
    is_tagged_mentee = (tags.get("mentee") == user.id)
    is_tagged_supervisor = (tags.get("supervisor") == user.id or user_type == "0")
    user_inst_id = user.institution_id
    if user_type == "3" and not user_inst_id:
        inst_rec = Institution.query.filter_by(user_id=user.id).first()
        if inst_rec:
            user_inst_id = inst_rec.id
    is_tagged_institution = bool(user_type == "3" and user_inst_id and (note.institution_id == user_inst_id or tags.get("inst") == user_inst_id))

    active_mentee_ids = set()
    if user_type == "1":
        active_mentee_ids = {r.mentee_id for r in MentorshipRequest.query.filter_by(
            mentor_id=user.id,
            supervisor_status="approved",
            final_status="approved"
        ).all()}
    is_assigned_mentor = bool(user_type == "1" and note.mentee_id in active_mentee_ids)

    if not (is_author or is_tagged_mentor or is_tagged_mentee or is_tagged_supervisor or is_tagged_institution or is_assigned_mentor):
        return jsonify({"error": "You do not have permission to edit this note."}), 403

    title = (request.form.get("title") or "").strip()
    content = (request.form.get("content") or "").strip()

    if not title:
        return jsonify({"error": "Note title is required."}), 400
    if not content:
        return jsonify({"error": "Note content is required."}), 400

    existing_tags = dict(note.tags_dict)

    if "mentor_id" in request.form:
        mid = request.form.get("mentor_id")
        if mid and str(mid).isdigit():
            mentor = User.query.get(int(mid))
            if mentor and mentor.user_type == "1":
                note.mentor_id = mentor.id
                existing_tags["mentor"] = mentor.id
        elif mid == "":
            note.mentor_id = None
            existing_tags.pop("mentor", None)
    elif note.mentor_id:
        existing_tags["mentor"] = note.mentor_id

    if "institution_id" in request.form:
        iid = request.form.get("institution_id")
        if iid and str(iid).isdigit():
            inst = Institution.query.get(int(iid))
            if inst:
                note.institution_id = inst.id
                existing_tags["inst"] = inst.id
        elif iid == "":
            note.institution_id = None
            existing_tags.pop("inst", None)
    elif note.institution_id:
        existing_tags["inst"] = note.institution_id

    if "mentee_tag_id" in request.form:
        eid = request.form.get("mentee_tag_id")
        if eid and str(eid).isdigit():
            existing_tags["mentee"] = int(eid)
        elif eid == "":
            existing_tags.pop("mentee", None)

    if "supervisor_tag_id" in request.form:
        sid = request.form.get("supervisor_tag_id")
        if sid and str(sid).isdigit():
            existing_tags["supervisor"] = int(sid)
        elif sid == "":
            existing_tags.pop("supervisor", None)

    # Sync columns and tags dictionary
    if existing_tags.get("mentor"):
        note.mentor_id = existing_tags["mentor"]
    else:
        note.mentor_id = None

    if existing_tags.get("inst"):
        note.institution_id = existing_tags["inst"]
    else:
        note.institution_id = None

    note.title = title
    import json as _json
    note.content = (_TAG_PREFIX + _json.dumps(existing_tags) + "\n" + content) if existing_tags else content
    note.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"success": True, "message": "Note updated successfully."})


@app.route("/notes/delete/<int:note_id>", methods=["POST"])
def delete_note(note_id):
    if "email" not in session:
        return jsonify({"error": "Please sign in first."}), 401

    note = ResourceNote.query.get(note_id)
    if not note:
        return jsonify({"error": "Note not found."}), 404

    user = User.query.filter_by(email=session["email"]).first()
    user_type = session.get("user_type")
    if not user or (note.mentee_id != user.id and user_type != "0"):
        return jsonify({"error": "You can only delete your own notes."}), 403

    db.session.delete(note)
    db.session.commit()

    return jsonify({"success": True, "message": "Note deleted successfully."})


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        try:
            init_scheduler()
        except Exception as e:
            print(f"⚠️ Could not initialize scheduler: {e}")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
