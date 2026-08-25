import os
import time
import psycopg2
from dotenv import load_dotenv

load_dotenv(override=True)

db_url = os.environ.get("DATABASE_URL", "").strip()
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
if "?pgbouncer=true" in db_url:
    db_url = db_url.replace("?pgbouncer=true", "")
if "&pgbouncer=true" in db_url:
    db_url = db_url.replace("&pgbouncer=true", "")

print("\n🔍 Supabase Database Ping & Connection Diagnostic")
print("=" * 55)

if not db_url:
    print("❌ Error: DATABASE_URL not set in .env file!")
    exit(1)

print(f"🔗 Target Host: {db_url.split('@')[-1] if '@' in db_url else db_url}")

start = time.time()
try:
    conn = psycopg2.connect(db_url, connect_timeout=10)
    latency = (time.time() - start) * 1000
    cur = conn.cursor()
    
    cur.execute("SELECT version();")
    pg_version = cur.fetchone()[0]
    
    cur.execute("SELECT count(*) FROM signup_details;")
    users_count = cur.fetchone()[0]
    
    cur.execute("SELECT count(*) FROM mentor_profile;")
    mentors_count = cur.fetchone()[0]
    
    cur.execute("SELECT count(*) FROM mentee_profile;")
    mentees_count = cur.fetchone()[0]
    
    print("\n✅ STATUS: SUCCESSFULLY CONNECTED!")
    print(f"⚡ PING / LATENCY: {latency:.2f} ms")
    print(f"🐘 POSTGRES VERSION: {pg_version.split(',')[0]}")
    print("\n📊 DATABASE STATS:")
    print(f"   • Registered Users (signup_details) : {users_count}")
    print(f"   • Mentor Profiles (mentor_profile)   : {mentors_count}")
    print(f"   • Mentee Profiles (mentee_profile)   : {mentees_count}")
    print("=" * 55 + "\n")
    conn.close()
except Exception as e:
    print(f"\n❌ CONNECTION ERROR: {e}\n")
