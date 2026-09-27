import sqlite3
conn = sqlite3.connect('instance/mentors_connect.db')
cursor = conn.cursor()
cursor.execute('SELECT id, mentee_id, mentor_id, final_status, mentor_type, duration_months FROM mentorship_requests WHERE mentor_type = "anchor"')
for row in cursor.fetchall():
    print(row)