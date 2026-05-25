#!/bin/bash
set -e

# Ensure state directory exists
mkdir -p state

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
# 1 worker is REQUIRED because TaskManager uses in-memory state (threads).
echo "Starting Gunicorn on port 8001..."
gunicorn shark_platform.wsgi:application --bind 127.0.0.1:8001 --workers 1 --timeout 600 --threads 4 --access-logfile - --error-logfile - --capture-output &

# Start Nginx (Frontend & Proxy)
echo "Starting Nginx on port 8000..."
nginx

# Keep container alive with gunicorn in background job
wait
