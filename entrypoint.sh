#!/bin/sh
set -e

echo "=== Initializing Database & Application Context ==="
python -c "from app import app, db, init_scheduler; 
with app.app_context():
    db.create_all()
    try:
        init_scheduler()
    except Exception as e:
        print(f'Scheduler notice: {e}')
"

echo "=== Starting Gunicorn Server on Port ${PORT:-5000} ==="
exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 2 --threads 4 --timeout 120 app:app
