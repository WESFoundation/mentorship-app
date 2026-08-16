import os
import time
import logging
import threading
import sqlite3
import psycopg2

from dotenv import load_dotenv
load_dotenv(override=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("supabase_sync")

def sync_sqlite_to_supabase():
    """
    Sync all tables from local SQLite database (mentors_connect.db) to Supabase PostgreSQL.
    Bypasses foreign key checks via session_replication_role = 'replica'.
    """
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        logger.warning("DATABASE_URL not set; skipping Supabase sync.")
        return False

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    # Find local SQLite database path
    sqlite_path = "instance/mentors_connect.db"
    if not os.path.exists(sqlite_path):
        sqlite_path = "mentors_connect.db"
        if not os.path.exists(sqlite_path):
            logger.warning("No SQLite mentors_connect.db found to sync.")
            return False

    try:
        s_conn = sqlite3.connect(sqlite_path)
        s_cur = s_conn.cursor()

        p_conn = psycopg2.connect(db_url)
        p_cur = p_conn.cursor()

        p_cur.execute("SET session_replication_role = 'replica';")

        s_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [t[0] for t in s_cur.fetchall()]

        synced = {}
        for t in tables:
            try:
                s_cur.execute(f'SELECT * FROM "{t}"')
                rows = s_cur.fetchall()
                cols = [description[0] for description in s_cur.description]
                if not rows:
                    continue

                # Find boolean columns in PostgreSQL table
                p_cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s AND data_type = 'boolean';", (t,))
                bool_cols = {r[0] for r in p_cur.fetchall()}

                formatted_rows = []
                for row in rows:
                    new_row = []
                    for col_name, val in zip(cols, row):
                        if col_name in bool_cols and val is not None:
                            new_row.append(bool(val))
                        else:
                            new_row.append(val)
                    formatted_rows.append(tuple(new_row))

                col_names = ", ".join([f'"{c}"' for c in cols])
                placeholders = ", ".join(["%s"] * len(cols))

                p_cur.execute(f'TRUNCATE TABLE "{t}" CASCADE;')
                insert_sql = f'INSERT INTO "{t}" ({col_names}) VALUES ({placeholders})'
                p_cur.executemany(insert_sql, formatted_rows)
                synced[t] = len(rows)
            except Exception as table_err:
                p_conn.rollback()
                p_cur.execute("SET session_replication_role = 'replica';")
                logger.warning(f"Skipping table {t} sync: {table_err}")

        p_conn.commit()
        p_cur.execute("SET session_replication_role = 'origin';")

        s_conn.close()
        p_conn.close()

        logger.info(f"✅ Supabase Backup Sync Successful! Synced tables: {synced}")
        return True
    except Exception as e:
        logger.error(f"❌ Error during Supabase backup sync: {e}")
        return False

def trigger_async_sync():
    """
    Run sync in a non-blocking background thread so Flask HTTP responses are instantaneous.
    """
    t = threading.Thread(target=sync_sqlite_to_supabase, daemon=True)
    t.start()

def start_periodic_sync(interval_seconds=60):
    """
    Start a periodic background daemon thread that backs up SQLite to Supabase every N seconds.
    """
    def loop():
        while True:
            time.sleep(interval_seconds)
            try:
                sync_sqlite_to_supabase()
            except Exception as e:
                logger.error(f"Periodic sync exception: {e}")

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    logger.info(f"🔄 Periodic Supabase Backup Sync started (Interval: {interval_seconds}s)")
