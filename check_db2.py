import sqlite3
conn = sqlite3.connect('WES-Working.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = cursor.fetchall()
print('Tables:', tables)
if not tables:
    print('No tables - database is empty')
conn.close()