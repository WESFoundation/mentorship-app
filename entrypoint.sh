#!/bin/sh
set -e

echo "=== Initializing Storage Directories & Permissions ==="
mkdir -p /app/instance /app/static/uploads
chmod -R 777 /app/instance /app/static/uploads 2>/dev/null || true

echo "=== Initializing Database & Application Context ==="
python -c "
from app import app, db, init_scheduler
with app.app_context():
    try:
        db.create_all()
        print('✅ Database tables created/verified.')
    except Exception as e:
        print(f'⚠️ db.create_all notice: {e}')
    
    try:
        from flask_migrate import upgrade
        upgrade()
        print('✅ Flask migrations applied.')
    except Exception as e:
        print(f'⚠️ Migration notice: {e}')
        
    try:
        init_scheduler()
        print('✅ Scheduler initialized.')
    except Exception as e:
        print(f'⚠️ Scheduler notice: {e}')
" || true

echo "=== Starting Gunicorn Server on Port ${PORT:-5000} ==="
exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 8 --timeout 120 app:app
