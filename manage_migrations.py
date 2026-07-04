#!/usr/bin/env python
"""
Diagnostic and management script for Flask-Migrate setup.
Run with: python manage_migrations.py [command]

Commands:
  validate    - Check if Flask-Migrate is properly configured
  test        - Test Flask-Migrate functionality
  status      - Show current migration status
"""

import sys
import os
from pathlib import Path

def validate():
    """Validate Flask-Migrate setup."""
    print("=" * 60)
    print("Validating Flask-Migrate Setup")
    print("=" * 60)

    errors = []
    warnings = []

    # Check 1: Flask-Migrate package
    print("\n1. Checking Flask-Migrate installation...")
    try:
        import flask_migrate
        print(f"   ✓ Flask-Migrate {flask_migrate.__version__} installed")
    except ImportError:
        errors.append("Flask-Migrate not installed")
        print("   ✗ Flask-Migrate not installed")

    # Check 2: Migrations directory structure
    print("\n2. Checking migrations directory structure...")
    migrations_path = Path(__file__).parent / "migrations"

    required_files = [
        ("migrations/__init__.py", "Package marker"),
        ("migrations/env.py", "Alembic environment"),
        ("migrations/script.py.mako", "Migration template"),
        ("migrations/alembic.ini", "Alembic config"),
        ("migrations/versions/__init__.py", "Versions package marker"),
    ]

    for file_path, description in required_files:
        full_path = Path(__file__).parent / file_path
        if full_path.exists():
            print(f"   ✓ {file_path} ({description})")
        else:
            errors.append(f"Missing {file_path}")
            print(f"   ✗ {file_path} (MISSING)")

    # Check 3: Flask app imports
    print("\n3. Checking Flask app imports...")
    try:
        from main import app, db, migrate
        print("   ✓ main.py imports successfully")
        print(f"   ✓ Flask app created: {app.name}")
        print(f"   ✓ SQLAlchemy db initialized")
        print(f"   ✓ Flask-Migrate initialized")
    except ImportError as e:
        errors.append(f"Cannot import from main.py: {e}")
        print(f"   ✗ Import error: {e}")
    except Exception as e:
        errors.append(f"Unexpected error in main.py: {e}")
        print(f"   ✗ Error: {e}")

    # Check 4: Flask CLI commands
    print("\n4. Checking Flask CLI commands...")
    try:
        from main import app
        with app.app_context():
            commands = app.cli.list_commands(None)
            if 'db' in commands:
                print("   ✓ 'flask db' command available")
            else:
                warnings.append("'flask db' command not found in CLI")
                print(f"   ⚠ 'flask db' not in available commands")
                print(f"     Available commands: {', '.join(sorted(commands))}")
    except Exception as e:
        errors.append(f"Cannot check CLI commands: {e}")
        print(f"   ✗ Error checking CLI: {e}")

    # Summary
    print("\n" + "=" * 60)
    if errors:
        print(f"ERRORS FOUND ({len(errors)}):")
        for error in errors:
            print(f"  • {error}")

    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for warning in warnings:
            print(f"  • {warning}")

    if not errors:
        print("✓ All checks passed!")

    print("=" * 60)
    return len(errors) == 0


def test():
    """Test Flask-Migrate functionality."""
    print("\n" + "=" * 60)
    print("Testing Flask-Migrate Functionality")
    print("=" * 60)

    try:
        from main import app, db

        with app.app_context():
            print("\n1. Testing database connection...")
            with db.engine.connect() as conn:
                result = conn.execute("SELECT 1")
                print("   ✓ Database connection successful")

            print("\n2. Checking existing tables...")
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            if tables:
                print(f"   ✓ Found {len(tables)} tables: {', '.join(tables)}")
            else:
                print("   ⚠ No tables found (may need migration)")

            print("\n3. Testing Flask-Migrate import...")
            from flask_migrate import upgrade
            print("   ✓ Flask-Migrate upgrade function available")

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n" + "=" * 60)
    print("✓ All tests passed!")
    print("=" * 60)
    return True


def status():
    """Show migration status."""
    print("\n" + "=" * 60)
    print("Migration Status")
    print("=" * 60)

    try:
        from main import app

        with app.app_context():
            print("\n1. Migration directory structure:")
            migrations_path = Path(__file__).parent / "migrations"
            versions_path = migrations_path / "versions"

            print(f"   Location: {migrations_path}")

            if versions_path.exists():
                migrations = list(versions_path.glob("*.py"))
                migrations = [f for f in migrations if f.name != "__init__.py"]
                if migrations:
                    print(f"   Existing migrations ({len(migrations)}):")
                    for mig in sorted(migrations):
                        print(f"     • {mig.name}")
                else:
                    print("   No migrations found")

            print("\n2. Database tables:")
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            if tables:
                for table in sorted(tables):
                    cols = inspector.get_columns(table)
                    print(f"   • {table} ({len(cols)} columns)")
            else:
                print("   No tables")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    print("=" * 60)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "validate"

    if command == "validate":
        success = validate()
        sys.exit(0 if success else 1)
    elif command == "test":
        success = test()
        sys.exit(0 if success else 1)
    elif command == "status":
        status()
    else:
        print(__doc__)
        sys.exit(1)
