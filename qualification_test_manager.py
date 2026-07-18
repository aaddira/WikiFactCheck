"""
Qualification test configuration backup and management.
Preserves test sample selections, labels, and annotator results independently from dataset changes.
"""

import json
from datetime import datetime
from pathlib import Path
from models import db, Pair, User, TestSubmission

QUAL_BACKUP_DIR = Path(__file__).parent / "backups" / "qualification_tests"
QUAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def save_qualification_config(dataset_id, test_name):
    """
    Save current qualification test configuration including:
    - Selected sample pair_ids and their correct_labels
    - Metadata about when created
    - Current annotator test results
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_file = QUAL_BACKUP_DIR / f"qualification_config_{test_name}_{timestamp}.json"

    try:
        # Get all test samples in this dataset
        test_pairs = Pair.query.filter_by(
            dataset_id=dataset_id,
            is_test_sample=True
        ).all()

        # Get all annotators who have taken tests
        annotators_with_results = db.session.query(User).filter(
            User.is_admin == False,
            User.qualification_score.isnot(None)
        ).all()

        config_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "test_name": test_name,
            "dataset_id": dataset_id,
            "backup_type": "qualification_test_config",

            # Preserve test sample configuration
            "test_samples": [
                {
                    "pair_id": p.id,
                    "pair_id_str": p.pair_id,
                    "article_title": p.article_title,
                    "correct_label": p.correct_label,
                    "is_test_sample": p.is_test_sample,
                    "passage_text": p.passage_text[:200] if p.passage_text else None,  # Excerpt for reference
                }
                for p in test_pairs
            ],

            # Preserve annotator test results (for history)
            "annotator_results": [
                {
                    "user_id": u.id,
                    "email": u.email,
                    "qualification_score": u.qualification_score,
                    "qualification_passed": u.qualification_passed,
                    "qualification_date": u.qualification_date.isoformat() if u.qualification_date else None,
                    "test_submitted": u.test_submitted,
                    "test_submission_date": u.test_submission_date.isoformat() if u.test_submission_date else None,
                    "test_approved_by_admin": u.test_approved_by_admin,
                    "test_approval_date": u.test_approval_date.isoformat() if u.test_approval_date else None,
                    "wiki_username": u.wiki_username,
                }
                for u in annotators_with_results
            ],

            # Preserve test submission answers (for audit trail)
            "test_submissions": [
                {
                    "user_id": ts.user_id,
                    "pair_id": ts.pair_id,
                    "label": ts.label,
                    "quote": ts.quote,
                    "explanation": ts.explanation,
                    "submission_batch_id": ts.submission_batch_id,
                    "submitted_at": ts.created_at.isoformat() if ts.created_at else None,
                }
                for ts in TestSubmission.query.filter(
                    TestSubmission.is_submitted == True
                ).all()
            ],

            "stats": {
                "total_test_samples": len(test_pairs),
                "annotators_tested": len(annotators_with_results),
                "annotators_passed": sum(1 for u in annotators_with_results if u.qualification_passed),
            }
        }

        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

        print(f"[OK] Qualification config backed up: {backup_file}")
        return str(backup_file)

    except Exception as e:
        print(f"[ERROR] Failed to backup qualification config: {e}")
        return None


def restore_qualification_config(backup_file):
    """
    Restore qualification test configuration from backup.
    Preserves test sample labels even if samples were temporarily cleared.
    """
    try:
        with open(backup_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        restored_count = 0
        failed_count = 0

        # Restore test sample labels
        for sample_config in config.get('test_samples', []):
            pair = Pair.query.get(sample_config['pair_id'])
            if pair:
                pair.is_test_sample = True
                pair.correct_label = sample_config['correct_label']
                restored_count += 1
            else:
                failed_count += 1
                print(f"[WARN] Could not find pair {sample_config['pair_id']}")

        db.session.commit()

        print(f"[OK] Restored {restored_count} test samples")
        if failed_count > 0:
            print(f"[WARN] Failed to restore {failed_count} samples (pairs may have been deleted)")

        return restored_count

    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] Failed to restore qualification config: {e}")
        return 0


def list_qualification_backups():
    """List all available qualification test backups."""
    backups = sorted(QUAL_BACKUP_DIR.glob("qualification_config_*.json"), reverse=True)
    return [
        {
            "filename": b.name,
            "path": str(b),
            "size_kb": b.stat().st_size / 1024,
            "modified": datetime.fromtimestamp(b.stat().st_mtime).isoformat(),
        }
        for b in backups
    ]


if __name__ == "__main__":
    # Example usage
    list_backups = list_qualification_backups()
    print(f"Available backups: {len(list_backups)}")
    for backup in list_backups[:5]:
        print(f"  - {backup['filename']}")
