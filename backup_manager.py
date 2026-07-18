"""
Automatic backup system for annotation data.
Exports all annotations, test submissions, and related data every 24 hours.
Protects against accidental deletion of datasets with annotations.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from models import db, Annotation, Pair, User, TestSubmission, Dataset

BACKUP_DIR = Path(__file__).parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

def create_backup():
    """
    Create a complete backup of all annotation data.
    Returns: path to backup file
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"annotations_backup_{timestamp}.json"

    try:
        backup_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "backup_type": "full_annotations",

            # Datasets
            "datasets": [
                {
                    "id": d.id,
                    "name": d.name,
                    "description": d.description,
                    "citation_type": d.citation_type,
                    "sample_count": d.sample_count,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in Dataset.query.all()
            ],

            # Annotations (most critical)
            "annotations": [
                {
                    "id": a.id,
                    "pair_id": a.pair_id,
                    "user_id": a.user_id,
                    "label": a.label,
                    "quote": a.quote,
                    "explanation": a.explanation,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "updated_at": a.updated_at.isoformat() if a.updated_at else None,
                }
                for a in Annotation.query.all()
            ],

            # Test submissions (qualification data)
            "test_submissions": [
                {
                    "id": ts.id,
                    "user_id": ts.user_id,
                    "pair_id": ts.pair_id,
                    "label": ts.label,
                    "quote": ts.quote,
                    "explanation": ts.explanation,
                    "is_submitted": ts.is_submitted,
                    "submission_batch_id": ts.submission_batch_id,
                    "created_at": ts.created_at.isoformat() if ts.created_at else None,
                }
                for ts in TestSubmission.query.all()
            ],

            # User qualification data
            "users_qualification": [
                {
                    "id": u.id,
                    "email": u.email,
                    "qualification_score": u.qualification_score,
                    "qualification_passed": u.qualification_passed,
                    "qualification_date": u.qualification_date.isoformat() if u.qualification_date else None,
                    "test_submitted": u.test_submitted,
                    "test_submission_date": u.test_submission_date.isoformat() if u.test_submission_date else None,
                    "test_approved_by_admin": u.test_approved_by_admin,
                    "test_approval_date": u.test_approval_date.isoformat() if u.test_approval_date else None,
                    "annotations_count": u.annotations_count,
                }
                for u in User.query.filter(User.is_admin == False).all()
            ],

            # Pairs with annotations (for context)
            "pairs_with_annotations": [
                {
                    "id": p.id,
                    "pair_id": p.pair_id,
                    "dataset_id": p.dataset_id,
                    "article_title": p.article_title,
                    "research_domains": p.research_domains,
                    "annotation_count": p.annotation_count,
                    "is_test_sample": p.is_test_sample,
                    "correct_label": p.correct_label,
                }
                for p in Pair.query.filter(Pair.annotation_count > 0).all()
            ],

            "stats": {
                "total_annotations": Annotation.query.count(),
                "total_test_submissions": TestSubmission.query.count(),
                "total_pairs_annotated": Pair.query.filter(Pair.annotation_count > 0).count(),
                "annotators": User.query.filter(User.is_admin == False).count(),
                "datasets": Dataset.query.count(),
            }
        }

        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)

        print(f"[OK] Backup created: {backup_file}")
        print(f"     Annotations: {backup_data['stats']['total_annotations']}")
        print(f"     Test submissions: {backup_data['stats']['total_test_submissions']}")
        print(f"     Pairs annotated: {backup_data['stats']['total_pairs_annotated']}")

        return str(backup_file)

    except Exception as e:
        print(f"[ERROR] Backup failed: {e}")
        return None


def restore_annotations_from_backup(backup_file):
    """
    Restore annotations from a backup file.
    WARNING: This will ADD to existing data, not replace it.
    For full restore, manually delete relevant records first.
    """
    try:
        with open(backup_file, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        restored_count = 0

        # Restore annotations
        for ann_data in backup_data.get('annotations', []):
            # Check if already exists
            existing = Annotation.query.filter_by(
                pair_id=ann_data['pair_id'],
                user_id=ann_data['user_id']
            ).first()

            if not existing:
                annotation = Annotation(
                    pair_id=ann_data['pair_id'],
                    user_id=ann_data['user_id'],
                    label=ann_data['label'],
                    quote=ann_data.get('quote'),
                    explanation=ann_data.get('explanation'),
                )
                db.session.add(annotation)
                restored_count += 1

        db.session.commit()

        print(f"[OK] Restored {restored_count} annotations from backup")
        return restored_count

    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] Restore failed: {e}")
        return 0


def cleanup_old_backups(days=7):
    """Delete backups older than N days (default 7)."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = 0

    for backup_file in BACKUP_DIR.glob("annotations_backup_*.json"):
        try:
            file_mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
            if file_mtime < cutoff:
                backup_file.unlink()
                deleted += 1
                print(f"[OK] Deleted old backup: {backup_file.name}")
        except Exception as e:
            print(f"[WARN] Could not delete {backup_file.name}: {e}")

    print(f"[OK] Cleanup complete: {deleted} old backups removed")
    return deleted


if __name__ == "__main__":
    create_backup()
    cleanup_old_backups(days=30)
