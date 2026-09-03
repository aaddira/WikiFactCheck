"""Background scheduler for WikiFactCheck platform using APScheduler."""

import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask
from sqlalchemy.exc import IntegrityError
from models import db, User, Annotation, Pair, JobRun
from email_utils import send_weekly_digest_email
from backup_manager import create_backup, cleanup_old_backups
from qualification_test_manager import save_qualification_config

logger = logging.getLogger(__name__)


def _week_key():
    """ISO year+week, e.g. '2026-W36'. One slot per calendar week."""
    return datetime.utcnow().strftime("%G-W%V")


def _day_key():
    """UTC date, e.g. '2026-09-07'. One slot per day."""
    return datetime.utcnow().strftime("%Y-%m-%d")


def run_once_across_workers(app, job_name, run_key, work):
    """Run `work()` in exactly one process per (job_name, run_key) slot.

    Gunicorn runs 2 workers and each has its own APScheduler, so both fire
    every cron. Inserting the claim row is the leader election: the unique
    constraint means only one worker's INSERT commits, and the loser skips.

    This is deliberately at-most-once, not at-least-once. If the winning
    worker dies mid-run the slot stays claimed and the job is skipped until
    the next slot -- for outbound email, silence beats duplicates.
    """
    with app.app_context():
        claim = JobRun(job_name=job_name, run_key=run_key)
        db.session.add(claim)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            logger.info(f"[{job_name}] slot {run_key} already claimed by another worker - skipping")
            return False

        logger.info(f"[{job_name}] claimed slot {run_key} - running")
        try:
            detail = work()
            claim.status = "success"
            claim.detail = detail if isinstance(detail, str) else None
            logger.info(f"[{job_name}] slot {run_key} completed: {detail}")
        except Exception as e:
            claim.status = "failed"
            claim.detail = str(e)[:2000]
            logger.error(f"[{job_name}] slot {run_key} failed: {e}", exc_info=True)
        finally:
            claim.completed_at = datetime.utcnow()
            db.session.commit()
        return True


def send_weekly_digests_job(app):
    """Send weekly digest emails to all annotators (once per week, one worker)."""
    def work():
        users = User.query.filter(User.is_admin == False, User.email_confirmed == True).all()
        sent_count = 0

        for user in users:
            try:
                app_url = app.config.get("APP_URL", "http://localhost:5000")
                # Already on a background thread: send inline so failures are
                # attributable to this user and counted correctly.
                send_weekly_digest_email(user, app_url, app=app, background=False)
                sent_count += 1
            except Exception as e:
                logger.error(f"Error sending digest to {user.email}: {str(e)}")

        return f"digests sent to {sent_count}/{len(users)} annotators"

    run_once_across_workers(app, "weekly_digest", _week_key(), work)


def backup_annotations_job(app):
    """Backup all annotation data every 24 hours (once per day, one worker)."""
    def work():
        backup_file = create_backup()
        if not backup_file:
            raise RuntimeError("create_backup() returned no file")
        cleanup_old_backups(days=30)
        _prune_job_runs(days=90)
        return f"backup written to {backup_file}"

    run_once_across_workers(app, "backup_annotations", _day_key(), work)


def backup_qualification_configs_job(app):
    """Backup qualification test configs every 24 hours (once per day, one worker)."""
    def work():
        from models import Dataset
        datasets = Dataset.query.all()
        backed_up = 0

        for dataset in datasets:
            # Only datasets that actually have test samples
            test_count = db.session.query(db.func.count(Pair.id)).filter_by(
                dataset_id=dataset.id,
                is_test_sample=True
            ).scalar()

            if test_count > 0:
                save_qualification_config(dataset.id, f"{dataset.name}_auto")
                backed_up += 1

        return f"{backed_up} qualification configs backed up"

    run_once_across_workers(app, "backup_qualification_configs", _day_key(), work)


def _prune_job_runs(days=90):
    """Drop old claim rows so job_runs doesn't grow without bound."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = JobRun.query.filter(JobRun.claimed_at < cutoff).delete(synchronize_session=False)
    db.session.commit()
    if deleted:
        logger.info(f"Pruned {deleted} job_runs rows older than {days} days")


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

    # Schedule automatic qualification config backups (30 min after annotations)
    qual_backup_hour = backup_hour
    qual_backup_minute = 30

    scheduler.add_job(
        backup_qualification_configs_job,
        CronTrigger(hour=qual_backup_hour, minute=qual_backup_minute),
        args=[app],
        id='backup_qualification_configs_job',
        name='Automatic backup of qualification test configs (24h)',
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
