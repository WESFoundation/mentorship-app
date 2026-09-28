import sqlite3
conn = sqlite3.connect('instance/mentors_connect.db')
cursor = conn.cursor()
cursor.execute('SELECT id, email, user_type FROM signup_details WHERE user_type IN ("0", "3") LIMIT 5')
for row in cursor.fetchall():
    print(row)