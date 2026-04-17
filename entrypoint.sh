#!/bin/sh

# Run database migrations
echo "Applying database migrations..."
python manage.py migrate

# Create superuser if not exists
echo "Creating superuser..."
python manage.py shell << END
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='$DJANGO_SUPERUSER_USERNAME').exists():
    User.objects.create_superuser('$DJANGO_SUPERUSER_USERNAME', '$DJANGO_SUPERUSER_EMAIL', '$DJANGO_SUPERUSER_PASSWORD')
    print('Superuser created.')
else:
    print('Superuser already exists.')
END

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Execute the CMD
exec "$@"
