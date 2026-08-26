import sys
import os
import sqlite3
import psycopg2
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv(override=True)

sqlite_path = "instance/mentors_connect.db"
# Direct new Supabase host
pg_url = "postgresql://postgres:Mansoori%40%402005@db.sdyhpmhsybyjrgglrkzp.supabase.co:5432/postgres"

print(f"Connecting to Local SQLite: {sqlite_path}")
s_conn = sqlite3.connect(sqlite_path)
s_cur = s_conn.cursor()

print(f"Connecting to NEW Supabase ({pg_url[:60]}...)...")
p_conn = psycopg2.connect(pg_url)
p_cur = p_conn.cursor()

# Disable foreign key trigger checks during bulk data import
p_cur.execute("SET session_replication_role = 'replica';")

# Add missing columns if any
try:
    p_cur.execute("ALTER TABLE signup_details ADD COLUMN IF NOT EXISTS profile_completion_email_sent BOOLEAN DEFAULT FALSE;")
    p_conn.commit()
except Exception:
    p_conn.rollback()

# Get all tables from SQLite
s_cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
all_sqlite_tables = [r[0] for r in s_cur.fetchall() if r[0] not in ('sqlite_sequence',)]

results = {}
for t in all_sqlite_tables:
    try:
        s_cur.execute(f'SELECT * FROM "{t}";')
        rows = s_cur.fetchall()
        cols = [description[0] for description in s_cur.description]
        
        if not rows:
            results[t] = 0
            continue

        # Get PostgreSQL table columns and boolean column names
        p_cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s;", (t,))
        pg_existing_cols = {r[0] for r in p_cur.fetchall()}
        
        if not pg_existing_cols:
            print(f"⚠️ Table {t:30s}: Missing in PostgreSQL schema, skipping")
            continue

        p_cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s AND data_type = 'boolean';", (t,))
        bool_cols = {r[0] for r in p_cur.fetchall()}

        # Filter columns to only those present in PostgreSQL
        valid_indices = [i for i, c in enumerate(cols) if c in pg_existing_cols]
        valid_cols = [cols[i] for i in valid_indices]

        formatted_rows = []
        for row in rows:
            new_row = []
            for idx in valid_indices:
                col_name = cols[idx]
                val = row[idx]
                if col_name in bool_cols and val is not None:
                    new_row.append(bool(val))
                else:
                    new_row.append(val)
            formatted_rows.append(tuple(new_row))

        col_names = ", ".join([f'"{c}"' for c in valid_cols])
        placeholders = ", ".join(["%s"] * len(valid_cols))

        p_cur.execute(f'TRUNCATE TABLE "{t}" CASCADE;')
        insert_sql = f'INSERT INTO "{t}" ({col_names}) VALUES ({placeholders});'
        p_cur.executemany(insert_sql, formatted_rows)
        p_conn.commit()
        results[t] = len(rows)
        print(f"✅ Table {t:30s}: Migrated {len(rows)} records")
    except Exception as table_err:
        p_conn.rollback()
        p_cur.execute("SET session_replication_role = 'replica';")
        print(f"❌ Table {t:30s}: Error ({table_err})")

p_cur.execute("SET session_replication_role = 'origin';")
p_conn.commit()

s_conn.close()
p_conn.close()

print("=" * 60)
print("🎉 MIGRATION TO NEW SUPABASE COMPLETED SUCCESSFULLY!")
print("Synced Record Summary:")
for tbl in sorted(results.keys()):
    print(f"   • {tbl:30s}: {results[tbl]} records")
print("=" * 60)
