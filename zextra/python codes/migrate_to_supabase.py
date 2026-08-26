import os
import sys
from dotenv import load_dotenv

# Force UTF-8 output for Windows console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv(override=True)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Import exact app models from app.py
from app import (
    db, app,
    User, PasswordResetOTP, MentorProfile, MenteeProfile, SupervisorProfile,
    Institution, ProfileCompletionReminder, ReminderSettings, MentorshipRequest,
    Notification, MeetingRequest, MasterTask, MenteeTask, PersonalTask,
    TaskRating, ChatConversation, ChatMessage, ResourceNote
)

# 1. Source SQLite Engine & Session
sqlite_db_path = os.path.join(app.root_path, "mentors_connect.db")
if not os.path.exists(sqlite_db_path) or os.path.getsize(sqlite_db_path) == 0:
    sqlite_db_path = os.path.join(app.root_path, "instance", "mentors_connect.db")

print(f"📂 Using Source SQLite Database File: {sqlite_db_path} (Size: {os.path.getsize(sqlite_db_path)} bytes)")

sqlite_engine = create_engine(f"sqlite:///{sqlite_db_path}")
SQLiteSession = sessionmaker(bind=sqlite_engine)
sqlite_session = SQLiteSession()

# 2. Target Supabase Engine & Session
supabase_url = os.environ.get("DATABASE_URL")
if supabase_url.startswith("postgres://"):
    supabase_url = supabase_url.replace("postgres://", "postgresql://", 1)

supabase_engine = create_engine(supabase_url)
SupabaseSession = sessionmaker(bind=supabase_engine)
supabase_session = SupabaseSession()

MODELS_TO_MIGRATE = [
    Institution,
    User,
    PasswordResetOTP,
    MentorProfile,
    MenteeProfile,
    SupervisorProfile,
    MentorshipRequest,
    Notification,
    MeetingRequest,
    MasterTask,
    MenteeTask,
    PersonalTask,
    TaskRating,
    ChatConversation,
    ChatMessage,
    ResourceNote,
    ProfileCompletionReminder,
    ReminderSettings
]

def migrate():
    print("🚀 Starting Data Migration from SQLite to Supabase...")
    
    with app.app_context():
        # Ensure target Supabase tables exist
        db.create_all()

    # Disable foreign key checks for bulk import in PostgreSQL session
    try:
        supabase_session.execute(text("SET session_replication_role = 'replica';"))
        supabase_session.commit()
    except Exception as e:
        print(f"Notice: Could not set session_replication_role: {e}")

    for model in MODELS_TO_MIGRATE:
        model_name = model.__name__
        print(f"\n📦 Migrating table: {model_name}...")
        
        try:
            records = sqlite_session.query(model).all()
            print(f"   Found {len(records)} records in SQLite.")
            
            migrated_count = 0
            for record in records:
                # Check if record already exists in Supabase by primary key ID
                existing = supabase_session.query(model).filter_by(id=record.id).first()
                if not existing:
                    # Copy column attributes
                    attrs = {c.name: getattr(record, c.name) for c in record.__table__.columns}
                    new_obj = model(**attrs)
                    supabase_session.add(new_obj)
                    migrated_count += 1
            
            supabase_session.commit()
            print(f"   ✅ Successfully migrated {migrated_count} new records to Supabase.")
            
        except Exception as e:
            supabase_session.rollback()
            err_msg = str(e)
            if "no such table" in err_msg.lower():
                print(f"   ℹ️ Table '{model_name}' does not exist in SQLite database. Skipping.")
            else:
                print(f"   ❌ Error migrating {model_name}: {e}")

    # Re-enable foreign key checks
    try:
        supabase_session.execute(text("SET session_replication_role = 'origin';"))
        supabase_session.commit()
    except Exception as e:
        pass

    print("\n🎉 ALL DATA MIGRATED SUCCESSFULLY TO SUPABASE!")

if __name__ == "__main__":
    migrate()