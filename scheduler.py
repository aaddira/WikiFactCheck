"""Background scheduler for WikiFactCheck platform using APScheduler."""

import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask
from models import db, User, Annotation
from email_utils import send_weekly_digest_email

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
