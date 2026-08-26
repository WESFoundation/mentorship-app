import sys
import os
import psycopg2
from dotenv import load_dotenv
from sqlalchemy import create_engine

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv(override=True)

# Direct Supabase host
db_url = "postgresql://postgres:Mansoori%40%402005@db.sdyhpmhsybyjrgglrkzp.supabase.co:5432/postgres"

print(f"Connecting to NEW Supabase ({db_url[:60]}...)...")

# Import app AND all models
import app as app_module
from app import app, db

# Create engine directly pointing to new Supabase
engine = create_engine(db_url)

print("Creating all application table schemas on NEW Supabase PostgreSQL...")
db.metadata.create_all(bind=engine)

conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Create alembic_version table
cur.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));")

# Create oauth_callbacks table if it exists in SQLite
cur.execute("""
CREATE TABLE IF NOT EXISTS oauth_callbacks (
    id SERIAL PRIMARY KEY,
    state VARCHAR(255),
    code VARCHAR(255),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
""")

conn.commit()

cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public';")
tables = [r[0] for r in cur.fetchall()]

print("=" * 60)
print(f"🎉 NEW SUPABASE (`sdyhpmhsybyjrgglrkzp`) HAS EXACTLY {len(tables)} TABLES:")
print("=" * 60)
for t in sorted(tables):
    cur.execute(f'SELECT COUNT(*) FROM "{t}"')
    cnt = cur.fetchone()[0]
    print(f"   • {t:30s} : {cnt} rows")
print("=" * 60)

conn.close()
