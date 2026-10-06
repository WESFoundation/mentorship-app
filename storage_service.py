"""
Google Drive and Cloud Storage Service for Mentorship Application.
Supports Google Drive folders using OAuth2 user credentials (refresh token)
or Service Account credentials, and falls back gracefully to local static/uploads storage
if cloud storage is not configured or unavailable.
"""

import os
import io
import logging
import uuid
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf"}

_drive_service = None
_drive_initialized = False
_root_folder_id = None
_folder_cache = {}


def is_allowed_file(filename):
    """Check if file extension is allowed."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_drive_service():
    """
    Initialize and return Google Drive service.
    First tries OAuth2 Refresh Token (e.g. for bucket.wes.lux.admin.portal@weslux.lu),
    then falls back to Service Account credentials.
    """
    global _drive_service, _drive_initialized

    if _drive_initialized:
        return _drive_service

    _drive_initialized = True

    # 1. Try OAuth2 Refresh Token credentials (primary for user bucket drive)
    refresh_token = os.getenv("GDRIVE_REFRESH_TOKEN")
    client_id = os.getenv("GDRIVE_CLIENT_ID")
    client_secret = os.getenv("GDRIVE_CLIENT_SECRET")

    if refresh_token and client_id and client_secret:
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials(
                None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret
            )
            svc = build("drive", "v3", credentials=creds)
            # Verify credentials with a lightweight call
            about = svc.about().get(fields="user(emailAddress, displayName)").execute()
            user_info = about.get("user", {})
            logger.info("Google Drive service initialized via OAuth2 Refresh Token: %s (%s)",
                        user_info.get("emailAddress"), user_info.get("displayName"))
            _drive_service = svc
            return _drive_service
        except Exception as e:
            logger.warning("Failed to initialize Google Drive with OAuth2 Refresh Token: %s", e)

    # 2. Try Service Account credentials
    private_key = (
        os.getenv("GDRIVE_PRIVATE_KEY")
        or os.getenv("GOOGLE_PRIVATE_KEY")
        or os.getenv("GCP_PRIVATE_KEY")
    )
    client_email = (
        os.getenv("GDRIVE_CLIENT_EMAIL")
        or os.getenv("GOOGLE_CLIENT_EMAIL")
        or os.getenv("GCP_CLIENT_EMAIL")
    )
    project_id = (
        os.getenv("GDRIVE_PROJECT_ID")
        or os.getenv("GOOGLE_PROJECT_ID")
        or os.getenv("GCP_PROJECT_ID")
    )

    if private_key and client_email:
        try:
            from googleapiclient.discovery import build
            from google.oauth2 import service_account

            raw_key = private_key.strip().strip('"').strip("'")
            if "\\n" in raw_key:
                formatted_key = raw_key.replace("\\n", "\n")
            elif "\n" in raw_key:
                formatted_key = raw_key
            else:
                header = "-----BEGIN PRIVATE KEY-----"
                footer = "-----END PRIVATE KEY-----"
                if header in raw_key and footer in raw_key:
                    body = raw_key.replace(header, "").replace(footer, "").strip().replace(" ", "")
                    chunks = [body[i:i+64] for i in range(0, len(body), 64)]
                    formatted_key = f"{header}\n" + "\n".join(chunks) + f"\n{footer}\n"
                else:
                    formatted_key = raw_key

            info = {
                "type": "service_account",
                "project_id": project_id or "inbound-lexicon-499018-r2",
                "private_key_id": os.getenv("GDRIVE_PRIVATE_KEY_ID") or os.getenv("GOOGLE_PRIVATE_KEY_ID", ""),
                "private_key": formatted_key,
                "client_email": client_email,
                "client_id": os.getenv("GDRIVE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID", ""),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{client_email}",
            }
            SCOPES = [
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/drive.file"
            ]
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
            svc = build("drive", "v3", credentials=creds)
            logger.info("Google Drive service initialized via Service Account: %s", client_email)
            _drive_service = svc
            return _drive_service
        except Exception as e:
            logger.warning("Failed to initialize Google Drive with Service Account: %s", e)

    logger.info("Google Drive not configured or credentials failed. Falling back to local storage.")
    _drive_service = None
    return None


def get_drive_root_folder_id(service):
    """
    Resolve the root target folder in Google Drive.
    Verifies GDRIVE_FOLDER_ID from environment; if missing or 404,
    locates or creates the 'WES LUX Uploads' folder.
    """
    global _root_folder_id

    if _root_folder_id:
        return _root_folder_id

    if not service:
        return None

    # Check configured env variable
    env_folder_id = os.getenv("GDRIVE_FOLDER_ID")
    if env_folder_id:
        try:
            folder = service.files().get(
                fileId=env_folder_id,
                supportsAllDrives=True,
                fields="id, name, mimeType"
            ).execute()
            if folder and folder.get("mimeType") == "application/vnd.google-apps.folder":
                _root_folder_id = env_folder_id
                logger.info("Using configured GDRIVE_FOLDER_ID: %s (%s)", _root_folder_id, folder.get("name"))
                return _root_folder_id
        except Exception as e:
            logger.warning("Configured GDRIVE_FOLDER_ID '%s' not accessible (%s). Searching for 'WES LUX Uploads'...", env_folder_id, e)

    # Search for 'WES LUX Uploads' folder
    try:
        query = "mimeType = 'application/vnd.google-apps.folder' and name = 'WES LUX Uploads' and trashed = false"
        res = service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = res.get("files", [])
        if files:
            _root_folder_id = files[0]["id"]
            logger.info("Found existing 'WES LUX Uploads' folder: %s", _root_folder_id)
            return _root_folder_id

        # Fallback: create 'WES LUX Uploads' folder
        meta = {
            "name": "WES LUX Uploads",
            "mimeType": "application/vnd.google-apps.folder"
        }
        created = service.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
        _root_folder_id = created.get("id")
        logger.info("Created new 'WES LUX Uploads' folder: %s", _root_folder_id)
        return _root_folder_id
    except Exception as e:
        logger.error("Error finding or creating root uploads folder in Drive: %s", e)
        return None


def get_or_create_subfolder(service, parent_id, folder_name):
    """Find or create a subfolder with given name under parent_id in Google Drive."""
    cache_key = (parent_id, folder_name)
    if cache_key in _folder_cache:
        return _folder_cache[cache_key]

    try:
        query = (
            f"'{parent_id}' in parents and "
            f"name = '{folder_name}' and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"trashed = false"
        )
        res = service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = res.get("files", [])
        if files:
            subfolder_id = files[0]["id"]
            _folder_cache[cache_key] = subfolder_id
            return subfolder_id

        meta = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]
        }
        folder = service.files().create(
            body=meta,
            fields="id",
            supportsAllDrives=True
        ).execute()
        subfolder_id = folder.get("id")
        _folder_cache[cache_key] = subfolder_id
        logger.info("Created subfolder '%s' (ID: %s)", folder_name, subfolder_id)
        return subfolder_id
    except Exception as e:
        logger.warning("Error getting/creating subfolder '%s': %s", folder_name, e)
        return parent_id


def get_or_create_path(service, root_folder_id, folder_path):
    """Resolve or create nested folder path in Google Drive (e.g. 'mentors/12')."""
    if not folder_path or not str(folder_path).strip():
        return root_folder_id

    current_parent = root_folder_id
    segments = [s.strip() for s in str(folder_path).replace("\\", "/").split("/") if s.strip()]

    for segment in segments:
        current_parent = get_or_create_subfolder(service, current_parent, segment)

    return current_parent


def upload_to_drive(file_storage, folder_prefix=None, custom_filename=None):
    """
    Upload a file to Google Drive folder using authenticated service.
    Places files inside nested subfolders (e.g. mentors/{id}/).
    Sets public read permissions and returns direct downloadable HTTPS URL.
    """
    service = get_drive_service()
    if not service:
        return None

    root_folder_id = get_drive_root_folder_id(service)
    if not root_folder_id:
        return None

    try:
        from googleapiclient.http import MediaIoBaseUpload

        target_folder_id = get_or_create_path(service, root_folder_id, folder_prefix)

        orig_name = secure_filename(file_storage.filename)
        ext = orig_name.rsplit(".", 1)[1].lower() if "." in orig_name else "jpg"

        if custom_filename:
            file_name = custom_filename
        else:
            file_name = f"{uuid.uuid4().hex[:12]}_{orig_name}"

        content_type = getattr(file_storage, "content_type", None)
        if not content_type:
            if ext in {"png"}:
                content_type = "image/png"
            elif ext in {"jpg", "jpeg"}:
                content_type = "image/jpeg"
            elif ext in {"gif"}:
                content_type = "image/gif"
            elif ext in {"pdf"}:
                content_type = "application/pdf"
            else:
                content_type = "application/octet-stream"

        file_metadata = {
            "name": file_name,
            "parents": [target_folder_id]
        }

        file_storage.seek(0)
        file_bytes = file_storage.read()
        file_storage.seek(0)

        if not file_bytes:
            logger.warning("Empty file passed to upload_to_drive: %s", file_name)
            return None

        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=content_type, resumable=True)

        drive_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink, webContentLink",
            supportsAllDrives=True
        ).execute()

        file_id = drive_file.get("id")

        # Grant public link reading permission
        try:
            service.permissions().create(
                fileId=file_id,
                body={"role": "reader", "type": "anyone"},
                supportsAllDrives=True
            ).execute()
        except Exception as perm_err:
            logger.warning("Could not set anyone reader permission on file %s: %s", file_id, perm_err)

        # Standard direct view URL for Google Drive that returns raw image/media
        direct_url = f"https://drive.google.com/uc?export=view&id={file_id}"
        logger.info("Uploaded %s to Drive folder (ID: %s). Direct URL: %s", file_name, file_id, direct_url)
        return direct_url

    except Exception as err:
        logger.error("Failed uploading to Google Drive: %s", err)
        return None


def upload_file(file_storage, folder_prefix="profiles", custom_filename=None, make_public=True):
    """
    Upload a file either to Google Drive, or falls back to local disk.
    
    Returns:
        tuple (file_url, stored_name):
            - file_url: Full HTTPS Google Drive URL (if uploaded to Drive),
                        or local filename stored_name (if saved locally).
            - stored_name: The clean filename.
    """
    if not file_storage or not getattr(file_storage, "filename", None):
        return None, None

    orig_name = secure_filename(file_storage.filename)

    if custom_filename:
        stored_name = custom_filename
    else:
        unique_id = uuid.uuid4().hex[:12]
        stored_name = f"{unique_id}_{orig_name}"

    # 1. Try Google Drive first
    service = get_drive_service()
    if service:
        drive_url = upload_to_drive(file_storage, folder_prefix=folder_prefix, custom_filename=stored_name)
        if drive_url:
            return drive_url, stored_name

    # 2. Local Disk Fallback
    try:
        from flask import current_app
        upload_folder = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "static", "uploads"))
        os.makedirs(upload_folder, exist_ok=True)
        local_path = os.path.join(upload_folder, stored_name)
        file_storage.seek(0)
        file_storage.save(local_path)
        logger.info("Saved file locally at %s", local_path)
        # Return clean stored_name so templates construct /static/uploads/<stored_name>
        return stored_name, stored_name
    except Exception as e:
        logger.error("Local save failed: %s", e)
        return None, None


def delete_file(file_identifier):
    """Remove obsolete file from cloud or local disk."""
    if not file_identifier or str(file_identifier).strip() == "":
        return

    file_str = str(file_identifier).strip()

    # If it's a Drive URL containing file ID
    if "drive.google.com" in file_str and "id=" in file_str:
        try:
            service = get_drive_service()
            if service:
                file_id = file_str.split("id=")[1].split("&")[0]
                service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
                logger.info("Deleted Google Drive file ID: %s", file_id)
                return
        except Exception as e:
            logger.warning("Failed deleting Google Drive file: %s", e)

    # Local file deletion
    try:
        from flask import current_app
        # Strip any leading /static/uploads/
        local_filename = os.path.basename(file_str)
        upload_folder = current_app.config.get("UPLOAD_FOLDER", os.path.join(current_app.root_path, "static", "uploads"))
        target_path = os.path.join(upload_folder, local_filename)
        if os.path.exists(target_path):
            os.remove(target_path)
            logger.info("Deleted local file: %s", target_path)
    except Exception as e:
        logger.warning("Could not delete local file: %s", e)
