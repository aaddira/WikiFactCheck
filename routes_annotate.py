from flask import Blueprint, jsonify, request
from models import db, User, Pair, Annotation, Config, TestSubmission, Skip
from auth import login_required, get_current_user, admin_required
from assignment import get_next_pair, release_claim, get_annotators_per_sample
from datetime import datetime
import uuid

annotate_bp = Blueprint("annotate", __name__, url_prefix="/api")


@annotate_bp.route("/pair/preview", methods=["GET"])
def api_pair_preview():
    """Get a random non-test pair for landing page preview (public access)."""
    # Return a random non-test pair from the database for preview
    import random
    total = Pair.query.filter_by(is_test_sample=False).count()
    if total == 0:
        pair = None
    else:
        offset = random.randint(0, max(0, total - 1))
        pair = Pair.query.filter_by(is_test_sample=False).offset(offset).first()

    if not pair:
        return jsonify({
            "status": "no_samples",
            "pair": None
        }), 200

    return jsonify({
        "status": "ok",
        "pair": {
            "id": pair.id,
            "pair_id": pair.pair_id,
            "passage_text": pair.passage_text,
            "passage_context": pair.passage_context,
            "passage_word_count": pair.passage_word_count,
            "article_title": pair.article_title,
            "citation_raw_text": pair.citation_raw_text,
            "citation_title": pair.citation_title,
            "citation_journal": pair.citation_journal,
            "citation_authors": pair.citation_authors,
            "citation_year": pair.citation_year,
            "citation_raw_word_count": pair.citation_raw_word_count,
        }
    })


@annotate_bp.route("/user/status")
@login_required
def api_user_status():
    """Get user qualification/annotation status."""
    user = get_current_user()
    cap = user.max_annotations_cap
    remaining = cap - user.annotations_count if cap else None

    return jsonify({
        "user_id": user.id,
        "email": user.email,
        "qualification_passed": user.qualification_passed,
        "qualification_score": user.qualification_score,
        "annotations_count": user.annotations_count,
        "max_annotations_cap": cap,
        "remaining_until_cap": remaining,
        "annotation_target": user.annotation_target,
    })


@annotate_bp.route("/user/target", methods=["GET", "PUT"])
@login_required
def api_user_target():
    """Get or set user's personal annotation target."""
    user = get_current_user()

    if request.method == "GET":
        return jsonify({
            "annotation_target": user.annotation_target,
            "annotations_count": user.annotations_count,
        })

    # PUT: set target
    data = request.get_json() or {}
    target = data.get("target")

    if target is not None:
        target = int(target) if target else None
        if target is not None and target < 1:
            return jsonify({"error": "Target must be at least 1"}), 400
        user.annotation_target = target
        db.session.commit()

    return jsonify({
        "status": "updated",
        "annotation_target": user.annotation_target,
    })


@annotate_bp.route("/pair/next", methods=["GET"])
@login_required
def api_pair_next():
    """Get the next pair to annotate using smart assignment."""
    user = get_current_user()

    if not user.test_approved_by_admin:
        return jsonify({"error": "Must be approved by admin to annotate"}), 403

    result = get_next_pair(user.id)
    status = result["status"]
    pair = result["pair"]

    if status in ["cap_reached", "project_complete", "no_candidates"]:
        return jsonify({"status": status}), 200

    if status == "error":
        return jsonify({"error": "Error getting next pair"}), 500

    # status == "ok"
    return jsonify({
        "status": "ok",
        "pair": {
            "id": pair.id,
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
            "citation_raw_word_count": pair.citation_raw_word_count,
        }
    })


@annotate_bp.route("/pair/<int:pair_id>", methods=["GET"])
@login_required
def api_pair_get(pair_id):
    """Get a specific pair by ID."""
    pair = Pair.query.get(pair_id)
    if not pair:
        return jsonify({"error": "Pair not found"}), 404

    return jsonify({
        "id": pair.id,
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
        "citation_raw_word_count": pair.citation_raw_word_count,
    })


@annotate_bp.route("/annotation", methods=["POST"])
@login_required
def api_annotation_save():
    """Save an annotation (label, quote, explanation)."""
    user = get_current_user()
    data = request.get_json() or {}

    pair_id = data.get("pair_id")
    label = data.get("label")
    quote = data.get("quote", "").strip()
    explanation = data.get("explanation", "").strip()

    if not pair_id or not label:
        return jsonify({"error": "Missing pair_id or label"}), 400

    pair = Pair.query.get(pair_id)
    if not pair:
        return jsonify({"error": "Pair not found"}), 404

    # Validate label
    valid_labels = ["TRUE", "FALSE", "MIXED", "NO_SUFFICIENT_INFO", "UNVERIFIABLE"]
    if label not in valid_labels:
        return jsonify({"error": f"Invalid label. Must be one of: {valid_labels}"}), 400

    # Check if already annotated
    existing = Annotation.query.filter_by(pair_id=pair_id, user_id=user.id).first()
    if existing:
        # Update existing annotation
        existing.label = label
        existing.quote = quote
        existing.explanation = explanation
        existing.updated_at = datetime.utcnow()
    else:
        # Create new annotation
        annotation = Annotation(
            pair_id=pair_id,
            user_id=user.id,
            label=label,
            quote=quote,
            explanation=explanation,
        )
        db.session.add(annotation)
        pair.annotation_count += 1
        user.annotations_count += 1

    # Release the claim
    release_claim(pair_id, user.id)

    db.session.commit()

    return jsonify({
        "status": "saved",
        "pair_id": pair_id,
        "label": label,
    })


@annotate_bp.route("/annotation/skip", methods=["POST"])
@login_required
def api_annotation_skip():
    """Skip a pair (remove from queue for this user)."""
    user = get_current_user()
    data = request.get_json() or {}
    pair_id = data.get("pair_id")

    if not pair_id:
        return jsonify({"error": "Missing pair_id"}), 400

    pair = Pair.query.get(pair_id)
    if not pair:
        return jsonify({"error": "Pair not found"}), 404

    # Check if already skipped
    from models import Skip
    existing_skip = Skip.query.filter_by(pair_id=pair_id, user_id=user.id).first()
    if not existing_skip:
        skip = Skip(pair_id=pair_id, user_id=user.id)
        db.session.add(skip)

    # Release the claim
    release_claim(pair_id, user.id)

    db.session.commit()

    return jsonify({"status": "skipped", "pair_id": pair_id})


@annotate_bp.route("/progress")
@login_required
def api_progress():
    """Get user's annotation progress."""
    user = get_current_user()

    # Get all test pairs
    test_pairs_count = Pair.query.filter_by(is_test_sample=True).count()

    # Get active dataset pairs (non-test)
    active_pairs_count = Pair.query.filter(
        Pair.is_test_sample == False,
        Pair.dataset_id.in_(
            db.session.query(db.func.id).select_from(db.session.query(
                db.text("id")
            ).select_from(Pair).distinct().subquery())
        )
    ).count()

    cap = user.max_annotations_cap
    remaining = cap - user.annotations_count if cap else None

    return jsonify({
        "annotations_count": user.annotations_count,
        "max_annotations_cap": cap,
        "remaining_until_cap": remaining,
        "test_pairs_count": test_pairs_count,
        "active_pairs_count": active_pairs_count,
    })


@annotate_bp.route("/test/save-progress", methods=["POST"])
@login_required
def api_test_save_progress():
    """Save test answers without submitting (resumes later)."""
    user = get_current_user()
    data = request.get_json() or {}
    answers = data.get("answers", {})  # {pair_id_str: {label, quote, explanation}, ...}

    if not answers:
        return jsonify({"error": "No answers provided"}), 400

    # Use or create a batch ID for this test attempt
    batch_id = request.headers.get("X-Test-Batch-ID") or str(uuid.uuid4())

    try:
        for pair_id_str, answer_data in answers.items():
            pair_id = int(pair_id_str)
            pair = Pair.query.get(pair_id)
            if not pair or not pair.is_test_sample:
                continue

            label = answer_data.get("label")
            quote = answer_data.get("quote", "").strip()
            explanation = answer_data.get("explanation", "").strip()

            # Check if already exists
            existing = TestSubmission.query.filter_by(
                user_id=user.id,
                pair_id=pair_id,
                submission_batch_id=batch_id
            ).first()

            if existing:
                existing.label = label
                existing.quote = quote
                existing.explanation = explanation
                existing.updated_at = datetime.utcnow()
            else:
                submission = TestSubmission(
                    user_id=user.id,
                    pair_id=pair_id,
                    label=label,
                    quote=quote,
                    explanation=explanation,
                    submission_batch_id=batch_id,
                    is_submitted=False,
                )
                db.session.add(submission)

        db.session.commit()
        return jsonify({
            "status": "saved",
            "batch_id": batch_id,
            "answers_saved": len(answers)
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@annotate_bp.route("/test/submit", methods=["POST"])
@login_required
def api_test_submit():
    """Submit qualification test answers for admin review."""
    user = get_current_user()
    data = request.get_json() or {}
    answers = data.get("answers", {})  # {pair_id_str: {label, quote, explanation}, ...}

    if not answers:
        return jsonify({"error": "No answers provided"}), 400

    # Create a batch ID for this submission
    batch_id = str(uuid.uuid4())

    # Get test pairs for scoring
    test_pairs = Pair.query.filter_by(is_test_sample=True).all()
    test_pair_ids = {p.id: p for p in test_pairs}

    correct = 0
    total = len(test_pairs)

    try:
        for pair_id_str, answer_data in answers.items():
            pair_id = int(pair_id_str)
            pair = test_pair_ids.get(pair_id)
            if not pair:
                continue

            label = answer_data.get("label")
            quote = answer_data.get("quote", "").strip()
            explanation = answer_data.get("explanation", "").strip()

            # Check if they got it correct
            if pair.correct_label == label:
                correct += 1

            # Save to TestSubmission
            existing = TestSubmission.query.filter_by(
                user_id=user.id,
                pair_id=pair_id,
                submission_batch_id=batch_id
            ).first()

            if existing:
                existing.label = label
                existing.quote = quote
                existing.explanation = explanation
                existing.is_submitted = True
            else:
                submission = TestSubmission(
                    user_id=user.id,
                    pair_id=pair_id,
                    label=label,
                    quote=quote,
                    explanation=explanation,
                    submission_batch_id=batch_id,
                    is_submitted=True,
                )
                db.session.add(submission)

        # Mark user test as submitted (but NOT qualified yet - waiting for admin)
        user.test_submitted = True
        user.test_submission_date = datetime.utcnow()
        user.qualification_score = correct  # Store score for display

        db.session.commit()

        return jsonify({
            "status": "submitted",
            "score": correct,
            "total": total,
            "message": "Your test has been submitted for review. The research team will notify you within 1-2 business days."
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@annotate_bp.route("/test/retake", methods=["POST"])
@login_required
def api_test_retake():
    """Reset test submission to allow retaking."""
    user = get_current_user()

    try:
        # Delete all test submissions for this user
        TestSubmission.query.filter_by(user_id=user.id).delete()

        # Reset test submitted flag (but keep scores for history)
        user.test_submitted = False
        user.test_submission_date = None

        db.session.commit()
        return jsonify({"status": "reset"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
