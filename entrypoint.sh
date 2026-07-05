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
log_info "Running: flask db upgrade"
log_info "FLASK_APP=$FLASK_APP"

# Run with timeout to prevent hanging
timeout 30 bash -c 'flask db upgrade 2>&1' > /tmp/migrate.log 2>&1
MIGRATE_EXIT=$?
MIGRATE_OUTPUT=$(cat /tmp/migrate.log)

log_info "Flask-Migrate exit code: $MIGRATE_EXIT"
log_info "Flask-Migrate output:"
echo "$MIGRATE_OUTPUT" >&2

if [ $MIGRATE_EXIT -eq 0 ]; then
    log_info "Database initialized successfully via Flask-Migrate"
elif [ $MIGRATE_EXIT -eq 124 ]; then
    log_err "Flask-Migrate command timed out (30 seconds)"
    log_warn "Falling back to SQLAlchemy"
elif echo "$MIGRATE_OUTPUT" | grep -q "No such command"; then
    # Flask-Migrate command not available, use fallback
    log_warn "Flask-Migrate command not available, falling back to SQLAlchemy"
    log_info "Initializing database via SQLAlchemy..."
    python -c "
from main import app, db
with app.app_context():
    db.create_all()
    print('[INFO] Database schema created via SQLAlchemy')
" || {
        log_err "SQLAlchemy initialization failed"
        exit 1
    }
else
    # Flask-Migrate exists but failed for another reason (or timed out)
    log_warn "Flask-Migrate upgrade failed (exit code: $MIGRATE_EXIT)"
    if [ -n "$MIGRATE_OUTPUT" ]; then
        log_err "Flask-Migrate output: $MIGRATE_OUTPUT"
    fi
    log_warn "Trying SQLAlchemy fallback..."
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
