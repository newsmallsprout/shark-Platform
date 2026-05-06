#!/bin/bash
set -e

# Ensure state directory exists
mkdir -p state logs

# Run migrations
python manage.py migrate

# Create superuser if not exists
python -c "
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shark_platform.settings')
django.setup()
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin')
    print('Superuser admin created')
"

# Gunicorn: default 1 worker if Normal sync runs in-process (TaskManager threads).
# For SHARK_SYNC_NORMAL_MODE=supervisor, set GUNICORN_WORKERS>1 and run the supervisor below.
echo "Starting Gunicorn on port 8001..."
GUNICORN_THREADS="${GUNICORN_THREADS:-4}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-1}"
if [ "$GUNICORN_WORKERS" != "1" ] && [ "${SHARK_SYNC_NORMAL_MODE:-inprocess}" != "supervisor" ]; then
  echo "WARN: GUNICORN_WORKERS>1 without SHARK_SYNC_NORMAL_MODE=supervisor: Normal sync tasks are unsafe across workers; see docs/MULTI_WORKER_REFACTOR.md" >&2
fi
if [ "${SHARK_SYNC_NORMAL_MODE:-inprocess}" = "supervisor" ]; then
  echo "Starting sync_supervisor (Normal sync in dedicated process)..."
  python manage.py sync_supervisor &
fi
gunicorn shark_platform.wsgi:application --bind 127.0.0.1:8001 --workers "$GUNICORN_WORKERS" --timeout 600 \
  --threads "$GUNICORN_THREADS" \
  --logger-class shark_platform.gunicorn_logger.FilteredAccessLogger \
  --log-level warning --access-logfile /dev/null --error-logfile - --capture-output &

# Start Nginx (Frontend & Proxy)
echo "Starting Nginx on port 8000..."
nginx

# Keep container alive with gunicorn in background job
wait
