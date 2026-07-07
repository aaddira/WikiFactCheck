"""Email utilities for sending confirmation and notification emails."""

import os
import logging
import threading
from datetime import datetime, timedelta
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

logger = logging.getLogger(__name__)


def send_email_async(to_email, subject, html_content, cc_email=None):
    """Send email via SendGrid in background thread."""
    def _send():
        try:
            api_key = os.getenv('SENDGRID_API_KEY')
            from_email = os.getenv('SENDGRID_FROM_EMAIL', 'noreply@wikifactcheck.com')

            if not api_key:
                logger.warning("SENDGRID_API_KEY not set, email not sent")
                return

            sg = SendGridAPIClient(api_key)

            mail = Mail(
                from_email=from_email,
                to_emails=to_email,
                subject=subject,
                html_content=html_content
            )

            if cc_email:
                mail.add_cc(cc_email)

            response = sg.client.mail.send.post(request_body=mail.get())
            logger.info(f"Email sent to {to_email} (status: {response.status_code})")
        except Exception as e:
            logger.error(f"Error sending email to {to_email}: {str(e)}")

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def send_confirmation_email(user, confirmation_token, app_url):
    """Send email confirmation link to user."""
    confirmation_link = f"{app_url}/confirm/{confirmation_token}"

    html_content = f"""
    <h2>Confirm Your Email</h2>
    <p>Hello {user.wiki_username or user.email},</p>
    <p>Welcome to WikiFactCheck! To complete your registration, please confirm your email address by clicking the link below:</p>
    <p><a href="{confirmation_link}" style="background: #059669; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; display: inline-block; font-weight: bold;">Confirm Email</a></p>
    <p>Or copy and paste this link: <code>{confirmation_link}</code></p>
    <p>This link expires in 24 hours.</p>
    <p>If you didn't register for WikiFactCheck, please ignore this email.</p>
    <p>Best regards,<br>WikiFactCheck Team</p>
    """

    send_email_async(user.email, "Confirm Your Email - WikiFactCheck", html_content)


def send_weekly_digest_email(user, app_url):
    """Send weekly progress digest email to user."""
    from models import Annotation, User
    from sqlalchemy import func

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
        (func.select(func.count(Annotation.id)).where(
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


# Import db for queries (avoid circular imports)
from models import db
