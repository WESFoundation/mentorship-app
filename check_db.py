import sqlite3
conn = sqlite3.connect('WES-Working.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = cursor.fetchall()
for t in tables:
    print(t[0])

# Check master_task
cursor.execute("SELECT COUNT(*) FROM master_task")
count = cursor.fetchone()[0]
print('MasterTask count:', count)
cursor.execute('SELECT id, month, meeting_number, purpose_of_call FROM master_task LIMIT 5')
for row in cursor.fetchall():
    print(row)