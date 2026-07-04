import random
import json
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from models import db, Pair, Annotation, Claim, Skip, Config, Dataset


def get_annotators_per_sample():
    """Get the configured annotators per sample threshold."""
    value = Config.get("ANNOTATORS_PER_SAMPLE", 3)
    if isinstance(value, str):
        return int(value)
    return value


def get_min_samples_for_target():
    """Get the configured minimum samples for target."""
    value = Config.get("MIN_SAMPLES_FOR_TARGET", 300)
    if isinstance(value, str):
        return int(value)
    return value


def get_domain_distribution():
    """Get the configured domain distribution (dict or JSON)."""
    value = Config.get("DOMAIN_DISTRIBUTION")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {"medicine": 50, "history": 30, "animals": 15, "artists": 5}
    return {"medicine": 50, "history": 30, "animals": 15, "artists": 5}


def compute_domain_targets(total_target, distribution):
    """
    Compute per-domain targets based on distribution percentages.
    Example: total=300, dist={medicine: 50, history: 30, animals: 15, artists: 5}
    Returns: {medicine: 150, history: 90, animals: 45, artists: 15}
    """
    targets = {}
    for domain, pct in distribution.items():
        targets[domain] = max(1, int(total_target * pct / 100))
    return targets


def count_domain_completion(domain):
    """
    Count pairs from a specific domain that have reached ANNOTATORS_PER_SAMPLE.
    """
    threshold = get_annotators_per_sample()
    count = db.session.query(db.func.count(Pair.id)).filter(
        Pair.research_domains.contains(domain),
        Pair.annotation_count >= threshold,
        Pair.is_test_sample == False
    ).scalar()
    return count or 0


def should_exclude_domain(domain, targets):
    """Check if a domain has hit its target and should be excluded."""
    completed = count_domain_completion(domain)
    target = targets.get(domain, 0)
    return completed >= target


def get_next_pair(user_id, timeout_minutes=30):
    """
    Smart assignment: return the next pair for an annotator to label.
    Returns: {pair: Pair object, status: "ok"|"cap_reached"|"project_complete"}

    Logic:
    1. Check if user hit annotation cap
    2. Check if project is complete (enough pairs hit ANNOTATORS_PER_SAMPLE)
    3. Query candidates: pairs not yet annotated/skipped by this user, not test samples,
       unclaimed or claim expired, filtered by domain distribution
    4. Tier into annotation_count groups: prefer pairs with more annotations already
    5. Random shuffle within each tier
    6. Return first available; create Claim record
    """
    from models import User

    user = User.query.get(user_id)
    if not user:
        return {"pair": None, "status": "error"}

    # Check annotation cap
    cap_enabled = Config.get("ANNOTATOR_CAP_ENABLED", "true")
    if isinstance(cap_enabled, str):
        cap_enabled = cap_enabled.lower() == "true"

    if cap_enabled and user.max_annotations_cap and user.annotations_count >= user.max_annotations_cap:
        return {"pair": None, "status": "cap_reached"}

    # Check project completion
    threshold = get_annotators_per_sample()
    min_target = get_min_samples_for_target()
    completed_count = db.session.query(db.func.count(Pair.id)).filter(
        Pair.annotation_count >= threshold,
        Pair.is_test_sample == False
    ).scalar() or 0

    if completed_count >= min_target:
        return {"pair": None, "status": "project_complete"}

    # Compute domain targets and exclusions
    distribution = get_domain_distribution()
    targets = compute_domain_targets(min_target, distribution)
    excluded_domains = [d for d in distribution.keys() if should_exclude_domain(d, targets)]

    # Build candidate query
    candidates = Pair.query.filter(
        Pair.dataset_id.in_(
            db.session.query(Dataset.id).filter(Dataset.is_active == True).subquery()
        ),
        Pair.annotation_count < threshold,
        Pair.is_test_sample == False,
        ~Pair.id.in_(
            db.session.query(Annotation.pair_id).filter(Annotation.user_id == user_id).subquery()
        ),
        ~Pair.id.in_(
            db.session.query(Skip.pair_id).filter(Skip.user_id == user_id).subquery()
        ),
        db.or_(
            Claim.pair_id == None,
            db.and_(
                Claim.claimed_at < datetime.utcnow() - timedelta(minutes=timeout_minutes)
            )
        )
    ).outerjoin(Claim).all()

    # Filter by excluded domains
    if excluded_domains:
        candidates = [
            p for p in candidates
            if not any(d in p.research_domains for d in excluded_domains)
        ]

    # Tier by annotation count (descending: prefer pairs with more annotations)
    tiers = {}
    for tier_count in range(threshold - 1, -1, -1):
        tiers[tier_count] = [p for p in candidates if p.annotation_count == tier_count]
        random.shuffle(tiers[tier_count])

    # Try candidates in tier order; handle race condition via IntegrityError retry
    for tier_count in range(threshold - 1, -1, -1):
        for pair in tiers[tier_count]:
            try:
                claim = Claim(pair_id=pair.id, user_id=user_id)
                db.session.add(claim)
                db.session.commit()
                return {"pair": pair, "status": "ok"}
            except IntegrityError:
                # Another request claimed this pair first; rollback and try next
                db.session.rollback()
                continue

    # No candidates available
    return {"pair": None, "status": "no_candidates"}


def release_claim(pair_id, user_id):
    """Release a claim (when annotation is saved or skipped)."""
    claim = Claim.query.filter_by(pair_id=pair_id, user_id=user_id).first()
    if claim:
        db.session.delete(claim)
        db.session.commit()
