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
# Single worker recommended for SQLite + session consistency.
echo "Starting Gunicorn on port 8001..."
gunicorn shark_platform.wsgi:application --bind 127.0.0.1:8001 --workers 1 --timeout 600 --threads 4 \
  --logger-class shark_platform.gunicorn_logger.FilteredAccessLogger \
  --access-logfile - --error-logfile - --capture-output &

# Nginx 日志目录（Docker 命名卷挂载时可能为空，需显式创建）
mkdir -p /var/log/nginx
touch /var/log/nginx/shark_access.log /var/log/nginx/shark_error.log 2>/dev/null || true

# Start Nginx (Frontend & Proxy)
echo "Starting Nginx on port 8000..."
nginx

# Keep container alive with gunicorn in background job
wait
