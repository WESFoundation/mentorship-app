import psycopg2

db_url = "postgresql://postgres.sdyhpmhsybyjrgglrkzp:Mansoori%40%402005@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"

conn = psycopg2.connect(db_url)
cur = conn.cursor()

print("--- Testing getAllMentors query ---")
cur.execute('''
    SELECT u.id as id, u.id as user_id, u.name, mp.profession, mp.organisation, mp.location, mp.supervisor_rating, mp.status
    FROM signup_details u
    LEFT JOIN mentor_profile mp ON u.id::varchar = mp.user_id
    WHERE u.user_type = '1'
    LIMIT 10
''')
mentors = cur.fetchall()
print(f"Fetched {len(mentors)} mentors successfully!")
for m in mentors[:3]:
    print(" ", m)

print("\n--- Testing getConnectedMentors query ---")
cur.execute('''
    SELECT u.id as id, u.id as user_id, u.name, mp.profession, mp.organisation, mp.location, mp.supervisor_rating, mp.status
    FROM mentorship_requests mr
    JOIN signup_details u ON mr.mentor_id = u.id
    LEFT JOIN mentor_profile mp ON u.id::varchar = mp.user_id
    WHERE mr.mentee_id = 265
      AND (mr.final_status = 'approved' OR mr.supervisor_status = 'approved' OR mr.mentor_status = 'accepted')
''')
connected = cur.fetchall()
print(f"Fetched {len(connected)} connected mentors for mentee 265 successfully!")
for cm in connected:
    print(" ", cm)

conn.close()
