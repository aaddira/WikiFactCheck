#!/bin/sh
# Try Flask-Migrate first, with fallback to db.create_all()
echo "Initializing database..."

# Attempt 1: Flask-Migrate (preferred - tracked, safe)
if flask db upgrade 2>&1; then
    echo "[OK] Database initialized via Flask-Migrate"
else
    echo "[WARN] Flask-Migrate failed, falling back to SQLAlchemy"
    # Fallback: Use SQLAlchemy directly if Flask-Migrate is not available
    if python -c "from main import app, db; app.app_context().push(); db.create_all()" 2>&1; then
        echo "[OK] Database initialized via SQLAlchemy"
    else
        echo "[ERROR] Database initialization failed"
        exit 1
    fi
fi

# Start gunicorn
exec gunicorn --bind 0.0.0.0:5000 --timeout 60 --workers 2 main:app
