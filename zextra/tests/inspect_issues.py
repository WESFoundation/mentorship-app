import psycopg2

db_url = "postgresql://postgres.sdyhpmhsybyjrgglrkzp:Mansoori%40%402005@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"

conn = psycopg2.connect(db_url)
cur = conn.cursor()

# 1. Check mentors in signup_details and mentor_profile
cur.execute("SELECT id, name, email, user_type FROM signup_details WHERE user_type = '1'")
mentors_signup = cur.fetchall()
print("--- Mentors in signup_details (user_type='1') ---")
for m in mentors_signup:
    print(f"  ID: {m[0]} | Name: {m[1]} | Email: {m[2]}")

cur.execute("SELECT id, user_id, profession, organisation FROM mentor_profile")
mentors_profile = cur.fetchall()
print("\n--- Rows in mentor_profile ---")
for mp in mentors_profile:
    print(f"  Profile ID: {mp[0]} | User ID: {mp[1]} | Profession: {mp[2]} | Org: {mp[3]}")

# 2. Check mentorship_requests for all mentees
cur.execute("SELECT id, mentee_id, mentor_id, mentor_status, supervisor_status, final_status FROM mentorship_requests")
requests = cur.fetchall()
print("\n--- All mentorship_requests ---")
for r in requests:
    print(f"  Req ID: {r[0]} | Mentee ID: {r[1]} | Mentor ID: {r[2]} | MentorStatus: {r[3]} | SupervisorStatus: {r[4]} | FinalStatus: {r[5]}")

# 3. Check meeting_requests sample
cur.execute("SELECT id, meeting_title, meeting_date, meeting_time, status FROM meeting_requests LIMIT 5")
meetings = cur.fetchall()
print("\n--- Sample meeting_requests ---")
for mt in meetings:
    print(f"  Meeting: {mt[0]} | Title: {mt[1]} | Date: {mt[2]} ({type(mt[2])}) | Time: {mt[3]}")

conn.close()
