#!/bin/sh
# One-shot bootstrap: runs on 'docker compose up', skipped on 'docker compose run'

set -e

# Run database migrations
echo "Applying database migrations..."
python manage.py migrate

# Create superuser if not exists
echo "Creating superuser..."
python manage.py shell << 'END'
from django.contrib.auth import get_user_model
import os
User = get_user_model()
username = os.environ.get('DJANGO_SUPERUSER_USERNAME', '')
if not username:
    print('DJANGO_SUPERUSER_USERNAME not set, skipping superuser creation.')
elif not User.objects.filter(username=username).exists():
    User.objects.create_superuser(
        username,
        os.environ.get('DJANGO_SUPERUSER_EMAIL', ''),
        os.environ.get('DJANGO_SUPERUSER_PASSWORD', ''),
    )
    print('Superuser created.')
else:
    print('Superuser already exists.')
END

echo "Init complete."
