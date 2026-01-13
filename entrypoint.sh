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

# Start Gunicorn
# 3 workers is a good default for small-medium instances
exec gunicorn shark_platform.wsgi:application --bind 0.0.0.0:8000 --workers 3
