from flask import Blueprint, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from auth import login_required, get_current_user, is_admin_email
from models import db, User
from sqlalchemy.exc import IntegrityError

settings_bp = Blueprint("settings", __name__, url_prefix="/api/settings")


@settings_bp.route("/profile", methods=["GET"])
@login_required
def api_settings_profile():
    """Get current user's profile info."""
    user = get_current_user()
    return jsonify({
        "id": user.id,
        "email": user.email,
        "wiki_username": user.wiki_username,
        "wiki_username_provided": user.wiki_username_provided,
        "qualification_passed": user.qualification_passed,
        "qualification_score": user.qualification_score,
        "test_submitted": user.test_submitted,
        "test_approved_by_admin": user.test_approved_by_admin,
        "annotations_count": user.annotations_count,
        "annotation_target": user.annotation_target,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    })


@settings_bp.route("/profile", methods=["PUT"])
@login_required
def api_settings_profile_update():
    """Update user's wiki username."""
    user = get_current_user()
    data = request.get_json() or {}

    wiki_username = data.get("wiki_username", "").strip()
    if wiki_username:
        user.wiki_username = wiki_username
        user.wiki_username_provided = True

    db.session.commit()
    return jsonify({"status": "success"}), 200


@settings_bp.route("/email", methods=["POST"])
@login_required
def api_settings_email():
    """Change user's email address."""
    user = get_current_user()
    data = request.get_json() or {}

    new_email = data.get("new_email", "").strip().lower()
    if not new_email:
        return jsonify({"error": "Email is required"}), 400

    # Basic email validation
    if "@" not in new_email or "." not in new_email:
        return jsonify({"error": "Invalid email format"}), 400

    # Check if email already exists (by another user)
    existing_user = User.query.filter_by(email=new_email).first()
    if existing_user and existing_user.id != user.id:
        return jsonify({"error": "Email already in use"}), 409

    try:
        user.email = new_email
        # Check if new email is in admin list and update is_admin accordingly
        user.is_admin = is_admin_email(new_email)
        db.session.commit()
        return jsonify({"status": "success"}), 200
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Email already in use"}), 409
