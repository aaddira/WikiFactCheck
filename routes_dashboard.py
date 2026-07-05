from flask import Blueprint, jsonify, request
from models import db, Annotation, Pair, User, Config
from auth import login_required
from assignment import get_annotators_per_sample, get_min_samples_for_target
from sqlalchemy import func
from collections import defaultdict

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
            "qualification_score": score,
        })

    return jsonify(result)


@dashboard_bp.route("/leaderboard")
@login_required
def api_results_leaderboard():
    """Get leaderboard of annotators ranked by annotation count."""
    annotators = db.session.query(
        User.wiki_username,
        User.email,
        func.count(Annotation.id).label("annotation_count"),
    ).outerjoin(Annotation).group_by(User.id).order_by(func.count(Annotation.id).desc()).all()

    result = []
    for wiki_username, email, count in annotators:
        result.append({
            "wiki_username": wiki_username or "Anonymous",
            "email": email,
            "annotations_count": count or 0,
        })

    return jsonify({"leaderboard": result})


def compute_pair_majority_label(pair_id):
    """
    Compute majority label for a pair (ties excluded).
    Returns (majority_label, voters, is_tie).
    """
    annotations = Annotation.query.filter_by(pair_id=pair_id).all()
    if not annotations:
        return None, [], False

    label_counts = defaultdict(int)
    for ann in annotations:
        label_counts[ann.label] += 1

    if not label_counts:
        return None, [], False

    max_count = max(label_counts.values())
    tied_labels = [label for label, count in label_counts.items() if count == max_count]

    if len(tied_labels) > 1:
        # Tie detected
        return None, list(label_counts.keys()), True

    majority_label = tied_labels[0]
    return majority_label, list(label_counts.keys()), False


@dashboard_bp.route("/agreement")
@login_required
def api_results_agreement():
    """
    Get inter-annotator agreement rates.
    For pairs with annotation_count >= 2, compute majority label agreement.
    Ties are excluded from denominators.
    """
    citation_type = request.args.get("citation_type")
    dataset_id = request.args.get("dataset_id", type=int)

    # Query qualifying pairs
    query = Pair.query.filter(
        Pair.annotation_count >= 2,
        Pair.is_test_sample == False
    )
    if citation_type:
        query = query.filter(Pair.citation_type == citation_type)
    if dataset_id:
        query = query.filter(Pair.dataset_id == dataset_id)

    pairs = query.all()

    if not pairs:
        return jsonify({
            "overall_agreement_pct": 0,
            "pairs_evaluated": 0,
            "by_dataset": {},
            "by_citation_type": {}
        })

    # Compute agreement metrics
    agreement_count = 0
    total_count = 0
    by_dataset = defaultdict(lambda: {"agreement": 0, "total": 0})
    by_citation_type = defaultdict(lambda: {"agreement": 0, "total": 0})

    for pair in pairs:
        majority_label, all_labels, is_tie = compute_pair_majority_label(pair.id)

        if not is_tie and majority_label:
            total_count += 1
            agreement_count += 1
            by_dataset[pair.dataset_id]["total"] += 1
            by_dataset[pair.dataset_id]["agreement"] += 1
            by_citation_type[pair.citation_type]["total"] += 1
            by_citation_type[pair.citation_type]["agreement"] += 1

    overall_pct = (agreement_count / total_count * 100) if total_count > 0 else 0

    return jsonify({
        "overall_agreement_pct": round(overall_pct, 1),
        "pairs_evaluated": total_count,
        "by_dataset": {
            str(ds_id): {
                "agreement_pct": round(stats["agreement"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0,
                "pairs": stats["total"]
            }
            for ds_id, stats in by_dataset.items()
        },
        "by_citation_type": {
            ct: {
                "agreement_pct": round(stats["agreement"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0,
                "pairs": stats["total"]
            }
            for ct, stats in by_citation_type.items()
        }
    })


@dashboard_bp.route("/agreement/by-annotator")
@login_required
def api_results_agreement_by_annotator():
    """
    Get per-annotator agreement rates.
    For each annotator: compare their labels to pair majority label (excluding ties).
    """
    annotators = User.query.all()
    result = []

    for user in annotators:
        # Get all annotations by this user
        user_annotations = Annotation.query.filter_by(user_id=user.id).all()

        if not user_annotations:
            result.append({
                "email": user.email,
                "agreement_rate_pct": None,
                "annotations_evaluated": 0
            })
            continue

        matches = 0
        total = 0

        for ann in user_annotations:
            # Get pair and check if it has >= 2 annotations
            pair = Pair.query.get(ann.pair_id)
            if not pair or pair.annotation_count < 2 or pair.is_test_sample:
                continue

            majority_label, all_labels, is_tie = compute_pair_majority_label(pair.id)

            if not is_tie and majority_label:
                total += 1
                if ann.label == majority_label:
                    matches += 1

        agreement_pct = (matches / total * 100) if total > 0 else None

        result.append({
            "email": user.email,
            "agreement_rate_pct": round(agreement_pct, 1) if agreement_pct is not None else None,
            "annotations_evaluated": total
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
