from flask import session, request, jsonify, redirect, url_for
from functools import wraps
from datetime import datetime
from models import db, User
import os


def get_admin_emails():
    """Get list of admin emails from environment variable."""
    admin_emails_str = os.getenv("ADMIN_EMAILS", "")
    return [email.strip() for email in admin_emails_str.split(",") if email.strip()]


def is_admin_email(email):
    """Check if an email is in the admin list."""
    return email in get_admin_emails()


def get_current_user():
    """Get the current user from session, or None if not logged in."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return User.query.get(user_id)


def login_required(f):
    """Decorator to require login. Handles both HTML and API routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_user():
            if request.path.startswith("/api"):
                return jsonify({"error": "Unauthorized"}), 401
            else:
                return redirect(url_for("login_page"))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Decorator to require admin access (token-based only)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Only token-based admin auth is allowed (via /admin/login)
        if not session.get("admin_authenticated"):
            if request.path.startswith("/api"):
                return jsonify({"error": "Forbidden"}), 403
            else:
                return redirect(url_for("admin_login_page"))
        return f(*args, **kwargs)

    return decorated_function


def do_login(email, wiki_username=None):
    """
    Log in a user by email (email-only, no password).
    Creates the user if they don't exist.
    Optionally saves wiki_username if provided.
    """
    email = email.lower().strip()

    # Upsert user
    user = User.query.filter_by(email=email).first()
    if user is None:
        user = User(email=email)
        db.session.add(user)

    # Check if this email is an admin
    user.is_admin = is_admin_email(email)
    user.last_login = datetime.utcnow()

    # Save wiki_username if provided
    if wiki_username and wiki_username.strip():
        user.wiki_username = wiki_username.strip()
        user.wiki_username_provided = True

    db.session.commit()

    # Set session
    session["user_id"] = user.id
    return user


def do_logout():
    """Log out the current user."""
    session.clear()
