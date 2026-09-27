import sqlite3
conn = sqlite3.connect('C:/Users/shrey/Downloads/wes lux/mentor connect/WES-Working/instance/mentors_connect.db')
cursor = conn.cursor()
cursor.execute('SELECT id, mentee_id, task_id, task_type, rating, text, created_at FROM mentee_feedbacks WHERE created_at LIKE "%2026-09-09%"')
for row in cursor.fetchall():
    print(row)