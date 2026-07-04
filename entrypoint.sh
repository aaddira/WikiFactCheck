#!/bin/sh
# Try to run migrations, but don't fail if they don't work
echo "Attempting database migrations..."
flask db upgrade 2>/dev/null || echo "Warning: Flask-Migrate not available, skipping migrations"

# Start gunicorn
exec gunicorn --bind 0.0.0.0:5000 --timeout 60 --workers 2 main:app
