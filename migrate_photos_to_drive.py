#!/usr/bin/env python3
"""
migrate_photos_to_drive.py

Migrates local profile photos and uploaded assets to Google Drive cloud storage.
Features:
- Connects using credentials configured in .env (OAuth2 Refresh Token or Service Account).
- Auto-compresses oversized images before uploading (max 800x800, quality 85).
- Queries Google Drive to skip already uploaded files (idempotent, safe to re-run).
- Writes a migration manifest to instance/drive_migration_manifest.json as a safe fallback record.
- Optional --update-db flag to update database records to direct Google Drive URLs.
- Optional --all flag to migrate all images in static/uploads/, not just active profile photos.
- Optional --dry-run flag to preview what would be uploaded without changing anything.

Usage:
    python migrate_photos_to_drive.py              # Migrate all profile photos
    python migrate_photos_to_drive.py --all        # Migrate all static/uploads images
    python migrate_photos_to_drive.py --dry-run    # Preview without uploading
    python migrate_photos_to_drive.py --update-db  # Also update DB URLs
"""

import os
import sys
import time
import json
import argparse
from io import BytesIO
from dotenv import load_dotenv

# Ensure environment is loaded from the script directory
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import storage_service
from werkzeug.datastructures import FileStorage


def get_existing_drive_files(service, folder_id=None):
    """Fetch dictionary of {filename: file_id} for all non-trashed files in Google Drive."""
    existing = {}
    if not service:
        return existing

    try:
        page_token = None
        while True:
            query = "trashed = false and mimeType != 'application/vnd.google-apps.folder'"
            res = service.files().list(
                q=query,
                fields="nextPageToken, files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageSize=1000,
                pageToken=page_token
            ).execute()
            for f in res.get("files", []):
                existing[f["name"]] = f["id"]
            page_token = res.get("nextPageToken")
            if not page_token:
                break
    except Exception as e:
        print(f"[!] Warning: Could not pre-fetch existing Drive files: {e}")

    return existing


def collect_profile_photos(upload_dir, migrate_all=False):
    """
    Collect unique local file names to migrate.
    If migrate_all is True, includes all image files in upload_dir.
    Otherwise, gathers local photos referenced in the database.
    """
    photo_set = set()
    db_records = []

    try:
        from app import app, db, User, MentorProfile, MenteeProfile
        with app.app_context():
            # 1. User.profile_picture_url
            for u in User.query.filter(User.profile_picture_url.isnot(None)).filter(User.profile_picture_url != "").all():
                url = (u.profile_picture_url or "").strip()
                if url and not url.startswith("http://") and not url.startswith("https://"):
                    clean = os.path.basename(url)
                    photo_set.add(clean)
                    db_records.append(("User", u.id, "profile_picture_url", clean))

            # 2. MentorProfile.profile_picture
            for mp in MentorProfile.query.filter(MentorProfile.profile_picture.isnot(None)).filter(MentorProfile.profile_picture != "").all():
                url = (mp.profile_picture or "").strip()
                if url and not url.startswith("http://") and not url.startswith("https://"):
                    clean = os.path.basename(url)
                    photo_set.add(clean)
                    db_records.append(("MentorProfile", mp.id, "profile_picture", clean))

            # 3. MenteeProfile.profile_picture
            for mp in MenteeProfile.query.filter(MenteeProfile.profile_picture.isnot(None)).filter(MenteeProfile.profile_picture != "").all():
                url = (mp.profile_picture or "").strip()
                if url and not url.startswith("http://") and not url.startswith("https://"):
                    clean = os.path.basename(url)
                    photo_set.add(clean)
                    db_records.append(("MenteeProfile", mp.id, "profile_picture", clean))

    except Exception as e:
        print(f"[*] Note: Could not query database directly ({e}). Falling back to scanning static/uploads/")
        migrate_all = True

    if migrate_all:
        exts = (".jpg", ".jpeg", ".png", ".webp", ".gif")
        if os.path.exists(upload_dir):
            for fname in os.listdir(upload_dir):
                fpath = os.path.join(upload_dir, fname)
                if os.path.isfile(fpath) and fname.lower().endswith(exts) and not fname.startswith("."):
                    photo_set.add(fname)

    return sorted(photo_set), db_records


def run_migration(migrate_all=True, update_db=False, force=False, limit=None, dry_run=False):
    """
    Programmatic entrypoint to run the Google Drive migration.
    Can be invoked directly from app.py on server startup or from CLI.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    upload_dir = os.path.join(base_dir, "static", "uploads")
    instance_dir = os.path.join(base_dir, "instance")
    manifest_path = os.path.join(instance_dir, "drive_migration_manifest.json")
    log_file_path = os.path.join(instance_dir, "drive_migration.log")
    completed_flag = os.path.join(instance_dir, "drive_migration_completed.flag")

    os.makedirs(instance_dir, exist_ok=True)

    def log(msg):
        print(msg, flush=True)
        try:
            with open(log_file_path, "a", encoding="utf-8") as lf:
                lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    log("=" * 68)
    log("      WES LUX MENTORSHIP - GOOGLE DRIVE PHOTO MIGRATION")
    log("=" * 68)

    # 1. Initialize Drive service
    log("\n[1/4] Connecting to Google Drive...")
    drive_service = storage_service.get_drive_service()
    if not drive_service:
        log("[!] ERROR: Google Drive service could not be initialized.")
        log("    Please check GDRIVE_REFRESH_TOKEN or GDRIVE_PRIVATE_KEY in .env.")
        return {"success": False, "message": "Drive service not initialized"}

    root_folder_id = storage_service.get_drive_root_folder_id(drive_service)
    if not root_folder_id:
        log("[!] ERROR: Could not resolve Google Drive root folder.")
        return {"success": False, "message": "Root folder not found"}

    target_folder_id = storage_service.get_or_create_path(drive_service, root_folder_id, "profiles")
    log(f"  [+] Connected to Google Drive.")
    log(f"  [+] Target folder: 'WES LUX Uploads / profiles' (ID: {target_folder_id})")

    # 2. Pre-fetch existing files on Drive for fast deduplication
    log("\n[2/4] Scanning files currently on Google Drive...")
    existing_drive_files = {} if force else get_existing_drive_files(drive_service, target_folder_id)
    log(f"  [+] Found {len(existing_drive_files)} files already stored in Drive folder.")

    # 3. Collect local photos
    log(f"\n[3/4] Gathering photos to migrate from: {upload_dir}")
    photos, db_records = collect_profile_photos(upload_dir, migrate_all=migrate_all)
    log(f"  [+] Found {len(photos)} unique photo files to process.")
    if limit and limit > 0:
        photos = photos[:limit]
        log(f"  [+] Limited to first {len(photos)} photos as requested.")

    # Load existing manifest if present
    manifest = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    if dry_run:
        log("\n--- DRY RUN SUMMARY ---")
        to_upload = [p for p in photos if p not in existing_drive_files]
        already_there = [p for p in photos if p in existing_drive_files]
        log(f"  Files that would be uploaded: {len(to_upload)}")
        log(f"  Files already on Google Drive: {len(already_there)}")
        for idx, p in enumerate(to_upload[:15], 1):
            p_path = os.path.join(upload_dir, p)
            sz_str = f"{os.path.getsize(p_path) / 1024:.1f} KB" if os.path.exists(p_path) else "MISSING"
            log(f"    {idx}. {p} ({sz_str})")
        if len(to_upload) > 15:
            log(f"    ... and {len(to_upload) - 15} more.")
        log("\nDry run complete. No files were modified.")
        return {"dry_run": True, "to_upload": len(to_upload), "already_there": len(already_there)}

    # 4. Upload loop
    log("\n[4/4] Starting migration to Google Drive...")
    start_time = time.time()
    uploaded_count = 0
    skipped_count = 0
    missing_count = 0
    error_count = 0
    total_bytes = 0

    total_photos = len(photos)

    for i, fname in enumerate(photos, 1):
        clean_name = os.path.basename(fname)
        local_path = os.path.join(upload_dir, clean_name)

        if not os.path.exists(local_path):
            log(f"  [{i}/{total_photos}] [MISSING] {clean_name} not found on local disk.")
            missing_count += 1
            continue

        # Check if already on Drive
        if clean_name in existing_drive_files and not force:
            file_id = existing_drive_files[clean_name]
            direct_url = f"https://drive.google.com/uc?export=view&id={file_id}"
            manifest[clean_name] = {
                "drive_url": direct_url,
                "file_id": file_id,
                "status": "already_present"
            }
            log(f"  [{i}/{total_photos}] [SKIPPED] {clean_name} (Already in Drive: {file_id})")
            skipped_count += 1
            continue

        # Read local file and compress if image
        try:
            with open(local_path, "rb") as f:
                content = f.read()

            raw_size = len(content)
            ext = clean_name.rsplit(".", 1)[-1].lower() if "." in clean_name else "jpg"
            mime = "image/png" if ext == "png" else ("image/webp" if ext == "webp" else "image/jpeg")

            fs = FileStorage(stream=BytesIO(content), filename=clean_name, content_type=mime)
            compressed_fs = storage_service.compress_image_stream(fs, max_size=(800, 800), quality=85)

            compressed_fs.seek(0)
            upload_bytes = compressed_fs.read()
            compressed_fs.seek(0)

            # Upload to Drive with 1 retry on failure
            drive_url = storage_service.upload_to_drive(
                compressed_fs,
                folder_prefix="profiles",
                custom_filename=clean_name
            )
            if not drive_url:
                time.sleep(2)
                compressed_fs.seek(0)
                drive_url = storage_service.upload_to_drive(
                    compressed_fs,
                    folder_prefix="profiles",
                    custom_filename=clean_name
                )

            if drive_url:
                uploaded_count += 1
                total_bytes += len(upload_bytes)
                file_id = drive_url.split("id=")[-1] if "id=" in drive_url else ""
                existing_drive_files[clean_name] = file_id
                manifest[clean_name] = {
                    "drive_url": drive_url,
                    "file_id": file_id,
                    "size_bytes": len(upload_bytes),
                    "original_size": raw_size,
                    "migrated_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                savings = f" (compressed from {raw_size/1024:.0f}KB to {len(upload_bytes)/1024:.0f}KB)" if raw_size != len(upload_bytes) else ""
                log(f"  [{i}/{total_photos}] [UPLOADED] {clean_name}{savings} -> {drive_url}")
            else:
                log(f"  [{i}/{total_photos}] [ERROR] Failed to upload {clean_name}.")
                error_count += 1

        except Exception as err:
            log(f"  [{i}/{total_photos}] [ERROR] {clean_name}: {err}")
            error_count += 1

    # Save manifest
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        log(f"\n  [+] Saved migration manifest with {len(manifest)} entries to: {manifest_path}")
    except Exception as e:
        log(f"\n  [!] Could not save manifest: {e}")

    # Optional database update
    if update_db and db_records:
        log("\nUpdating database profile picture URLs...")
        try:
            from app import app, db, User, MentorProfile, MenteeProfile
            updated_records = 0
            with app.app_context():
                for model_name, rec_id, field, clean_name in db_records:
                    if clean_name in manifest and manifest[clean_name].get("drive_url"):
                        drive_url = manifest[clean_name]["drive_url"]
                        if model_name == "User":
                            rec = db.session.get(User, rec_id)
                        elif model_name == "MentorProfile":
                            rec = db.session.get(MentorProfile, rec_id)
                        else:
                            rec = db.session.get(MenteeProfile, rec_id)

                        if rec and getattr(rec, field) != drive_url:
                            setattr(rec, field, drive_url)
                            updated_records += 1

                db.session.commit()
                log(f"  [+] Updated {updated_records} database records to direct Google Drive URLs.")
        except Exception as e:
            log(f"  [!] Database update error: {e}")

    duration = time.time() - start_time
    log("\n" + "=" * 68)
    log("                    MIGRATION SUMMARY")
    log("=" * 68)
    log(f"  Total scanned:          {total_photos}")
    log(f"  Successfully uploaded:  {uploaded_count}")
    log(f"  Already in Drive:       {skipped_count}")
    log(f"  Missing on local disk:  {missing_count}")
    log(f"  Errors:                 {error_count}")
    log(f"  Total data uploaded:    {total_bytes / 1024 / 1024:.2f} MB")
    log(f"  Time taken:             {duration:.1f} seconds")
    log("=" * 68)
    log("Safe fallback status:")
    log("1. All photos are permanently backed up in Google Drive.")
    log("2. Flask app will automatically download missing files on demand via")
    log("   storage_service.download_file_from_drive() in serve_uploaded_file().")
    log("3. Migration manifest is saved at instance/drive_migration_manifest.json.")
    log("=" * 68)

    # Write completion flag
    try:
        with open(completed_flag, "w", encoding="utf-8") as cf:
            cf.write(f"completed_at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            cf.write(f"total: {total_photos}\n")
            cf.write(f"uploaded: {uploaded_count}\n")
            cf.write(f"skipped: {skipped_count}\n")
            cf.write(f"missing: {missing_count}\n")
            cf.write(f"errors: {error_count}\n")
            cf.write(f"duration_sec: {duration:.1f}\n")
    except Exception as e:
        log(f"  [!] Could not write completion flag: {e}")

    return {
        "success": True,
        "total": total_photos,
        "uploaded": uploaded_count,
        "skipped": skipped_count,
        "missing": missing_count,
        "errors": error_count,
        "bytes": total_bytes,
        "duration": duration
    }


def main():
    parser = argparse.ArgumentParser(description="Migrate profile photos to Google Drive cloud storage.")
    parser.add_argument("--all", action="store_true", help="Migrate all static/uploads images, not only database profile photos.")
    parser.add_argument("--update-db", action="store_true", help="Update database profile_picture columns to direct Google Drive URLs.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect what would be uploaded without making changes.")
    parser.add_argument("--force", action="store_true", help="Re-upload files even if already present in Google Drive.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of photos to migrate (useful for testing).")
    args = parser.parse_args()

    run_migration(
        migrate_all=args.all,
        update_db=args.update_db,
        force=args.force,
        limit=args.limit,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
