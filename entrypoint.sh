#!/bin/sh
set -e

echo "=== Initializing Storage Directories & Permissions ==="
mkdir -p /app/instance /app/static/uploads
chmod -R 777 /app/instance /app/static/uploads

echo "=== Initializing Database & Application Context ==="
python -c "from app import app, db, init_scheduler; 
with app.app_context():
    try:
        from flask_migrate import upgrade
        upgrade()
        print('✅ Flask migrations applied successfully.')
    except Exception as e:
        print(f'⚠️ Migration notice (falling back to db.create_all()): {e}')
        db.create_all()
        print('✅ Database tables created with db.create_all().')
    try:
        init_scheduler()
    except Exception as e:
        print(f'⚠️ Scheduler notice: {e}')
"

echo "=== Starting Gunicorn Server on Port ${PORT:-5000} ==="
# Note: --workers 1 --threads 8 prevents SQLite database locking errors while handling concurrent requests
exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 8 --timeout 120 app:app
