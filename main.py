import os
from pathlib import Path
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from flask_migrate import Migrate
from dotenv import load_dotenv
from datetime import datetime
import logging
import sys

from models import db, User, Dataset, Pair, Annotation, Claim, Skip, Config, TestSubmission, AuditLog
from auth import do_login, do_logout, login_required, admin_required, get_current_user
from data_loader import parse_jsonl_file, seed_default_config

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Database configuration
# Priority: DATABASE_URL env var > DB_PATH env var > local dev default
database_url = os.getenv("DATABASE_URL")
if database_url:
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    # Fall back to DB_PATH env var (absolute path, e.g. /data/app.db on Railway)
    # or local dev path relative to this file
    db_path = os.getenv("DB_PATH")
    if db_path:
        # Use provided absolute path as-is
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path.replace(chr(92), '/')}"
    else:
        # Default: local dev path (relative to this file)
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.db")
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path.replace(chr(92), '/')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False  # Set to True in production with HTTPS

# Email configuration
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "True").lower() == "true"
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER", "noreply@wikifactcheck.com")
app.config["APP_URL"] = os.getenv("APP_URL", "http://localhost:5000")

mail = Mail(app)

db.init_app(app)
migrate = Migrate(app, db, render_as_batch=True)  # render_as_batch=True required for SQLite ALTER TABLE support

# Verify Flask-Migrate is properly initialized
if 'migrate' not in app.extensions:
    app.logger.warning("Flask-Migrate not found in app.extensions")
else:
    app.logger.info("Flask-Migrate initialized successfully")

# Configure logging (outputs to stdout, Railway captures automatically)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout
)
app.config["DEBUG"] = os.getenv("FLASK_DEBUG", "false").lower() == "true"


# CLI Commands
@app.cli.command()
def init_db():
    """Initialize the database."""
    db.create_all()
    print("[OK] Database initialized")
    seed_default_config()
    print("[OK] Default config seeded")


@app.cli.command()
def import_jsonl():
    """Import a JSONL file into a new dataset (uses sys.argv for args)."""
    import sys
    if len(sys.argv) < 3:
        print("Usage: flask import-jsonl <path> <dataset_name>")
        return

    jsonl_path = sys.argv[1]
    dataset_name = sys.argv[2]

    path = Path(jsonl_path)
    if not path.exists():
        print(f"[ERROR] File not found: {jsonl_path}")
        return

    dataset = Dataset(name=dataset_name, is_active=True)
    db.session.add(dataset)
    db.session.commit()
    print(f"[OK] Created dataset: {dataset_name} (ID: {dataset.id})")

    result = parse_jsonl_file(str(path), dataset)
    print(f"[OK] Loaded: {result['loaded']}")
    print(f"[SKIP] Skipped duplicates: {result['skipped_duplicates']}")
    if result["errors"]:
        print(f"[ERROR] Errors: {len(result['errors'])}")
        for error in result["errors"][:5]:  # Show first 5
            print(f"  - {error}")


# ============================================================================
# HTML Routes
# ============================================================================


@app.route("/")
def index():
    """Home page — landing page if not logged in, dashboard if logged in."""
    user = get_current_user()
    if not user:
        return render_template("landing.html")
    # Check if session has admin token auth (from /admin/login)
    if session.get("admin_authenticated"):
        return redirect(url_for("admin_page"))
    # All logged-in annotators go to dashboard (test is optional, taken when user decides)
    return redirect(url_for("dashboard_page"))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    """Login page (annotators only — admins use /admin/login with token)."""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        wiki_username = request.form.get("wiki_username", "").strip()
        if not email:
            return render_template("login.html", error="Email is required")
        if not wiki_username:
            return render_template("login.html", error="Wikipedia username is required")
        do_login(email, wiki_username=wiki_username)
        # All logged-in users go to dashboard (test is optional)
        return redirect(url_for("dashboard_page"))
    return render_template("login.html")


@app.route("/test/post-login")
@login_required
def test_post_login_page():
    """Qualification test page (after login, before test submission)."""
    user = get_current_user()
    # If already approved, go to annotation
    if user.test_approved_by_admin:
        return redirect(url_for("annotate_page"))
    # Get test samples
    test_pairs = Pair.query.filter_by(is_test_sample=True).all()
    return render_template("test_post_login.html", test_pairs=test_pairs)


@app.route("/test/results")
@login_required
def test_results_page():
    """Show test results (after submission, waiting for admin review)."""
    user = get_current_user()
    # If approved, go to annotation
    if user.test_approved_by_admin:
        return redirect(url_for("annotate_page"))
    # If never submitted, go back to test
    if not user.test_submitted:
        return redirect(url_for("test_post_login_page"))
    return render_template("test_results.html", user=user)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login_page():
    """Secret token-based admin login."""
    if request.method == "POST":
        token = request.form.get("token", "").strip()
        admin_token = os.getenv("ADMIN_SECRET_TOKEN", "")

        if token and admin_token and token == admin_token:
            # Create/get system admin user for tracking dataset uploads
            admin_user = User.query.filter_by(email="admin@system.internal").first()
            if not admin_user:
                admin_user = User(email="admin@system.internal", is_admin=True)
                db.session.add(admin_user)
                db.session.commit()

            # Log admin login
            AuditLog.record(
                action="admin_login",
                actor_user_id=admin_user.id,
                actor_email=admin_user.email,
                details=request.remote_addr
            )
            db.session.commit()

            # Set session
            session["admin_authenticated"] = True
            session["is_admin"] = True
            session["user_id"] = admin_user.id  # Required for get_current_user()
            return redirect(url_for("admin_page"))
        else:
            return render_template("admin_login.html", error="Invalid token")

    return render_template("admin_login.html")


@app.route("/admin/preview")
@admin_required
def admin_preview():
    """Admin preview of annotation interface (read-only, no qualification required)."""
    return render_template("annotate.html", preview_mode=True)


@app.route("/logout")
def logout():
    """Logout."""
    do_logout()
    return redirect(url_for("index"))


@app.route("/test")
@login_required
def test_page():
    """Qualification test page."""
    user = get_current_user()
    if user.qualification_passed:
        return redirect(url_for("annotate_page"))

    # Get test samples
    test_pairs = Pair.query.filter_by(is_test_sample=True).all()
    return render_template("test.html", test_pairs=test_pairs)


@app.route("/annotate")
@login_required
def annotate_page():
    """Annotation interface — full if approved, read-only preview if not."""
    user = get_current_user()
    preview_mode = not user.test_approved_by_admin
    return render_template("annotate.html", preview_mode=preview_mode)


@app.route("/history")
@login_required
def history_page():
    """View and manage past annotations."""
    return render_template("history.html")


@app.route("/dashboard")
@login_required
def dashboard_page():
    """Dashboard — admin panel for admins, personal stats for annotators."""
    user = get_current_user()
    if user.is_admin:
        return render_template("dashboard.html")  # Admin dashboard
    else:
        return render_template("dashboard_personal.html")  # Personal dashboard


@app.route("/settings")
@login_required
def settings_page():
    """User settings page."""
    return render_template("settings.html")


@app.route("/admin")
@admin_required
def admin_page():
    """Admin control panel."""
    return render_template("admin.html")


# ============================================================================
# API Routes
# ============================================================================


@app.route("/auth/me")
@login_required
def api_auth_me():
    """Get current user info."""
    user = get_current_user()
    return jsonify({
        "id": user.id,
        "email": user.email,
        "is_admin": user.is_admin,
        "qualification_passed": user.qualification_passed,
    })


# Import blueprint routes
from routes_annotate import annotate_bp
from routes_admin import admin_bp
from routes_dashboard import dashboard_bp
from routes_settings import settings_bp

app.register_blueprint(annotate_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(settings_bp)


# Context processors
@app.context_processor
def inject_current_user():
    """Inject current_user into all templates for nav bar and auth checks."""
    return {"current_user": get_current_user()}


# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    app.logger.exception("Unhandled exception")
    db.session.rollback()
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)
