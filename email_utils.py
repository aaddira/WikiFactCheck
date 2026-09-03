"""Email utilities for sending confirmation and notification emails."""

import logging
from datetime import datetime, timedelta
from flask import current_app
from flask_mail import Message

logger = logging.getLogger(__name__)


def send_email_sync(to_email, subject, html_content, cc_email=None):
    """Send email via Flask-Mail with proper error handling."""
    try:
        if not to_email:
            logger.warning("Attempted to send email without recipient address")
            return False

        # Validate email configuration
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_username = current_app.config.get('MAIL_USERNAME', '')
        mail_password = current_app.config.get('MAIL_PASSWORD', '')

        if not mail_server or not mail_username or not mail_password:
            logger.error(f"✗ Email config incomplete - not sent to {to_email}")
            logger.debug(f"  MAIL_SERVER: {bool(mail_server)}, MAIL_USERNAME: {bool(mail_username)}, MAIL_PASSWORD: {bool(mail_password)}")
            return False

        # Get mail instance from Flask extensions
        mail = current_app.extensions.get('mail')
        if not mail:
            logger.error(f"✗ Flask-Mail not initialized - email not sent to {to_email}")
            return False

        msg = Message(
            subject=subject,
            recipients=[to_email],
            html=html_content,
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@wikifactcheck.com')
        )

        if cc_email:
            if isinstance(cc_email, str):
                msg.cc = [cc_email]
            else:
                msg.cc = cc_email

        mail.send(msg)
        logger.info(f"✓ Email delivered to {to_email}")
        return True

    except Exception as e:
        logger.error(f"✗ Email delivery failed for {to_email}: {str(e)}", exc_info=True)
        return False

def send_email_queued(scheduler, to_email, subject, html_content, cc_email=None, delay_seconds=2):
    """Queue email to be sent in background via APScheduler (non-blocking)."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        if not scheduler or not isinstance(scheduler, BackgroundScheduler):
            logger.error(f"Invalid scheduler for email queue — falling back to sync send")
            return send_email_sync(to_email, subject, html_content, cc_email)

        # Create a one-time job to send email after short delay
        job_id = f"email_{to_email}_{int(datetime.utcnow().timestamp() * 1000)}"

        def send_job():
            with current_app.app_context():
                send_email_sync(to_email, subject, html_content, cc_email)

        scheduler.add_job(
            send_job,
            'date',
            run_date=datetime.utcnow() + timedelta(seconds=delay_seconds),
            id=job_id,
            replace_existing=False,
            misfire_grace_time=300
        )
        logger.info(f"Email queued for {to_email} (job: {job_id})")
        return True

    except Exception as e:
        logger.error(f"Failed to queue email for {to_email}: {str(e)}", exc_info=True)
        return send_email_sync(to_email, subject, html_content, cc_email)



def send_confirmation_email(user, confirmation_token, app_url, scheduler=None, admin_cc='aaddira@gmail.com'):
    """Send email confirmation link to user and CC admin for registration tracking."""
    confirmation_link = f"{app_url}/confirm/{confirmation_token}"

    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif; line-height: 1.6; color: #333; }}
            a.button {{ background: #059669; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; display: inline-block; font-weight: bold; }}
            .footer {{ color: #666; font-size: 0.9em; margin-top: 2em; border-top: 1px solid #eee; padding-top: 1em; }}
        </style>
    </head>
    <body>
        <h2>Welcome to WikiFactCheck! 👋</h2>
        <p>Hello {user.wiki_username or user.email},</p>
        <p>Thank you for registering! To complete your registration and start annotating, please confirm your email address by clicking the button below:</p>

        <p style="margin: 20px 0;">
            <a href="{confirmation_link}" class="button">Confirm My Email</a>
        </p>

        <p>Or copy and paste this link if the button doesn't work:</p>
        <p><code style="background: #f5f5f5; padding: 10px; display: inline-block; border-radius: 4px;">{confirmation_link}</code></p>

        <p><strong>⏱️ Important:</strong> This link expires in 24 hours.</p>

        <p>If you didn't register for WikiFactCheck, please ignore this email or contact us if you have questions.</p>

        <div class="footer">
            <p>Best regards,<br><strong>WikiFactCheck Team</strong></p>
            <p>Questions? Visit us at {app_url}</p>
        </div>
    </body>
    </html>
    """

    if scheduler:
        success = send_email_queued(
            scheduler,
            user.email,
            "Confirm Your Email - WikiFactCheck",
            html_content,
            cc_email=admin_cc,
            app=current_app
        )
    else:
        success = send_email_sync(user.email, "Confirm Your Email - WikiFactCheck", html_content, cc_email=admin_cc)

    if success:
        logger.info(f"✓ Confirmation email sent to new user {user.email} (CC: {admin_cc})")
    else:
        logger.error(f"✗ Failed to send confirmation email to {user.email}")


def send_weekly_digest_email(user, app_url):
    """Send weekly progress digest email to user."""
    from models import Annotation, User
    from sqlalchemy import select, func

    week_start = datetime.utcnow() - timedelta(days=7)

    # Calculate this week's stats
    this_week_count = Annotation.query.filter(
        Annotation.user_id == user.id,
        Annotation.created_at >= week_start
    ).count()

    # Calculate total stats
    total_annotations = Annotation.query.filter_by(user_id=user.id).count()
    target = user.annotation_target or 300
    target_pct = (total_annotations / target * 100) if target > 0 else 0

    # Calculate leaderboard rank
    rank_result = db.session.query(func.count(User.id)).filter(
        User.is_admin == False,
        User.id != user.id,
        (select(func.count(Annotation.id)).where(
            Annotation.user_id == User.id
        ).correlate(User)).as_scalar() > total_annotations
    ).scalar()
    rank = (rank_result or 0) + 1

    # Get total active annotators
    active_count = User.query.filter(User.is_admin == False).count()

    # Calculate accuracy (agreement rate)
    # Simplified: count matching annotations with other annotators
    from models import Pair
    from sqlalchemy import and_
    matching = db.session.query(func.count(Annotation.id)).filter(
        Annotation.user_id == user.id,
        and_(
            Annotation.pair_id == Annotation.pair_id,  # join on pair
            Annotation.label == Annotation.label  # matching label
        )
    ).scalar() or 0

    total_with_overlap = Annotation.query.filter(Annotation.user_id == user.id).count()
    accuracy_pct = (matching / max(total_with_overlap, 1)) * 100

    html_content = f"""
    <h2>Your WikiFactCheck Weekly Progress Report</h2>
    <p>Hello {user.wiki_username or user.email},</p>

    <h3>📊 This Week's Activity</h3>
    <ul>
        <li>Annotations completed: <strong>{this_week_count}</strong></li>
        <li>Total annotations: <strong>{total_annotations}</strong></li>
        <li>Estimated accuracy: <strong>{accuracy_pct:.1f}%</strong></li>
    </ul>

    <h3>🎯 Progress Toward Your Target</h3>
    <ul>
        <li>Target: <strong>{target} annotations</strong></li>
        <li>Completed: <strong>{total_annotations}/{target} ({target_pct:.1f}%)</strong></li>
        <li>Remaining: <strong>{max(0, target - total_annotations)}</strong></li>
    </ul>

    <h3>🏆 Your Leaderboard Position</h3>
    <ul>
        <li>Your rank: <strong>#{rank} out of {active_count}</strong> active annotators</li>
    </ul>

    <p><a href="{app_url}/dashboard" style="background: #059669; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; display: inline-block; font-weight: bold;">View Your Dashboard</a></p>

    <p>Keep up the great work! Every annotation helps advance our research.</p>
    <p>Best regards,<br>WikiFactCheck Team</p>
    """

    send_email_async(user.email, "Your WikiFactCheck Weekly Progress Report", html_content)


def send_test_submission_notification(user, score, total, app_url, scheduler=None, cc_email='aaddira@gmail.com'):
    """Notify admins when a user submits qualification test."""
    from models import User

    # Get all admin emails
    admins = User.query.filter_by(is_admin=True).all()
    admin_emails = [admin.email for admin in admins if admin.email]

    if not admin_emails:
        logger.warning(f"No admin emails found for test submission notification (user: {user.email})")
        # Still send to cc_email even if no admins configured
        if not cc_email:
            return
        admin_emails = [cc_email]

    percentage = (score / total * 100) if total > 0 else 0
    status = "✓ PASS" if percentage >= 80 else "✗ FAIL"
    review_link = f"{app_url}/admin#submissions"
    status_color = '#059669' if percentage >= 80 else '#dc2626'

    html_content = f"""
    <h2>📝 New Qualification Test Submission</h2>
    <p>A user has submitted their qualification test for review.</p>

    <div style="background: #f3f4f6; padding: 16px; border-radius: 6px; margin: 16px 0; border-left: 4px solid {status_color};">
        <p><strong>User:</strong> {user.wiki_username or user.email}</p>
        <p><strong>Email:</strong> {user.email}</p>
        <p><strong>Score:</strong> {score}/{total} ({percentage:.1f}%)</p>
        <p><strong>Status:</strong> <span style="font-weight: bold; color: {status_color};">{status}</span></p>
        <p><strong>Submitted:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
    </div>

    <p><a href="{review_link}" style="background: #059669; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; display: inline-block; font-weight: bold;">Review in Admin Panel</a></p>

    <p style="color: #666; font-size: 14px;">
        {'⚠️ <strong>Below threshold:</strong> This submission scored below 80%. Please review carefully and contact user if needed.' if percentage < 80 else '✓ <strong>Passed:</strong> This submission passed the 80% threshold. Consider approving to grant annotation access.'}
    </p>
    """

    # Send to primary admin with CC
    if admin_emails:
        primary_email = admin_emails[0]
        cc_list = admin_emails[1:] + ([cc_email] if cc_email and cc_email not in admin_emails else [])

        if scheduler:
            success = send_email_queued(
                scheduler,
                primary_email,
                f"[TEST SUBMISSION] {status} - {user.wiki_username or user.email} ({percentage:.0f}%)",
                html_content,
                cc_email=cc_list if cc_list else None,
                app=current_app
            )
        else:
            success = send_email_sync(
                primary_email,
                f"[TEST SUBMISSION] {status} - {user.wiki_username or user.email} ({percentage:.0f}%)",
                html_content,
                cc_email=cc_list if cc_list else None
            )

        if success:
            logger.info(f"✓ Test submission notification sent to {primary_email}" +
                       (f" (CC: {', '.join(cc_list)})" if cc_list else ""))
        else:
            logger.error(f"✗ Failed to send test submission notification for user {user.email}")


# Import db for queries (avoid circular imports)
from models import db
