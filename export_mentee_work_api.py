"""Command-line client for the read-only Excel export API.

Usage:
    python export_mentee_work_api.py --mentor-id 228 [--output report.xlsx]
    python export_mentee_work_api.py --mentor-email joyifeanyieze@gmail.com [--output report.xlsx]

The script only READS data through the API. It never writes to the database.
API key is read from the .env file (EXPORT_API_KEY) or passed via --api-key.
"""


import argparse
import json
import os
import sys
import urllib.request
import urllib.error


def load_env_key():
    """Load EXPORT_API_KEY from the .env file next to this script."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("EXPORT_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main():
    parser = argparse.ArgumentParser(description="Export mentor's mentee work to Excel via the read-only API.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mentor-id", type=int, help="Mentor's user id")
    group.add_argument("--mentor-email", help="Mentor's email address")
    parser.add_argument("--api-key", help="API key (defaults to EXPORT_API_KEY from .env)")
    parser.add_argument("--url", default="http://127.0.0.1:5000/api/export_mentee_work",
                        help="API endpoint URL")
    parser.add_argument("--output", default="mentee_work_report.xlsx", help="Output .xlsx file path")
    args = parser.parse_args()

    api_key = args.api_key or load_env_key()
    if not api_key:
        print("ERROR: No API key. Set EXPORT_API_KEY in .env or pass --api-key.")
        sys.exit(2)

    body = {}
    if args.mentor_id:
        body["mentor_id"] = args.mentor_id
    if args.mentor_email:
        body["mentor_email"] = args.mentor_email

    req = urllib.request.Request(
        args.url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            with open(args.output, "wb") as f:
                f.write(data)
        print(f"OK: saved {len(data)} bytes -> {args.output}")
        print("This was a READ-ONLY request. No database changes were made.")
    except urllib.error.HTTPError as e:
        print(f"HTTP ERROR {e.code}: {e.read().decode('utf-8', 'replace')}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
