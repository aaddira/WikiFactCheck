#!/bin/sh
# Robust database initialization with comprehensive logging

set -e  # Exit on any error
set -u  # Exit on undefined variables

log_info() { echo "[INFO] $1" >&2; }
log_warn() { echo "[WARN] $1" >&2; }
log_err() { echo "[ERROR] $1" >&2; }

log_info "Starting application initialization..."

# Check if Flask-Migrate is available and working
log_info "Attempting database initialization via Flask-Migrate..."
if flask db upgrade 2>&1 | tee /tmp/migrate.log; then
    log_info "Database initialized successfully via Flask-Migrate"
else
    migrate_status=$?
    log_warn "Flask-Migrate upgrade failed (exit code: $migrate_status)"

    # Check if the error was just about Flask-Migrate not being available
    if grep -q "No such command" /tmp/migrate.log 2>/dev/null; then
        log_warn "Flask-Migrate command not available, using SQLAlchemy fallback"
    else
        log_warn "Detailed migration output:"
        cat /tmp/migrate.log >&2
    fi

    # Fallback: Direct SQLAlchemy initialization
    log_info "Initializing database via SQLAlchemy (fallback)..."
    python -c "
from main import app, db
with app.app_context():
    db.create_all()
    print('[INFO] Database schema created via SQLAlchemy')
" || {
        log_err "SQLAlchemy initialization failed"
        exit 1
    }
fi

log_info "Database initialization complete"
log_info "Starting gunicorn..."

# Start gunicorn with detailed logging
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --timeout 60 \
    --workers 2 \
    --access-logfile - \
    --error-logfile - \
    main:app
