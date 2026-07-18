from flask import Blueprint, jsonify, request, send_file, g, current_app
from models import db, Dataset, Pair, Annotation, User, Config, TestSubmission, AuditLog, Claim, Skip
from auth import admin_required, get_current_user
from data_loader import parse_jsonl_file
from io import StringIO, BytesIO
import json
import csv
from datetime import datetime, timedelta
from sqlalchemy import func
import os

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
    """Delete a dataset and all its pairs (with cascading annotations)."""
    user = g.user
    dataset = Dataset.query.get(dataset_id)
    if not dataset:
        return jsonify({"error": "Dataset not found"}), 404

    try:
        # Get all pairs in this dataset for cascading deletion
        pairs = Pair.query.filter_by(dataset_id=dataset_id).all()
        pair_ids = [p.id for p in pairs]
        annotation_count = 0

        # Delete in proper cascade order to avoid foreign key constraints
        # 1. Delete annotations for all pairs in this dataset
        if pair_ids:
            from models import Annotation, Claim, Skip
            annotation_count = Annotation.query.filter(
                Annotation.pair_id.in_(pair_ids)
            ).delete(synchronize_session=False)

            # 2. Delete claims for all pairs in this dataset
            Claim.query.filter(
                Claim.pair_id.in_(pair_ids)
            ).delete(synchronize_session=False)

            # 3. Delete skips for all pairs in this dataset
            Skip.query.filter(
                Skip.pair_id.in_(pair_ids)
            ).delete(synchronize_session=False)

            # 4. Delete test submissions for all pairs in this dataset
            TestSubmission.query.filter(
                TestSubmission.pair_id.in_(pair_ids)
            ).delete(synchronize_session=False)

        # 5. Delete all pairs in this dataset
        Pair.query.filter_by(dataset_id=dataset_id).delete(synchronize_session=False)

        # 6. Finally, delete the dataset
        db.session.delete(dataset)
        db.session.commit()

        # Snapshot dataset info after successful deletion
        AuditLog.record(
            action="dataset_delete",
            actor_user_id=user.id,
            actor_email=user.email,
            target_type="Dataset",
            target_id=str(dataset_id),
            details=json.dumps({
                "name": dataset.name,
                "citation_type": dataset.citation_type,
                "sample_count": dataset.sample_count,
                "annotations_deleted": annotation_count
            })
        )
        db.session.commit()

        return jsonify({
            "status": "deleted",
            "dataset_id": dataset_id,
            "annotations_deleted": annotation_count,
            "pairs_deleted": len(pair_ids)
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Error deleting dataset {dataset_id}")
        return jsonify({"error": f"Failed to delete dataset: {str(e)}"}), 500


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

    # Send approval email (async, non-blocking)
    send_approval_email(user)

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

    # Send rejection email (async, non-blocking)
    send_rejection_email(user, reason)

    return jsonify({
        "status": "rejected",
        "user_id": user_id,
        "email": user.email,
    })


def send_approval_email(user):
    """Send approval email to user (non-blocking, background thread)."""
    from flask import current_app
    import os
    import threading
    from sendgrid import SendGridAPIClient

    app = current_app._get_current_object()
    config = {
        'api_key': os.getenv('SENDGRID_API_KEY'),
        'from_email': os.getenv('SENDGRID_FROM_EMAIL', 'noreply@wikifactcheck.com'),
        'app_url': app.config.get('APP_URL'),
        'user_email': user.email,
        'cc_admin': os.getenv("MAIL_CC_ADMIN", "").strip()
    }

    def _send_in_background():
        try:
            with app.app_context():
                sg = SendGridAPIClient(config['api_key'])

                html_content = f"""
<h2>Great News!</h2>
<p>Hi {config['user_email']},</p>
<p>Congratulations! Your test submission has been reviewed and approved by our research team.</p>
<p>You are now qualified to begin contributing to our fact-checking research. You will receive $3 per annotation completed, in accordance with the research participation agreement.</p>
<p>Within the next few days, you will receive a formal research participation agreement detailing the annotation guidelines, payment terms, and data usage. Please review and sign it to proceed with annotating.</p>
<p><a href="{config['app_url']}/">Log in and get started</a></p>
<p>Thank you for contributing to this important research initiative!</p>
"""

                to_list = [{"email": config['user_email']}]
                cc_list = []
                if config['cc_admin']:
                    cc_list.append({"email": config['cc_admin']})

                payload = {
                    "personalizations": [
                        {
                            "to": to_list,
                            "cc": cc_list if cc_list else None,
                            "subject": "WikiFactCheck: You're Approved to Start Annotating"
                        }
                    ],
                    "from": {"email": config['from_email']},
                    "content": [
                        {
                            "type": "text/html",
                            "value": html_content
                        }
                    ]
                }

                # Remove None values
                if not payload['personalizations'][0]['cc']:
                    del payload['personalizations'][0]['cc']

                response = sg.client.mail.send.post(request_body=payload)
                app.logger.info(f"Approval email sent to {config['user_email']} (status: {response.status_code})")
        except Exception as e:
            app.logger.error(f"Error sending approval email to {config['user_email']}: {type(e).__name__}: {str(e)}")

    thread = threading.Thread(target=_send_in_background, daemon=True)
    thread.start()


def send_rejection_email(user, reason):
    """Send rejection email to user (non-blocking, background thread)."""
    from flask import current_app
    import os
    import threading
    from sendgrid import SendGridAPIClient

    app = current_app._get_current_object()
    config = {
        'api_key': os.getenv('SENDGRID_API_KEY'),
        'from_email': os.getenv('SENDGRID_FROM_EMAIL', 'noreply@wikifactcheck.com'),
        'app_url': app.config.get('APP_URL'),
        'user_email': user.email,
        'reason': reason,
        'cc_admin': os.getenv("MAIL_CC_ADMIN", "").strip()
    }

    def _send_in_background():
        try:
            with app.app_context():
                sg = SendGridAPIClient(config['api_key'])

                html_content = f"""
<h2>Test Submission Review</h2>
<p>Hi {config['user_email']},</p>
<p>Thank you for your submission and interest in contributing to our research. We have completed our initial review of your test responses.</p>
<p><strong>Status:</strong> {config['reason']}</p>
<p>We encourage you to review the task instructions and retake the test at your convenience. <a href="{config['app_url']}/">Log in to try again</a></p>
<p>If you have any questions about the task requirements or need clarification, please contact our research team.</p>
"""

                to_list = [{"email": config['user_email']}]
                cc_list = []
                if config['cc_admin']:
                    cc_list.append({"email": config['cc_admin']})

                payload = {
                    "personalizations": [
                        {
                            "to": to_list,
                            "cc": cc_list if cc_list else None,
                            "subject": "WikiFactCheck: Test Result"
                        }
                    ],
                    "from": {"email": config['from_email']},
                    "content": [
                        {
                            "type": "text/html",
                            "value": html_content
                        }
                    ]
                }

                # Remove None values
                if not payload['personalizations'][0]['cc']:
                    del payload['personalizations'][0]['cc']

                response = sg.client.mail.send.post(request_body=payload)
                app.logger.info(f"Rejection email sent to {config['user_email']} (status: {response.status_code})")
        except Exception as e:
            app.logger.error(f"Error sending rejection email to {config['user_email']}: {type(e).__name__}: {str(e)}")

    thread = threading.Thread(target=_send_in_background, daemon=True)
    thread.start()

    # Start email send in background thread (non-blocking)
    thread = threading.Thread(target=_send_in_background, daemon=True)
    thread.start()


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


# ============================================================================
# User Management (Admin Testing & Cleanup)
# ============================================================================


@admin_bp.route("/users", methods=["GET"])
@admin_required
def api_users_list():
    """List all users (for admin testing and management)."""
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([
        {
            "id": u.id,
            "email": u.email,
            "wiki_username": u.wiki_username,
            "is_admin": u.is_admin,
            "qualification_passed": u.qualification_passed,
            "qualification_score": u.qualification_score,
            "test_submitted": u.test_submitted,
            "test_approved_by_admin": u.test_approved_by_admin,
            "annotations_count": len(u.annotations) if u.annotations else 0,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in users
    ])


@admin_bp.route("/user/<int:user_id>", methods=["DELETE"])
@admin_required
def api_user_delete(user_id):
    """Delete a user and all their related data (annotations, claims, skips, test submissions)."""
    admin = g.user
    user = User.query.get(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    # Prevent deleting the system admin user
    if user.email == "admin@system.internal":
        return jsonify({"error": "Cannot delete system admin user"}), 403

    # Snapshot user data before deletion
    user_snapshot = {
        "email": user.email,
        "wiki_username": user.wiki_username,
        "qualification_score": user.qualification_score,
        "test_approved_by_admin": user.test_approved_by_admin,
        "annotations_count": len(user.annotations) if user.annotations else 0,
    }

    # Log deletion (before cascading deletes happen)
    AuditLog.record(
        action="user_delete",
        actor_user_id=admin.id,
        actor_email=admin.email,
        target_type="User",
        target_id=str(user_id),
        details=json.dumps(user_snapshot)
    )

    # Manually delete all related records (in proper order) to avoid cascade issues
    Annotation.query.filter_by(user_id=user_id).delete()
    Claim.query.filter_by(user_id=user_id).delete()
    Skip.query.filter_by(user_id=user_id).delete()
    TestSubmission.query.filter_by(user_id=user_id).delete()

    # Now delete the user
    db.session.delete(user)
    db.session.commit()

    return jsonify({
        "status": "deleted",
        "user_id": user_id,
        "email": user_snapshot["email"],
        "message": "User account and all related data deleted"
    })


# ============================================================================
# P1: Unified Annotators Dashboard
# ============================================================================


@admin_bp.route("/annotators/dashboard", methods=["GET"])
@admin_required
def api_annotators_dashboard():
    """Get unified annotators dashboard with all users and stats."""
    from sqlalchemy import and_, func

    try:
        # Get all annotators (non-admin)
        annotators = User.query.filter(User.is_admin == False).order_by(User.created_at.desc()).all()

        result = []
        total_approved = 0
        total_pending = 0
        agreement_rates = []

        for user in annotators:
            # Annotation count
            ann_count = Annotation.query.filter_by(user_id=user.id).count()

            # Calculate agreement rate (pairwise matches with other annotators)
            # Get all pairs where this user has annotated
            user_pairs = db.session.query(Annotation.pair_id).filter_by(user_id=user.id).subquery()
            total_pairs_with_overlap = db.session.query(func.count(Annotation.pair_id)).filter(
                Annotation.pair_id.in_(
                    db.session.query(Annotation.pair_id).group_by(Annotation.pair_id).having(
                        func.count(Annotation.id) > 1
                    )
                ),
                Annotation.user_id == user.id
            ).scalar() or 0

            # Count matching annotations with other annotators on same pair
            matching = db.session.query(func.count(Annotation.id)).filter(
                Annotation.user_id == user.id,
                Annotation.pair_id.in_(
                    db.session.query(Annotation.pair_id).filter(
                        Annotation.user_id != user.id
                    ).subquery()
                )
            ).scalar() or 0

            agreement_rate = 0
            if total_pairs_with_overlap > 0:
                agreement_rate = (matching / total_pairs_with_overlap) * 100

            if agreement_rate > 0:
                agreement_rates.append(agreement_rate)

            # Test status
            test_status = "not_submitted"
            if user.test_approved_by_admin:
                test_status = "approved"
                total_approved += 1
            elif user.test_submitted:
                test_status = "pending"
                total_pending += 1

            # Active status (logged in last 7 days)
            from datetime import timedelta
            recently_active = user.last_login and user.last_login > datetime.utcnow() - timedelta(days=7)

            result.append({
                "id": user.id,
                "email": user.email,
                "wiki_username": user.wiki_username or "—",
                "qualification_score": user.qualification_score or 0,
                "agreement_rate": round(agreement_rate, 1),
                "annotations_count": ann_count,
                "annotation_target": user.annotation_target or 300,
                "target_progress_pct": (ann_count / max(user.annotation_target or 300, 1)) * 100,
                "test_status": test_status,
                "test_submitted_at": user.test_submission_date.isoformat() if user.test_submission_date else None,
                "test_approval_date": user.test_approval_date.isoformat() if user.test_approval_date else None,
                "recent_activity": user.last_login.isoformat() if user.last_login else None,
                "is_active": recently_active,
                "actions": {
                    "can_approve": test_status == "pending",
                    "can_reject": test_status == "pending",
                    "can_view_answers": test_status in ("pending", "approved")
                }
            })

        # Summary stats
        avg_agreement = sum(agreement_rates) / len(agreement_rates) if agreement_rates else 0

        return jsonify({
            "annotators": result,
            "summary": {
                "total_annotators": len(annotators),
                "approved": total_approved,
                "pending_review": total_pending,
                "rejected": len(annotators) - total_approved - total_pending,
                "average_agreement_rate": round(avg_agreement, 1)
            }
        })

    except Exception as e:
        current_app.logger.exception("Error fetching annotators dashboard")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/annotators/<int:user_id>/test-answers", methods=["GET"])
@admin_required
def api_annotators_test_answers(user_id):
    """Get test answers for a specific user."""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Use existing helper function (defined earlier in this file)
        batch_id, answers = get_latest_test_submission_answers(user_id)

        return jsonify({
            "user_id": user_id,
            "email": user.email,
            "wiki_username": user.wiki_username or "—",
            "score": user.qualification_score or 0,
            "submitted_at": user.test_submission_date.isoformat() if user.test_submission_date else None,
            "batch_id": batch_id,
            "total_questions": len(answers),
            "correct_answers": sum(1 for a in answers if a.get("is_correct")),
            "accuracy_pct": round((sum(1 for a in answers if a.get("is_correct")) / max(len(answers), 1)) * 100, 1),
            "answers": answers
        })

    except Exception as e:
        current_app.logger.exception(f"Error fetching test answers for user {user_id}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Email Confirmation Recovery (Admin)
# ============================================================================


@admin_bp.route("/users/fix-unconfirmed", methods=["POST"])
@admin_required
def api_fix_unconfirmed_users():
    """
    Fix users stuck with unconfirmed emails (old users from before confirmation was added).
    Marks them as confirmed if they have no valid confirmation token.
    """
    admin = g.user

    try:
        # Find users who are unconfirmed but have no valid token (or expired token)
        unconfirmed_users = User.query.filter_by(email_confirmed=False).all()

        fixed_count = 0
        for user in unconfirmed_users:
            # If no token or token is expired, mark as confirmed (they're old users)
            if not user.confirmation_token or user.confirmation_token_expired():
                user.email_confirmed = True
                user.confirmation_token = None
                user.confirmation_token_expires_at = None
                fixed_count += 1

        db.session.commit()

        AuditLog.record(
            action="fix_unconfirmed_users",
            actor_user_id=admin.id,
            actor_email=admin.email,
            target_type="User",
            target_id="bulk",
            details=json.dumps({"fixed_count": fixed_count})
        )
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": f"Fixed {fixed_count} unconfirmed users",
            "fixed_count": fixed_count
        })

    except Exception as e:
        current_app.logger.exception("Error fixing unconfirmed users")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/user/<int:user_id>/confirm-email", methods=["POST"])
@admin_required
def api_confirm_user_email(user_id):
    """Manually confirm a specific user's email."""
    admin = g.user
    user = User.query.get(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    try:
        user.email_confirmed = True
        user.confirmation_token = None
        user.confirmation_token_expires_at = None

        AuditLog.record(
            action="confirm_user_email",
            actor_user_id=admin.id,
            actor_email=admin.email,
            target_type="User",
            target_id=str(user_id),
            details=json.dumps({"user_email": user.email})
        )

        db.session.commit()

        return jsonify({
            "status": "success",
            "message": f"Confirmed email for {user.email}",
            "user_id": user_id
        })

    except Exception as e:
        current_app.logger.exception(f"Error confirming email for user {user_id}")
        return jsonify({"error": str(e)}), 500
