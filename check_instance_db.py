import os
db_path = 'instance/mentors_connect.db'
print('DB exists:', os.path.exists(db_path))
if os.path.exists(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
    tables = cursor.fetchall()
    print('Tables:', tables)
    # Check user table schema
    cursor.execute('PRAGMA table_info(user)')
    for row in cursor.fetchall():
        print('user:', row)
    # Check signup_details table schema
    cursor.execute('PRAGMA table_info(signup_details)')
    for row in cursor.fetchall():
        print('signup_details:', row)
    conn.close()