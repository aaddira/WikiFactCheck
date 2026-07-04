#!/bin/sh
# Initialize database schema using SQLAlchemy
echo "Initializing database schema..."
python -c "from main import app, db; app.app_context().push(); db.create_all()" || echo "Warning: Database initialization failed"

# Start gunicorn
exec gunicorn --bind 0.0.0.0:5000 --timeout 60 --workers 2 main:app
