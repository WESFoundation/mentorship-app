import psycopg2

db_url = "postgresql://postgres.sdyhpmhsybyjrgglrkzp:Mansoori%40%402005@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"

conn = psycopg2.connect(db_url)
cur = conn.cursor()

def get_mentor_rating(user_id):
    # 1. Profile completeness
    cur.execute("SELECT profession, organisation, location FROM mentor_profile WHERE user_id = %s OR user_id = %s", (user_id, str(user_id)))
    prof = cur.fetchone()
    fields = 0
    if prof:
        if prof[0]: fields += 1
        if prof[1]: fields += 1
        if prof[2]: fields += 1
    profile_stars = round((fields / 3.0) * 5.0, 1) if fields > 0 else 3.0

    # 2. Supervisor rating
    cur.execute("SELECT supervisor_rating FROM mentor_profile WHERE user_id = %s OR user_id = %s", (user_id, str(user_id)))
    sup = cur.fetchone()
    admin_stars = float(sup[0]) if sup and sup[0] is not None else 5.0

    # 3. Tasks rating
    cur.execute("SELECT status FROM mentee_tasks WHERE mentor_id = %s", (user_id,))
    tasks = cur.fetchall()
    if tasks:
        done = sum(1 for t in tasks if t[0] == 'completed' or t[0] == 'Done')
        task_stars = round((done / len(tasks)) * 5.0, 1)
    else:
        task_stars = 4.5

    final_rating = round((profile_stars + admin_stars + task_stars) / 3.0, 1)
    return min(5.0, max(1.0, final_rating))

print("Mentor 282 rating:", get_mentor_rating(282))
print("Mentor 2 rating:", get_mentor_rating(2))
print("Mentor 455 rating:", get_mentor_rating(455))

conn.close()
