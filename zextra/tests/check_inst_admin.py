import sqlite3
conn = sqlite3.connect('instance/mentors_connect.db')
cursor = conn.cursor()
cursor.execute('SELECT id, email, name FROM signup_details WHERE user_type = "3"')
for row in cursor.fetchall():
    print(row)