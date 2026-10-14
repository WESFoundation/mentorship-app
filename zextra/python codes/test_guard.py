"""Safety helper: create a throwaway SQLite copy of the database for testing.

app.py resolves its database from the DATABASE_URL environment variable, and on
this machine that variable is pre-set to the PRODUCTION Supabase instance. Every
test must therefore be pointed at a disposable copy BEFORE app.py is imported.

Usage from a test script:

    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from test_guard import use_disposable_db, bootstrap
    use_disposable_db(__file__)   # <- sets DATABASE_URL, exits if unsafe
    bootstrap()                   # <- sys.path + env, still no app import yet

    from app import ...           # safe now
"""
import os
import shutil
import sys
import tempfile

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LOCAL_DB = os.path.join(APP_ROOT, "instance", "mentors_connect.db")


def _is_safe_url(url):
    return url.strip().lower().startswith("sqlite:")


def use_disposable_db(script_name):
    """Make DATABASE_URL point at a FRESH throwaway copy. Refuses anything else.

    A fresh copy is taken on every run so a previous run that crashed before its
    cleanup cannot leave rows behind and make the next run non-deterministic.
    Set WES_TEST_REUSE_DB=1 to keep and reuse a copy (useful while debugging).
    """
    existing = (os.environ.get("DATABASE_URL") or "").strip()

    if existing and not _is_safe_url(existing):
        print("=" * 78)
        print(f"BLOCKED: {os.path.basename(script_name)}")
        print("=" * 78)
        print("  DATABASE_URL points at a shared / production database:")
        print(f"    {existing[:90]}")
        print()
        print("  These tests create and delete rows, so they only run against a")
        print("  disposable SQLite copy. Unset it and re-run:")
        print("    Remove-Item Env:\\DATABASE_URL")
        sys.exit(2)

    tmpdir = os.path.join(tempfile.gettempdir(), "mentor_connect_tests")
    os.makedirs(tmpdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(script_name))[0]
    target = os.path.join(tmpdir, f"{base}.db")
    reuse = (os.environ.get("WES_TEST_REUSE_DB") or "").strip().lower() in ("1", "true", "yes")

    if reuse and existing and os.path.isfile(existing.split("sqlite:///", 1)[-1]):
        print(f"[db] reusing existing disposable copy for {os.path.basename(script_name)}")
        return existing

    # Start from a clean copy of the real database.
    for path in (target, target + "-wal", target + "-shm"):
        if os.path.isfile(path):
            os.remove(path)
    if not os.path.isfile(LOCAL_DB):
        print(f"BLOCKED: {LOCAL_DB} not found - cannot build a disposable copy.")
        sys.exit(2)
    shutil.copyfile(LOCAL_DB, target)
    url = "sqlite:///" + target.replace("\\", "/")
    os.environ["DATABASE_URL"] = url
    print(f"[db] fresh disposable copy for {os.path.basename(script_name)} -> {target}")
    return url


def bootstrap():
    """sys.path + safe env. Does NOT import the app."""
    sys.path.insert(0, APP_ROOT)
    os.environ.setdefault("PRODUCTION", "false")
    # Stop app.py's auto_migrate_schema() from writing at import time; the test
    # harness creates the schema it needs itself (see ensure_test_schema).
    os.environ["SKIP_AUTO_MIGRATE"] = "1"
    return APP_ROOT


def ensure_test_schema():
    """Create missing tables AND columns on the disposable copy."""
    from sqlalchemy import inspect, text

    import app as application

    with application.app.app_context():
        db = application.db
        db.create_all()

        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        for table_name, table in db.metadata.tables.items():
            if table_name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                col_type = col.type.compile(db.engine.dialect)
                with db.engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}"))
                    conn.commit()
                print(f"[db] added column {table_name}.{col.name}")

        indexes = [
            ("idx_mentor_country", "mentor_profile", "country"),
            ("idx_mentor_state", "mentor_profile", "state"),
            ("idx_mentor_city", "mentor_profile", "city"),
            ("idx_mentor_coupons_mentor", "mentor_coupons", "mentor_id"),
            ("idx_mentor_coupons_status", "mentor_coupons", "status"),
            ("idx_mentor_reflections_task", "mentor_reflections", "task_type, task_id, mentor_id"),
            ("idx_task_ratings_task_mentor", "task_ratings", "task_type, task_id, mentor_id"),
        ]
        with db.engine.connect() as conn:
            for name, table, cols in indexes:
                try:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))
                    conn.commit()
                except Exception:
                    pass