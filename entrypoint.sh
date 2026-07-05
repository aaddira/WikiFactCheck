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
log_info "FLASK_APP=$FLASK_APP"

# Try Flask-Migrate directly with Python to avoid subprocess issues
python << 'PYTHON_EOF'
import sys
import os
log_prefix = "[INFO]"

try:
    from flask_migrate import upgrade
    from main import app

    print(f"{log_prefix} Flask-Migrate found, attempting upgrade...", file=sys.stderr)

    with app.app_context():
        upgrade()
        print(f"{log_prefix} Database upgraded successfully via Flask-Migrate", file=sys.stderr)
        sys.exit(0)

except Exception as e:
    print(f"[ERROR] Flask-Migrate failed: {str(e)}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
PYTHON_EOF

MIGRATE_EXIT=$?

if [ $MIGRATE_EXIT -eq 0 ]; then
    log_info "Database upgraded via Flask-Migrate"
    # Also run db.create_all() to ensure all tables exist (for tables not covered by migrations)
    log_info "Running db.create_all() to ensure all tables exist..."
    python -c "
from main import app, db
with app.app_context():
    db.create_all()
    print('[INFO] All tables created/verified via SQLAlchemy')
" || {
        log_err "SQLAlchemy db.create_all() failed"
        exit 1
    }
    log_info "Database initialization complete"
else
    log_warn "Flask-Migrate upgrade failed (exit code: $MIGRATE_EXIT), falling back to SQLAlchemy..."
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
