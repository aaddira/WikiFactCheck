from flask import Blueprint, jsonify, request, send_file, g, current_app
from models import db, Dataset, Pair, Annotation, User, Config, TestSubmission, AuditLog
from auth import admin_required, get_current_user
from data_loader import parse_jsonl_file
from io import StringIO, BytesIO
import json
import csv
from datetime import datetime
import os
from flask_mail import Mail, Message

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ============================================================================
# Dataset Management
# ============================================================================


@admin_bp.route("/dataset/list", methods=["GET"])
@admin_required
def api_dataset_list():
    """List all datasets."""
    datasets = Dataset.query.all()
    return jsonify([
        {
            "id": d.id,
            "name": d.name,
            "description": d.description,
            "citation_type": d.citation_type,
            "is_active": d.is_active,
            "sample_count": d.sample_count,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in datasets
    ])


@admin_bp.route("/dataset/upload", methods=["POST"])
@admin_required
def api_dataset_upload():
    """Upload a JSONL file and create a new dataset."""
    user = g.user  # Injected by @admin_required decorator
    name = request.form.get("name", "").strip()
    citation_type = request.form.get("citation_type", "JOURNAL").upper()
    file = request.files.get("file")

    if not name:
        return jsonify({"error": "Missing dataset name"}), 400
    if not file:
        return jsonify({"error": "Missing file"}), 400
    if citation_type not in ("JOURNAL", "WEB"):
        return jsonify({"error": "Invalid citation_type. Must be JOURNAL or WEB"}), 400

    # Create dataset
    dataset = Dataset(name=name, citation_type=citation_type, is_active=True, created_by_user_id=user.id)
    db.session.add(dataset)
    db.session.commit()

    # Parse file
    try:
        file_content = file.read().decode("utf-8")
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        result = parse_jsonl_file(tmp_path, dataset, citation_type=citation_type)

        import os
        os.unlink(tmp_path)

        # Log audit entry
        AuditLog.record(
            action="dataset_upload",
            actor_user_id=user.id,
            actor_email=user.email,
            target_type="Dataset",
            target_id=str(dataset.id),
            details=json.dumps({
                "name": name,
                "citation_type": citation_type,
                "loaded": result["loaded"],
                "skipped_duplicates": result["skipped_duplicates"]
            })
        )
        db.session.commit()

        return jsonify({
            "dataset_id": dataset.id,
            "citation_type": citation_type,
            "loaded": result["loaded"],
            "skipped_duplicates": result["skipped_duplicates"],
            "errors": result["errors"][:10],  # Return first 10 errors
        })

    except Exception as e:
        db.session.delete(dataset)
        db.session.commit()
        return jsonify({"error": str(e)}), 400


@admin_bp.route("/dataset/<int:dataset_id>", methods=["PUT"])
@admin_required
def api_dataset_update(dataset_id):
    """Update dataset (name, active status)."""
    user = g.user
    dataset = Dataset.query.get(dataset_id)
    if not dataset:
        return jsonify({"error": "Dataset not found"}), 404

    data = request.get_json() or {}
    if "name" in data:
        dataset.name = data["name"]
    if "is_active" in data:
        dataset.is_active = data["is_active"]

    AuditLog.record(
        action="dataset_update",
        actor_user_id=user.id,
        actor_email=user.email,
        target_type="Dataset",
        target_id=str(dataset_id),
        details=json.dumps(data)
    )
    db.session.commit()
    return jsonify({"status": "updated"})


@admin_bp.route("/dataset/<int:dataset_id>", methods=["DELETE"])
@admin_required
def api_dataset_delete(dataset_id):
    """Delete a dataset and all its pairs."""
    user = g.user
    dataset = Dataset.query.get(dataset_id)
    if not dataset:
        return jsonify({"error": "Dataset not found"}), 404

    # Snapshot dataset info before deletion
    AuditLog.record(
        action="dataset_delete",
        actor_user_id=user.id,
        actor_email=user.email,
        target_type="Dataset",
        target_id=str(dataset_id),
        details=json.dumps({
            "name": dataset.name,
            "citation_type": dataset.citation_type,
            "sample_count": dataset.sample_count
        })
    )
    db.session.delete(dataset)
    db.session.commit()
    return jsonify({"status": "deleted"})


# ============================================================================
# Configuration
# ============================================================================


@admin_bp.route("/config", methods=["GET"])
@admin_required
def api_config_get():
    """Get all config values."""
    configs = Config.query.all()
    return jsonify({
        c.key: json.loads(c.value) if c.value and c.value.startswith('{') else c.value
        for c in configs
    })


@admin_bp.route("/config/<key>", methods=["PUT"])
@admin_required
def api_config_set(key):
    """Set a config value."""
    user = g.user
    data = request.get_json() or {}
    value = data.get("value")

    if value is None:
        return jsonify({"error": "Missing value"}), 400

    # Capture old value before update
    old_config = Config.query.filter_by(key=key).first()
    old_value = old_config.value if old_config else None

    Config.set(key, value)

    # Log audit entry
    AuditLog.record(
        action="config_set",
        actor_user_id=user.id,
        actor_email=user.email,
        target_type="Config",
        target_id=key,
        details=json.dumps({
            "old_value": old_value,
            "new_value": str(value)
        })
    )
    db.session.commit()

    return jsonify({"status": "updated", "key": key, "value": value})


# ============================================================================
# Test Sample Management
# ============================================================================


@admin_bp.route("/test/random", methods=["GET"])
@admin_required
def api_test_random():
    """Get random pairs from a dataset for test sample selection."""
    dataset_id = request.args.get("dataset_id", type=int)
    count = request.args.get("count", default=5, type=int)

    if not dataset_id:
        return jsonify({"error": "Missing dataset_id"}), 400

    dataset = Dataset.query.get(dataset_id)
    if not dataset:
        return jsonify({"error": "Dataset not found"}), 404

    import random
    # Get random pairs from dataset (exclude already-marked test samples)
    pairs = Pair.query.filter_by(dataset_id=dataset_id, is_test_sample=False).all()
    if not pairs:
        return jsonify({"error": "No unmarked pairs in dataset"}), 404

    selected = random.sample(pairs, min(count, len(pairs)))
    return jsonify({
        "pairs": [
            {
                "id": p.id,
                "pair_id": p.pair_id,
                "passage_text": p.passage_text,
                "citation_raw_text": p.citation_raw_text,
                "article_title": p.article_title,
            }
            for p in selected
        ]
    })


@admin_bp.route("/test/pair", methods=["GET"])
@admin_required
def api_test_pair():
    """Get a specific pair by pair_id from a dataset for test sample selection."""
    dataset_id = request.args.get("dataset_id", type=int)
    pair_id = request.args.get("pair_id", type=str)

    if not dataset_id or not pair_id:
        return jsonify({"error": "Missing dataset_id or pair_id"}), 400

    pair = Pair.query.filter_by(dataset_id=dataset_id, pair_id=pair_id, is_test_sample=False).first()
    if not pair:
        return jsonify({"error": "Pair not found in dataset"}), 404

    return jsonify({
        "pair": {
            "id": pair.id,
            "pair_id": pair.pair_id,
            "passage_text": pair.passage_text,
            "citation_raw_text": pair.citation_raw_text,
            "article_title": pair.article_title,
        }
    })


@admin_bp.route("/test/mark-samples", methods=["POST"])
@admin_required
def api_test_mark_samples():
    """Mark samples as test samples with correct labels."""
    data = request.get_json() or {}
    samples = data.get("samples", [])  # [{pair_id: int, correct_label: str}, ...]

    for sample in samples:
        pair_id = sample.get("pair_id")
        correct_label = sample.get("correct_label")

        pair = Pair.query.get(pair_id)
        if pair:
            pair.is_test_sample = True
            pair.correct_label = correct_label

    db.session.commit()
    return jsonify({"status": "marked", "count": len(samples)})


@admin_bp.route("/test/results", methods=["GET"])
@admin_required
def api_test_results():
    """Get test results for all users."""
    users = User.query.filter(User.qualification_score.isnot(None)).all()
    return jsonify([
        {
            "user_id": u.id,
            "email": u.email,
            "score": u.qualification_score,
            "passed": u.qualification_passed,
            "qualification_date": u.qualification_date.isoformat() if u.qualification_date else None,
        }
        for u in users
    ])


@admin_bp.route("/test/<int:user_id>/override", methods=["PUT"])
@admin_required
def api_test_override(user_id):
    """Manually override a user's qualification status."""
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}
    passed = data.get("passed", False)

    user.qualification_passed = passed
    db.session.commit()

    return jsonify({"status": "updated", "user_id": user_id, "passed": passed})


# ============================================================================
# Test Submission Review
# ============================================================================


def get_latest_test_submission_answers(user_id):
    """Get answers from the most recent test submission batch for a user."""
    submissions = TestSubmission.query.filter_by(
        user_id=user_id,
        is_submitted=True
    ).order_by(TestSubmission.created_at.desc()).all()

    if not submissions:
        return None, []

    # Get the most recent batch ID
    latest_batch_id = submissions[0].submission_batch_id
    latest_batch = [s for s in submissions if s.submission_batch_id == latest_batch_id]

    answers = []
    for sub in latest_batch:
        pair = Pair.query.get(sub.pair_id)
        answers.append({
            "pair_id": sub.pair_id,
            "passage_text": pair.passage_text if pair else None,
            "article_title": pair.article_title if pair else None,
            "user_answer": sub.label,
            "correct_answer": pair.correct_label if pair else None,
            "quote": sub.quote,
            "explanation": sub.explanation,
            "is_correct": sub.label == pair.correct_label if pair else False,
        })

    return latest_batch_id, answers


@admin_bp.route("/test/submissions/pending", methods=["GET"])
@admin_required
def api_test_submissions_pending():
    """Get all pending test submissions (submitted but not approved)."""
    users = User.query.filter(
        User.test_submitted == True,
        User.test_approved_by_admin == False
    ).all()

    result = []
    for user in users:
        _, answers = get_latest_test_submission_answers(user.id)

        result.append({
            "user_id": user.id,
            "email": user.email,
            "score": user.qualification_score,
            "submitted_at": user.test_submission_date.isoformat() if user.test_submission_date else None,
            "answers": answers,
        })

    return jsonify(result)


@admin_bp.route("/test/submissions/<int:user_id>/approve", methods=["POST"])
@admin_required
def api_test_submission_approve(user_id):
    """Approve a user's test submission and send approval email."""
    admin = g.user
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    if not user.test_submitted:
        return jsonify({"error": "User has not submitted test"}), 400

    user.test_approved_by_admin = True
    user.test_approval_date = datetime.utcnow()

    AuditLog.record(
        action="test_submission_approve",
        actor_user_id=admin.id,
        actor_email=admin.email,
        target_type="User",
        target_id=str(user_id),
        details=json.dumps({
            "email": user.email,
            "score": user.qualification_score
        })
    )
    db.session.commit()

    # Send approval email
    try:
        send_approval_email(user)
    except Exception as e:
        # Log error but don't fail the approval
        from flask import current_app
        current_app.logger.exception(f"Error sending approval email to {user.email}")

    return jsonify({
        "status": "approved",
        "user_id": user_id,
        "email": user.email,
    })


@admin_bp.route("/test/submissions/<int:user_id>/reject", methods=["POST"])
@admin_required
def api_test_submission_reject(user_id):
    """Reject a user's test submission and send rejection email."""
    admin = g.user
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    if not user.test_submitted:
        return jsonify({"error": "User has not submitted test"}), 400

    data = request.get_json() or {}
    reason = data.get("reason", "Your test submission was not approved. Please review the instructions and retake the test.")

    # Snapshot latest submission answers before deletion
    _, answers = get_latest_test_submission_answers(user_id)

    # Log audit entry (before deletion so we have the data)
    AuditLog.record(
        action="test_submission_reject",
        actor_user_id=admin.id,
        actor_email=admin.email,
        target_type="User",
        target_id=str(user_id),
        details=json.dumps({
            "email": user.email,
            "reason": reason,
            "answers": answers
        })
    )

    # Reset test submission to allow retaking
    TestSubmission.query.filter_by(user_id=user_id).delete()
    user.test_submitted = False
    user.test_submission_date = None
    db.session.commit()

    # Send rejection email
    try:
        send_rejection_email(user, reason)
    except Exception as e:
        from flask import current_app
        current_app.logger.exception(f"Error sending rejection email to {user.email}")

    return jsonify({
        "status": "rejected",
        "user_id": user_id,
        "email": user.email,
    })


def send_approval_email(user):
    """Send approval email to user."""
    from flask_mail import Mail, Message
    from flask import current_app
    import os

    mail = Mail(current_app)
    recipients = [user.email]

    # CC admin if configured
    admin_cc = os.getenv("MAIL_CC_ADMIN", "").strip()
    if admin_cc:
        recipients.append(admin_cc)

    msg = Message(
        subject="WikiFactCheck: You're Approved to Start Annotating",
        recipients=recipients,
        html=f"""
<h2>Great News!</h2>
<p>Hi {user.email},</p>
<p>Congratulations! Your test submission has been reviewed and approved by our research team.</p>
<p>You can now start annotating Wikipedia citations and earning $3-5 per review.</p>
<p><a href="{current_app.config.get('APP_URL', 'https://app.example.com')}/">Log in and start annotating</a></p>
<p>Thank you for your contribution!</p>
"""
    )
    mail.send(msg)


def send_rejection_email(user, reason):
    """Send rejection email to user."""
    from flask_mail import Mail, Message
    from flask import current_app
    import os

    mail = Mail(current_app)
    recipients = [user.email]

    # CC admin if configured
    admin_cc = os.getenv("MAIL_CC_ADMIN", "").strip()
    if admin_cc:
        recipients.append(admin_cc)

    msg = Message(
        subject="WikiFactCheck: Test Result",
        recipients=recipients,
        html=f"""
<h2>Test Submission Review</h2>
<p>Hi {user.email},</p>
<p>Thank you for submitting your test. Unfortunately, we were unable to approve your submission at this time.</p>
<p><strong>Reason:</strong> {reason}</p>
<p>You can retake the test anytime. <a href="{current_app.config.get('APP_URL', 'https://app.example.com')}/">Log in to try again</a></p>
<p>If you have questions, please reach out to us.</p>
"""
    )
    mail.send(msg)


# ============================================================================
# Audit Log
# ============================================================================


@admin_bp.route("/audit-log", methods=["GET"])
@admin_required
def api_audit_log():
    """Get paginated audit log with filtering."""
    try:
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 50, type=int), 200)  # Cap at 200
        action = request.args.get("action", None, type=str)
        actor_email = request.args.get("actor_email", None, type=str)
        target_type = request.args.get("target_type", None, type=str)
        date_from = request.args.get("date_from", None, type=str)
        date_to = request.args.get("date_to", None, type=str)

        # Build query
        query = AuditLog.query
    except Exception as e:
        current_app.logger.exception("Error building audit log query parameters")
        return jsonify({"error": f"Failed to parse parameters: {str(e)}"}), 400

    if action:
        query = query.filter(AuditLog.action == action)
    if actor_email:
        query = query.filter(AuditLog.actor_email.ilike(f"%{actor_email}%"))
    if target_type:
        query = query.filter(AuditLog.target_type == target_type)
    if date_from:
        from datetime import datetime
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(AuditLog.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        from datetime import datetime
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.filter(AuditLog.created_at <= dt_to)
        except ValueError:
            pass

    try:
        # Paginate
        paginated = query.order_by(AuditLog.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
    except Exception as e:
        current_app.logger.exception("Error paginating audit logs")
        return jsonify({"error": f"Failed to fetch audit logs: {str(e)}"}), 500

    def parse_details(details_str):
        """Safely parse details JSON, fallback to string if invalid."""
        if not details_str:
            return None
        try:
            return json.loads(details_str)
        except (json.JSONDecodeError, ValueError):
            return details_str

    try:
        return jsonify({
            "logs": [
                {
                    "id": log.id,
                    "action": log.action,
                    "actor_user_id": log.actor_user_id,
                    "actor_email": log.actor_email,
                    "target_type": log.target_type,
                    "target_id": log.target_id,
                    "details": parse_details(log.details),
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in paginated.items
            ],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": paginated.total,
                "pages": paginated.pages,
                "has_prev": paginated.has_prev,
                "has_next": paginated.has_next,
            }
        })
    except Exception as e:
        current_app.logger.exception("Error formatting audit log response")
        return jsonify({"error": f"Failed to format response: {str(e)}"}), 500


# ============================================================================
# Export
# ============================================================================


@admin_bp.route("/export/jsonl", methods=["GET"])
@admin_required
def api_export_jsonl():
    """Export all annotations as JSONL."""
    annotations = Annotation.query.all()

    lines = []
    for ann in annotations:
        pair = ann.pair
        user = ann.annotator

        record = {
            "pair_id": pair.pair_id,
            "article_title": pair.article_title,
            "passage_text": pair.passage_text,
            "passage_context": pair.passage_context,
            "passage_word_count": pair.passage_word_count,
            "citation_title": pair.citation_title,
            "citation_journal": pair.citation_journal,
            "citation_doi": pair.citation_doi,
            "citation_year": pair.citation_year,
            "citation_authors": pair.citation_authors,
            "citation_raw_text": pair.citation_raw_text,
            "citation_source_url": pair.citation_source_url,
            "label": ann.label,
            "quote": ann.quote,
            "explanation": ann.explanation,
            "annotator": user.email,
            "timestamp": ann.created_at.isoformat() if ann.created_at else None,
        }
        lines.append(json.dumps(record))

    content = "\n".join(lines)
    return send_file(
        BytesIO(content.encode("utf-8")),
        mimetype="application/jsonl",
        as_attachment=True,
        download_name=f"annotations_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jsonl",
    )


@admin_bp.route("/export/csv", methods=["GET"])
@admin_required
def api_export_csv():
    """Export all annotations as CSV."""
    annotations = Annotation.query.all()

    output = StringIO()
    fieldnames = [
        "pair_id",
        "article_title",
        "passage_text",
        "citation_title",
        "citation_journal",
        "label",
        "quote",
        "explanation",
        "annotator",
        "timestamp",
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for ann in annotations:
        pair = ann.pair
        user = ann.annotator

        writer.writerow({
            "pair_id": pair.pair_id,
            "article_title": pair.article_title,
            "passage_text": pair.passage_text,
            "citation_title": pair.citation_title,
            "citation_journal": pair.citation_journal,
            "label": ann.label,
            "quote": ann.quote,
            "explanation": ann.explanation,
            "annotator": user.email,
            "timestamp": ann.created_at.isoformat() if ann.created_at else None,
        })

    csv_content = output.getvalue()
    return send_file(
        BytesIO(csv_content.encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"annotations_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
    )


@admin_bp.route("/export/test-results", methods=["GET"])
@admin_required
def api_export_test_results():
    """Export test results as CSV."""
    users = User.query.filter(User.qualification_score.isnot(None)).all()

    output = StringIO()
    fieldnames = ["email", "score", "passed", "qualification_date"]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for user in users:
        writer.writerow({
            "email": user.email,
            "score": user.qualification_score,
            "passed": user.qualification_passed,
            "qualification_date": user.qualification_date.isoformat() if user.qualification_date else None,
        })

    csv_content = output.getvalue()
    return send_file(
        BytesIO(csv_content.encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"test_results_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
    )
