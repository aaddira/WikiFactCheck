"""Background scheduler for WikiFactCheck platform using APScheduler."""

import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask
from models import db, User, Annotation
from email_utils import send_weekly_digest_email
from backup_manager import create_backup, cleanup_old_backups

logger = logging.getLogger(__name__)


def send_weekly_digests_job(app):
    """Send weekly digest emails to all annotators."""
    with app.app_context():
        try:
            users = User.query.filter(User.is_admin == False, User.email_confirmed == True).all()
            sent_count = 0

            for user in users:
                try:
                    app_url = app.config.get("APP_URL", "http://localhost:5000")
                    send_weekly_digest_email(user, app_url)
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Error sending digest to {user.email}: {str(e)}")

            logger.info(f"Weekly digests sent to {sent_count}/{len(users)} annotators")
        except Exception as e:
            logger.error(f"Error in send_weekly_digests_job: {str(e)}")


def backup_annotations_job(app):
    """Backup all annotation data every 24 hours."""
    with app.app_context():
        try:
            backup_file = create_backup()
            if backup_file:
                logger.info(f"Annotation backup completed: {backup_file}")
                # Cleanup backups older than 30 days
                cleanup_old_backups(days=30)
            else:
                logger.error("Annotation backup failed")
        except Exception as e:
            logger.error(f"Error in backup_annotations_job: {str(e)}")


def init_scheduler(app):
    """Initialize background scheduler with Flask app."""
    scheduler_enabled = app.config.get("SCHEDULER_ENABLED", True)

    if not scheduler_enabled:
        logger.info("Background scheduler disabled via config")
        return None

    scheduler = BackgroundScheduler()

    # Schedule weekly digest: Monday at 9 AM UTC (0 = Monday)
    digest_day = int(app.config.get("DIGEST_SCHEDULE_DAY", 0))
    digest_hour = int(app.config.get("DIGEST_SCHEDULE_HOUR", 9))

    scheduler.add_job(
        send_weekly_digests_job,
        CronTrigger(day_of_week=digest_day, hour=digest_hour, minute=0),
        args=[app],
        id='weekly_digest_job',
        name='Send weekly progress digests to annotators',
        replace_existing=True,
        coalesce=True,  # Coalesca multiple missed runs into one
        max_instances=1  # Ensure only one instance runs
    )

    # Schedule automatic backups every 24 hours at 2 AM UTC
    backup_hour = int(app.config.get("BACKUP_SCHEDULE_HOUR", 2))

    scheduler.add_job(
        backup_annotations_job,
        CronTrigger(hour=backup_hour, minute=0),
        args=[app],
        id='backup_annotations_job',
        name='Automatic backup of all annotations (24h)',
        replace_existing=True,
        coalesce=True,
        max_instances=1
    )

    def start_scheduler():
        """Start scheduler on first request if not already started."""
        if not scheduler.running:
            try:
                scheduler.start()
                app.logger.info("Background scheduler started successfully")
            except Exception as e:
                app.logger.error(f"Error starting scheduler: {str(e)}")

    # Use before_first_request hook to start scheduler
    @app.before_request
    def _before_first_request():
        start_scheduler()

    return scheduler


def stop_scheduler(scheduler):
    """Stop the background scheduler gracefully."""
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Background scheduler stopped")
