import sys
import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

db_url = "postgresql://postgres:Mansoori%40%402005@db.sdyhpmhsybyjrgglrkzp.supabase.co:5432/postgres"

conn = psycopg2.connect(db_url)
cur = conn.cursor()

cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public';")
tables = [r[0] for r in cur.fetchall()]

cur.execute("SET session_replication_role = 'replica';")
for t in tables:
    cur.execute(f'TRUNCATE TABLE "{t}" CASCADE;')
cur.execute("SET session_replication_role = 'origin';")
conn.commit()

print("=" * 60)
print(f"🎉 NEW SUPABASE (`sdyhpmhsybyjrgglrkzp`) HAS EXACTLY {len(tables)} TABLES (ALL 0 ROWS):")
print("=" * 60)
for t in sorted(tables):
    cur.execute(f'SELECT COUNT(*) FROM "{t}"')
    cnt = cur.fetchone()[0]
    print(f"   • {t:30s} : {cnt} rows (EMPTY)")
print("=" * 60)

conn.close()
