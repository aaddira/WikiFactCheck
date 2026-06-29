from flask import Blueprint, jsonify, request
from models import db, Annotation, Pair, User, Config
from auth import login_required
from assignment import get_annotators_per_sample, get_min_samples_for_target
from sqlalchemy import func

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/results")


@dashboard_bp.route("/summary")
@login_required
def api_results_summary():
    """Get summary statistics (optionally filtered by citation_type)."""
    citation_type = request.args.get("citation_type")  # JOURNAL, WEB, or None for all
    threshold = get_annotators_per_sample()
    min_target = get_min_samples_for_target()

    # Build base query
    pair_filter = Pair.query.filter_by(is_test_sample=False)
    if citation_type:
        pair_filter = pair_filter.filter_by(citation_type=citation_type)

    total_pairs = pair_filter.count()

    # Filter annotations by citation type if specified
    anno_filter = Annotation.query.join(Pair).filter(Pair.is_test_sample == False)
    if citation_type:
        anno_filter = anno_filter.filter(Pair.citation_type == citation_type)

    total_annotations = anno_filter.count()

    # Count pairs by annotation count
    q1 = pair_filter.filter(Pair.annotation_count >= 1)
    anno_1_plus = q1.count()

    q2 = pair_filter.filter(Pair.annotation_count >= 2)
    anno_2_plus = q2.count()

    q3 = pair_filter.filter(Pair.annotation_count >= threshold)
    anno_threshold_plus = q3.count()

    completion_pct = (anno_threshold_plus / min_target * 100) if min_target > 0 else 0

    return jsonify({
        "citation_type": citation_type or "ALL",
        "total_pairs": total_pairs,
        "total_annotations": total_annotations,
        "pairs_with_1_annotation": anno_1_plus,
        "pairs_with_2_annotations": anno_2_plus,
        "pairs_with_threshold_annotations": anno_threshold_plus,
        "threshold": threshold,
        "min_target": min_target,
        "completion_pct": round(completion_pct, 1),
    })


@dashboard_bp.route("/by-annotator")
@login_required
def api_results_by_annotator():
    """Get annotation breakdown by annotator."""
    annotators = db.session.query(
        User.email,
        func.count(Annotation.id).label("annotation_count"),
        User.qualification_passed,
        User.qualification_score,
    ).outerjoin(Annotation).group_by(User.id).all()

    result = []
    for email, count, passed, score in annotators:
        status = "passed" if passed else ("failed" if score is not None else "not_tested")
        result.append({
            "email": email,
            "annotation_count": count or 0,
            "qualification_status": status,
        })

    return jsonify(result)


@dashboard_bp.route("/label-distribution")
@login_required
def api_results_label_distribution():
    """Get distribution of labels (optionally filtered by citation_type, excluding test samples)."""
    citation_type = request.args.get("citation_type")

    labels = [
        "TRUE",
        "FALSE",
        "MIXED",
        "NO_SUFFICIENT_INFO",
        "UNVERIFIABLE",
    ]

    # Build filter
    anno_filter = Annotation.query.join(Pair).filter(Pair.is_test_sample == False)
    if citation_type:
        anno_filter = anno_filter.filter(Pair.citation_type == citation_type)

    total = anno_filter.count()

    distribution = {}
    for label in labels:
        q = Annotation.query.join(Pair).filter(
            Annotation.label == label,
            Pair.is_test_sample == False
        )
        if citation_type:
            q = q.filter(Pair.citation_type == citation_type)

        count = q.count()
        pct = (count / total * 100) if total > 0 else 0
        distribution[label] = {
            "count": count,
            "percentage": round(pct, 1),
        }

    return jsonify({
        "citation_type": citation_type or "ALL",
        "distribution": distribution,
    })


@dashboard_bp.route("/per-dataset")
@login_required
def api_results_per_dataset():
    """Get annotation progress per dataset."""
    from models import Dataset

    datasets = Dataset.query.all()
    result = []

    for dataset in datasets:
        total_in_dataset = Pair.query.filter_by(
            dataset_id=dataset.id,
            is_test_sample=False
        ).count()

        annotated_in_dataset = db.session.query(
            func.count(Annotation.id)
        ).join(Pair).filter(
            Pair.dataset_id == dataset.id,
            Pair.is_test_sample == False
        ).scalar() or 0

        pct = (annotated_in_dataset / total_in_dataset * 100) if total_in_dataset > 0 else 0

        result.append({
            "dataset_id": dataset.id,
            "dataset_name": dataset.name,
            "citation_type": dataset.citation_type,
            "total_samples": total_in_dataset,
            "annotated_samples": annotated_in_dataset,
            "percentage": round(pct, 1),
        })

    return jsonify(result)


@dashboard_bp.route("/per-citation-type")
@login_required
def api_results_per_citation_type():
    """Get annotation progress aggregated by citation type (Journal vs Web)."""
    threshold = get_annotators_per_sample()

    result = {}
    for citation_type in ["JOURNAL", "WEB"]:
        total = Pair.query.filter_by(
            citation_type=citation_type,
            is_test_sample=False
        ).count()

        annotated = db.session.query(
            func.count(Annotation.id)
        ).join(Pair).filter(
            Pair.citation_type == citation_type,
            Pair.is_test_sample == False
        ).scalar() or 0

        complete = Pair.query.filter(
            Pair.citation_type == citation_type,
            Pair.annotation_count >= threshold,
            Pair.is_test_sample == False
        ).count()

        pct = (annotated / total * 100) if total > 0 else 0

        result[citation_type] = {
            "total_samples": total,
            "annotated_samples": annotated,
            "complete_samples": complete,
            "annotation_percentage": round(pct, 1),
        }

    return jsonify(result)
