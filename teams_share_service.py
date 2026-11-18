"""
Microsoft Teams file sharing for task-reflection attachments.

Files are stored in the "Files" tab of a Teams channel (which is a SharePoint
folder behind the scenes) through Microsoft Graph, instead of the application
database or Google Drive.

Required environment (the MS Graph app registration already used for e-mail is
re-used for the credentials):

    MS_GRAPH_TENANT_ID / MS_GRAPH_CLIENT_ID / MS_GRAPH_CLIENT_SECRET
    MS_TEAMS_TEAM_ID      id of the Team that owns the share
    MS_TEAMS_CHANNEL_ID   id of the channel whose Files tab is used
    MS_TEAMS_SUBFOLDER    optional, folder inside the channel (default
                          "Task Reflections")

The app registration needs the *application* permission Files.ReadWrite.All
(or Sites.ReadWrite.All) with admin consent, plus ChannelSettings.Read.All /
Team.ReadBasic.All so the channel's files folder can be resolved.

Every function degrades gracefully: when Teams is not configured, or Graph
returns an error, the caller gets ``None`` and falls back to local storage.
"""

import logging
import os
import re
import urllib.parse

import requests

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024        # Graph simple PUT limit
CHUNK = 5 * 320 * 1024                       # upload-session chunk (multiple of 320 KiB)

_folder_cache = {}                           # (team, channel) -> (drive_id, folder_item_id)


def _team_id():
    return os.environ.get("MS_TEAMS_TEAM_ID")


def _channel_id():
    return os.environ.get("MS_TEAMS_CHANNEL_ID")


def _subfolder():
    return (os.environ.get("MS_TEAMS_SUBFOLDER") or "Task Reflections").strip("/ ")


def is_configured():
    return bool(_team_id() and _channel_id())


def _headers(token, extra=None):
    h = {"Authorization": f"Bearer {token}"}
    if extra:
        h.update(extra)
    return h


def _channel_files_folder(token):
    """(drive_id, folder_item_id) of the channel's Files folder, cached."""
    key = (_team_id(), _channel_id())
    if key in _folder_cache:
        return _folder_cache[key]
    resp = requests.get(
        f"{GRAPH}/teams/{key[0]}/channels/{key[1]}/filesFolder",
        headers=_headers(token), timeout=20)
    resp.raise_for_status()
    data = resp.json()
    drive_id = (data.get("parentReference") or {}).get("driveId")
    item_id = data.get("id")
    if not drive_id or not item_id:
        raise RuntimeError("Graph did not return a drive/folder for the Teams channel")
    _folder_cache[key] = (drive_id, item_id)
    return _folder_cache[key]


def _safe_name(name):
    name = re.sub(r"[\\/:*?\"<>|#%]", "_", name or "file").strip(". ") or "file"
    return name[:150]


def upload(token, data, filename, content_type="application/octet-stream", subfolder=None):
    """Upload ``data`` (bytes) into the Teams channel files folder.

    Returns ``{"drive_id", "item_id", "web_url"}`` or ``None`` on any failure.
    ``subfolder`` is an extra path under the configured sub-folder, e.g.
    ``"master_12"`` so each task gets its own folder in Teams.
    """
    if not token or not is_configured():
        return None
    try:
        drive_id, folder_id = _channel_files_folder(token)
        parts = [p for p in (_subfolder(), subfolder) if p]
        rel = "/".join(urllib.parse.quote(_safe_name(p)) for p in parts)
        name = urllib.parse.quote(_safe_name(filename))
        base = f"{GRAPH}/drives/{drive_id}/items/{folder_id}:/{rel}/{name}:"
        conflict = {"item": {"@microsoft.graph.conflictBehavior": "rename"}}

        if len(data) <= SIMPLE_UPLOAD_LIMIT:
            resp = requests.put(
                base + "/content?@microsoft.graph.conflictBehavior=rename",
                headers=_headers(token, {"Content-Type": content_type}),
                data=data, timeout=60)
            resp.raise_for_status()
            item = resp.json()
        else:
            sess = requests.post(base + "/createUploadSession",
                                 headers=_headers(token), json=conflict, timeout=30)
            sess.raise_for_status()
            url = sess.json()["uploadUrl"]
            total, start, item = len(data), 0, None
            while start < total:
                chunk = data[start:start + CHUNK]
                end = start + len(chunk) - 1
                r = requests.put(url, data=chunk, timeout=120, headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{total}"})
                r.raise_for_status()
                if r.status_code in (200, 201):
                    item = r.json()
                start = end + 1
            if not item:
                raise RuntimeError("Upload session finished without an item")

        return {
            "drive_id": (item.get("parentReference") or {}).get("driveId") or drive_id,
            "item_id": item.get("id"),
            "web_url": item.get("webUrl"),
        }
    except Exception as err:  # network, permission, config - caller falls back
        logger.warning("Teams upload failed: %s", err)
        return None


def download(token, drive_id, item_id):
    """Fetch a stored file. Returns ``(bytes, content_type)`` or ``None``."""
    if not token or not drive_id or not item_id:
        return None
    try:
        resp = requests.get(f"{GRAPH}/drives/{drive_id}/items/{item_id}/content",
                            headers=_headers(token), timeout=60, allow_redirects=True)
        resp.raise_for_status()
        return resp.content, resp.headers.get("Content-Type", "application/octet-stream")
    except Exception as err:
        logger.warning("Teams download failed: %s", err)
        return None
