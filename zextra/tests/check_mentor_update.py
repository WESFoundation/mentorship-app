import psycopg2

db_url = "postgresql://postgres.sdyhpmhsybyjrgglrkzp:Mansoori%40%402005@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"

conn = psycopg2.connect(db_url)
cur = conn.cursor()

cur.execute("SELECT id, user_id, profession, organisation, supervisor_rating FROM mentor_profile WHERE user_id = '282' OR user_id = '2'")
rows = cur.fetchall()
print("Mentor profile rows:")
for r in rows:
    print(" ", r)

conn.close()
