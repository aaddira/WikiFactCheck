import os
from pathlib import Path
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from dotenv import load_dotenv
from datetime import datetime

from models import db, User, Dataset, Pair, Annotation, Claim, Skip, Config, TestSubmission
from auth import do_login, do_logout, login_required, admin_required, get_current_user
from data_loader import parse_jsonl_file, seed_default_config

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Use absolute path for SQLite database
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path.replace(chr(92), '/')}"  # Convert backslashes to forward slashes
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
    """Home page — landing page if not logged in, otherwise redirect based on status."""
    user = get_current_user()
    if not user:
        return render_template("landing.html")
    # Check if session has admin token auth (from /admin/login)
    if session.get("admin_authenticated"):
        return redirect(url_for("admin_page"))
    # If test not submitted yet, go to test post-login page
    if not user.test_submitted:
        return redirect(url_for("test_post_login_page"))
    # If test submitted but not approved yet, show test results
    if not user.test_approved_by_admin:
        return redirect(url_for("test_results_page"))
    # If approved, go to annotation page
    return redirect(url_for("annotate_page"))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    """Login page (annotators only — admins use /admin/login with token)."""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        wiki_username = request.form.get("wiki_username", "").strip()
        if email:
            do_login(email, wiki_username=wiki_username)
            user = get_current_user()
            # Route to test post-login page or annotation based on status
            if not user.test_submitted:
                return redirect(url_for("test_post_login_page"))
            elif not user.test_approved_by_admin:
                return redirect(url_for("test_results_page"))
            else:
                return redirect(url_for("annotate_page"))
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
            # Mark session as authenticated admin (without needing email)
            session["admin_authenticated"] = True
            session["is_admin"] = True
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
    return redirect(url_for("login_page"))


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
    """Annotation interface."""
    user = get_current_user()
    if not user.qualification_passed:
        return redirect(url_for("test_page"))
    return render_template("annotate.html")


@app.route("/dashboard")
@login_required
def dashboard_page():
    """Results dashboard."""
    return render_template("dashboard.html")


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

app.register_blueprint(annotate_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(dashboard_bp)


# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)
