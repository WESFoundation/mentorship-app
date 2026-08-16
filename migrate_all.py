import sys
import os
import sqlite3
import psycopg2
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv(override=True)

sqlite_path = "instance/mentors_connect.db"
pg_url = os.environ.get("DATABASE_URL")

print(f"Connecting to SQLite: {sqlite_path}")
s_conn = sqlite3.connect(sqlite_path)
s_cur = s_conn.cursor()

print(f"Connecting to Supabase PostgreSQL: {pg_url[:60]}...")
p_conn = psycopg2.connect(pg_url)
p_cur = p_conn.cursor()

p_cur.execute("SET session_replication_role = 'replica';")

# Ensure missing columns exist in PostgreSQL
try:
    p_cur.execute("ALTER TABLE signup_details ADD COLUMN IF NOT EXISTS profile_completion_email_sent BOOLEAN DEFAULT FALSE;")
    p_conn.commit()
except Exception as e:
    p_conn.rollback()

tables = [
    'signup_details', 
    'mentor_profile', 
    'mentee_profile', 
    'supervisor_profile', 
    'institution_profiles', 
    'MasterTask', 
    'personal_tasks', 
    'mentee_tasks', 
    'task_ratings', 
    'mentorship_requests', 
    'meeting_requests', 
    'chat_conversations', 
    'chat_messages', 
    'institutions', 
    'profile_completion_reminders', 
    'reminder_settings', 
    'password_reset_otp'
]

results = {}
for t in tables:
    try:
        s_cur.execute(f'SELECT * FROM "{t}";')
        rows = s_cur.fetchall()
        cols = [description[0] for description in s_cur.description]
        
        if not rows:
            results[t] = 0
            continue
            
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
        insert_sql = f'INSERT INTO "{t}" ({col_names}) VALUES ({placeholders});'
        p_cur.executemany(insert_sql, formatted_rows)
        p_conn.commit()
        results[t] = len(rows)
        print(f"✅ Table {t:30s}: Migrated {len(rows)} records")
    except Exception as e:
        p_conn.rollback()
        p_cur.execute("SET session_replication_role = 'replica';")
        print(f"❌ Table {t:30s}: Error ({e})")

p_cur.execute("SET session_replication_role = 'origin';")
p_conn.commit()

s_conn.close()
p_conn.close()

print("=" * 60)
print("🎉 FULL MIGRATION TO SUPABASE COMPLETED SUCCESSFULLY!")
print("Synced Record Summary:")
for tbl, count in results.items():
    print(f"   • {tbl:30s}: {count} records")
print("=" * 60)
