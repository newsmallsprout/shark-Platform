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

# Start Gunicorn (Backend) on port 8001
# 1 worker is REQUIRED（TaskManager 进程内状态）。并发靠线程；可用 GUNICORN_THREADS 调大（IO/GeoIP 友好）。
echo "Starting Gunicorn on port 8001..."
GUNICORN_THREADS="${GUNICORN_THREADS:-4}"
gunicorn shark_platform.wsgi:application --bind 127.0.0.1:8001 --workers 1 --timeout 600 \
  --threads "$GUNICORN_THREADS" \
  --logger-class shark_platform.gunicorn_logger.FilteredAccessLogger \
  --log-level warning --access-logfile /dev/null --error-logfile - --capture-output &

# Start Nginx (Frontend & Proxy)
echo "Starting Nginx on port 8000..."
nginx

# Keep container alive with gunicorn in background job
wait
