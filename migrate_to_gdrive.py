"""
Migration Script: Local Static Uploads -> Google Drive Folder Hierarchy.
Transfers existing profile pictures and criminal certificates from static/uploads
to Google Drive inside the persona / account ID folder structure and updates the database.
"""

import os
import io
import sys
import logging
from dotenv import load_dotenv

load_dotenv(".env")

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from app import app, db, User, MentorProfile, MenteeProfile, Institution, SupervisorProfile
import storage_service


def migrate_file(local_filename, folder_prefix):
    """Upload existing local file to Drive under folder_prefix and return direct URL."""
    if not local_filename:
        return None

    filename = os.path.basename(local_filename.strip())

    # Skip if already a full web/cloud URL
    if filename.startswith("http://") or filename.startswith("https://"):
        return filename

    local_path = os.path.join(app.root_path, "static", "uploads", filename)
    if not os.path.exists(local_path):
        # File not present on disk
        return None

    class LocalFileStorage:
        def __init__(self, path, name):
            self.path = path
            self.filename = name
            self.content_type = None

        def read(self):
            with open(self.path, "rb") as f:
                return f.read()

        def seek(self, offset):
            pass

    file_obj = LocalFileStorage(local_path, filename)
    url = storage_service.upload_to_drive(file_obj, folder_prefix=folder_prefix, custom_filename=filename)
    return url


def run_migration():
    """Migrates all records across mentors, mentees, institutions, supervisors."""
    logger.info("Starting cloud migration to Google Drive...")

    service = storage_service.get_drive_service()
    if not service:
        logger.error("Google Drive service could not be initialized. Please check credentials.")
        return

    root_folder = os.getenv("GDRIVE_FOLDER_ID")
    logger.info("Target Root Drive Folder ID: %s", root_folder)

    with app.app_context():
        # 1. Mentors
        mentors = MentorProfile.query.all()
        logger.info("Found %d mentor profiles to inspect.", len(mentors))
        for m in mentors:
            # Profile Picture
            if m.profile_picture and not m.profile_picture.startswith("http"):
                new_url = migrate_file(m.profile_picture, f"mentors/{m.user_id}")
                if new_url:
                    logger.info("Migrated Mentor %d picture -> %s", m.user_id, new_url)
                    m.profile_picture = new_url

            # Criminal Certificate
            if hasattr(m, 'criminal_certificate') and m.criminal_certificate and not m.criminal_certificate.startswith("http"):
                new_cert_url = migrate_file(m.criminal_certificate, f"mentors/{m.user_id}")
                if new_cert_url:
                    logger.info("Migrated Mentor %d certificate -> %s", m.user_id, new_cert_url)
                    m.criminal_certificate = new_cert_url

        # 2. Mentees
        mentees = MenteeProfile.query.all()
        logger.info("Found %d mentee profiles to inspect.", len(mentees))
        for me in mentees:
            if me.profile_picture and not me.profile_picture.startswith("http"):
                new_url = migrate_file(me.profile_picture, f"mentees/{me.user_id}")
                if new_url:
                    logger.info("Migrated Mentee %d picture -> %s", me.user_id, new_url)
                    me.profile_picture = new_url

        # 3. Institutions
        institutions = Institution.query.all()
        logger.info("Found %d institutions to inspect.", len(institutions))
        for inst in institutions:
            if inst.profile_picture and not inst.profile_picture.startswith("http"):
                new_url = migrate_file(inst.profile_picture, f"institutions/{inst.id}")
                if new_url:
                    logger.info("Migrated Institution %d logo -> %s", inst.id, new_url)
                    inst.profile_picture = new_url

        # 4. Supervisors
        supervisors = SupervisorProfile.query.all()
        logger.info("Found %d supervisor profiles to inspect.", len(supervisors))
        for s in supervisors:
            if s.profile_picture and not s.profile_picture.startswith("http"):
                new_url = migrate_file(s.profile_picture, f"supervisors/{s.user_id}")
                if new_url:
                    logger.info("Migrated Supervisor %d picture -> %s", s.user_id, new_url)
                    s.profile_picture = new_url

        try:
            db.session.commit()
            logger.info("All migrated URLs committed to the database successfully!")
        except Exception as e:
            db.session.rollback()
            logger.error("Failed committing migration to database: %s", e)


if __name__ == "__main__":
    run_migration()
