import sqlite3
conn = sqlite3.connect('WES-Working.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
for row in cursor.fetchall():
    print(row)
conn.close()