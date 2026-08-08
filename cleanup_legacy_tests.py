#!/usr/bin/env python3
"""
Clean up legacy is_test_sample=True pairs from the database.
Use this after migrating to the new TestSampleSet versioning system.
"""

import sys
from main import app, db
from models import Pair

def cleanup_legacy_tests():
    """Remove legacy test sample flags."""
    with app.app_context():
        # Count legacy test samples
        legacy_count = Pair.query.filter_by(is_test_sample=True).count()

        if legacy_count == 0:
            print("✓ No legacy test samples found. Database is clean.")
            return

        print(f"Found {legacy_count} legacy test sample(s) marked with is_test_sample=True")
        print("These will be cleared to use only the new versioned test sample sets.")

        # Prompt for confirmation
        response = input("\nProceed with cleanup? (yes/no): ").strip().lower()
        if response != "yes":
            print("Cleanup cancelled.")
            return

        # Clear the legacy flag
        try:
            Pair.query.filter_by(is_test_sample=True).update({"is_test_sample": False})
            db.session.commit()
            print(f"✓ Successfully cleared {legacy_count} legacy test sample flag(s)")

            # Verify
            remaining = Pair.query.filter_by(is_test_sample=True).count()
            if remaining == 0:
                print("✓ Verification passed: No legacy test samples remain in database")
            else:
                print(f"⚠ Warning: {remaining} legacy test sample(s) still remain")
        except Exception as e:
            db.session.rollback()
            print(f"✗ Error during cleanup: {str(e)}")
            return False

    return True

if __name__ == "__main__":
    success = cleanup_legacy_tests()
    sys.exit(0 if success else 1)
