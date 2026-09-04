"""Email utilities for sending confirmation and notification emails.

Delivery model: emails are handed to a short-lived daemon thread so the HTTP
request returns immediately (SMTP handshakes can take 30s+ and were timing out
gunicorn workers). Threads are used rather than APScheduler because this is a
plain "run this I/O call now" job with no schedule, no persistence and no
misfire semantics -- the scheduler added failure modes without adding value.

The one rule that matters here: `current_app` is a LocalProxy bound to the
request thread. It MUST be unwrapped via `_resolve_app()` while still on that
thread. Handing the bare proxy to a background thread raises
"RuntimeError: Working outside of application context" when the thread
dereferences it.
"""

import logging
import secrets
import smtplib
import threading
import time
from datetime import datetime, timedelta
from flask import current_app
from flask_mail import Message, sanitize_address, sanitize_addresses

logger = logging.getLogger(__name__)

# Flask-Mail builds the MIME correctly but calls smtplib.SMTP(server, port)
# with NO timeout, so smtplib inherits socket's default of None and blocks
# forever if the SMTP port is filtered (common on PaaS egress). That hung the
# sender thread silently -- no delivery, no error, one leaked thread per send.
# We therefore keep Message for MIME and own the transport ourselves.
DEFAULT_SMTP_TIMEOUT = 20


def _resolve_app(app=None):
    """Return the real Flask app object, never a LocalProxy.

    Must be called on the request thread (or inside an app context). Passing a
    LocalProxy into a background thread is the bug this exists to prevent.
    """
    if app is None:
        app = current_app
    unwrap = getattr(app, "_get_current_object", None)
    return unwrap() if unwrap is not None else app


def smtp_transport(app, msg, timeout=None):
    """Send a built Message over SMTP, logging each phase.

    Mirrors flask_mail.Connection.send but with an explicit socket timeout, so
    a filtered port fails in `timeout` seconds instead of hanging forever. Each
    phase is logged separately: when this fails, the last line tells you whether
    it was DNS/connect, STARTTLS, auth, or the send itself.
    """
    server = app.config['MAIL_SERVER']
    port = int(app.config['MAIL_PORT'])
    use_tls = app.config.get('MAIL_USE_TLS', False)
    use_ssl = app.config.get('MAIL_USE_SSL', False)
    username = app.config.get('MAIL_USERNAME')
    password = app.config.get('MAIL_PASSWORD')
    timeout = timeout or app.config.get('MAIL_TIMEOUT', DEFAULT_SMTP_TIMEOUT)

    if msg.date is None:
        msg.date = time.time()
    if msg.has_bad_headers():
        raise ValueError("Message has bad headers (newline in sender or recipients)")

    started = time.monotonic()
    cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP

    logger.info(f"SMTP connecting to {server}:{port} (timeout={timeout}s, ssl={use_ssl})")
    smtp = cls(server, port, timeout=timeout)
    try:
        logger.info(f"SMTP connected in {time.monotonic() - started:.1f}s")
        if use_tls:
            smtp.starttls()
            logger.info("SMTP STARTTLS negotiated")
        if username and password:
            smtp.login(username, password)
            logger.info(f"SMTP authenticated as {username}")
        smtp.sendmail(
            sanitize_address(msg.sender),
            list(sanitize_addresses(msg.send_to)),
            msg.as_bytes(),
        )
        logger.info(f"SMTP handed off message in {time.monotonic() - started:.1f}s total")
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


def _deliver(app, to_email, subject, html_content, cc_email=None):
    """Perform the actual SMTP send. `app` must be a real Flask app object."""
    try:
        if not to_email:
            logger.warning("Attempted to send email without recipient address")
            return False

        with app.app_context():
            mail_server = app.config.get('MAIL_SERVER')
            mail_username = app.config.get('MAIL_USERNAME', '')
            mail_password = app.config.get('MAIL_PASSWORD', '')

            if not mail_server or not mail_username or not mail_password:
                logger.error(
                    f"✗ Email NOT sent to {to_email} - SMTP config incomplete "
                    f"(MAIL_SERVER={'set' if mail_server else 'MISSING'}, "
                    f"MAIL_USERNAME={'set' if mail_username else 'MISSING'}, "
                    f"MAIL_PASSWORD={'set' if mail_password else 'MISSING'})"
                )
                return False

            msg = Message(
                subject=subject,
                recipients=[to_email],
                html=html_content,
                sender=app.config.get('MAIL_DEFAULT_SENDER', 'noreply@wikifactcheck.com')
            )

            if cc_email:
                msg.cc = [cc_email] if isinstance(cc_email, str) else list(cc_email)

            smtp_transport(app, msg)
            logger.info(f"✓ Email DELIVERED to {to_email} via {mail_server} (subject: {subject!r})")
            return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(
            f"✗ Email FAILED for {to_email} - SMTP rejected the credentials ({e.smtp_code}). "
            f"Gmail requires a 16-character App Password here, not the account password.",
        )
        return False
    except (OSError, smtplib.SMTPServerDisconnected) as e:
        logger.error(
            f"✗ Email FAILED for {to_email} - could not reach "
            f"{app.config.get('MAIL_SERVER')}:{app.config.get('MAIL_PORT')} ({e}). "
            f"Outbound SMTP is likely blocked from this host.",
        )
        return False
    except Exception as e:
        logger.error(f"✗ Email delivery FAILED for {to_email}: {e}", exc_info=True)
        return False


def send_email(to_email, subject, html_content, cc_email=None, app=None, background=True):
    """Send an email.

    background=True (default): returns immediately after spawning a sender
    thread. The return value means "handed off", NOT "delivered" -- look for
    the "✓ Email DELIVERED" log line for actual delivery confirmation.

    background=False: sends inline and returns the true delivery result. Use
    from CLI commands and anywhere the caller needs to report real success.
    """
    real_app = _resolve_app(app)  # unwrap on THIS thread, before handing off

    if not background:
        return _deliver(real_app, to_email, subject, html_content, cc_email)

    threading.Thread(
        target=_deliver,
        args=(real_app, to_email, subject, html_content, cc_email),
        name=f"email-{to_email}",
        daemon=True,
    ).start()
    logger.info(f"Email queued for delivery to {to_email} (subject: {subject!r})")
    return True


def send_confirmation_email(user, confirmation_token, app_url, app=None, background=True,
                            admin_cc='aaddira@gmail.com', subject=None, heading=None,
                            intro_html=None, expiry_text="This link expires in 24 hours."):
    """Send the email-confirmation link to a user, CC'ing the admin.

    subject/heading/intro_html/expiry_text override the registration wording so
    other flows (e.g. the verification-reminder blast) reuse this one template
    instead of copying the markup.
    """
    confirmation_link = f"{app_url}/confirm/{confirmation_token}"
    subject = subject or "Confirm Your Email - WikiFactCheck"
    heading = heading or "Welcome to WikiFactCheck! 👋"
    intro_html = intro_html or (
        "<p>Thank you for registering! To complete your registration and start "
        "annotating, please confirm your email address by clicking the button below:</p>"
    )

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
        <h2>{heading}</h2>
        <p>Hello {user.wiki_username or user.email},</p>
        {intro_html}

        <p style="margin: 20px 0;">
            <a href="{confirmation_link}" class="button">Confirm My Email</a>
        </p>

        <p>Or copy and paste this link if the button doesn't work:</p>
        <p><code style="background: #f5f5f5; padding: 10px; display: inline-block; border-radius: 4px;">{confirmation_link}</code></p>

        <p><strong>⏱️ Important:</strong> {expiry_text}</p>

        <p>If you didn't register for WikiFactCheck, please ignore this email or contact us if you have questions.</p>

        <div class="footer">
            <p>Best regards,<br><strong>WikiFactCheck Team</strong></p>
            <p>Questions? Visit us at {app_url}</p>
        </div>
    </body>
    </html>
    """

    return send_email(
        user.email,
        subject,
        html_content,
        cc_email=admin_cc,
        app=app,
        background=background,
    )


REMINDER_SUBJECT = "Reminder to verify your WikiFactCheck account"
REMINDER_HEADING = "Please verify your WikiFactCheck account"
REMINDER_INTRO = (
    "<p>You registered for WikiFactCheck but your email address was never verified. "
    "A technical problem on our side stopped those verification emails from being "
    "delivered. That issue is now fixed, and we're sorry for the delay.</p>"
    "<p>To activate your account, please confirm your email address:</p>"
)


def send_verification_reminders(app, days=7, pace=1.0, progress=None):
    """Mint fresh tokens and send the one-time reminder to every unverified user.

    Existing confirmation tokens expire after 24h, so nearly every unverified
    account has a dead link -- each user gets a NEW token valid for `days`
    before their reminder goes out, otherwise the link is dead on arrival.

    Sends inline and paced so Gmail doesn't throttle the burst, and skips the
    admin CC (one CC per recipient would flood the admin inbox).
    Returns (sent, failed, considered).
    """
    from models import User

    with app.app_context():
        users = User.query.filter(User.email_confirmed == False).order_by(User.created_at).all()
        sent = failed = 0

        for user in users:
            if user.email_confirmed:      # confirmed since the list was built
                continue
            try:
                user.confirmation_token = secrets.token_urlsafe(32)
                user.confirmation_token_expires_at = datetime.utcnow() + timedelta(days=days)
                db.session.commit()

                ok = send_confirmation_email(
                    user, user.confirmation_token, app.config["APP_URL"],
                    app=app, background=False, admin_cc=None,
                    subject=REMINDER_SUBJECT, heading=REMINDER_HEADING,
                    intro_html=REMINDER_INTRO,
                    expiry_text=f"This link expires in {days} days.",
                )
                sent += 1 if ok else 0
                failed += 0 if ok else 1
            except Exception as e:
                failed += 1
                db.session.rollback()
                logger.error(f"Reminder failed for {user.email}: {e}", exc_info=True)

            if progress:
                progress(sent, failed, len(users))
            if pace:
                time.sleep(pace)

        logger.info(f"Verification reminders: sent {sent}/{len(users)}, {failed} failed")
        return sent, failed, len(users)


def send_weekly_digest_email(user, app_url, app=None, background=True):
    """Send the weekly progress digest email to one user."""
    from models import Annotation, User
    from sqlalchemy import func, select

    week_start = datetime.utcnow() - timedelta(days=7)

    this_week_count = Annotation.query.filter(
        Annotation.user_id == user.id,
        Annotation.created_at >= week_start
    ).count()

    total_annotations = Annotation.query.filter_by(user_id=user.id).count()
    target = user.annotation_target or 300
    target_pct = (total_annotations / target * 100) if target > 0 else 0

    rank_result = db.session.query(func.count(User.id)).filter(
        User.is_admin == False,
        User.id != user.id,
        (select(func.count(Annotation.id)).where(
            Annotation.user_id == User.id
        ).correlate(User)).as_scalar() > total_annotations
    ).scalar()
    rank = (rank_result or 0) + 1

    active_count = User.query.filter(User.is_admin == False).count()

    from models import Pair
    from sqlalchemy import and_
    matching = db.session.query(func.count(Annotation.id)).filter(
        Annotation.user_id == user.id,
        and_(
            Annotation.pair_id == Annotation.pair_id,
            Annotation.label == Annotation.label
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

    return send_email(
        user.email,
        "Your WikiFactCheck Weekly Progress Report",
        html_content,
        app=app,
        background=background,
    )


def send_test_submission_notification(user, score, total, app_url, app=None, background=True,
                                      cc_email='aaddira@gmail.com'):
    """Notify admins that a user submitted their qualification test."""
    from models import User

    admins = User.query.filter_by(is_admin=True).all()
    admin_emails = [admin.email for admin in admins if admin.email]

    if not admin_emails:
        logger.warning(f"No admin emails found for test submission notification (user: {user.email})")
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

    primary_email = admin_emails[0]
    cc_list = admin_emails[1:] + ([cc_email] if cc_email and cc_email not in admin_emails else [])

    return send_email(
        primary_email,
        f"[TEST SUBMISSION] {status} - {user.wiki_username or user.email} ({percentage:.0f}%)",
        html_content,
        cc_email=cc_list if cc_list else None,
        app=app,
        background=background,
    )


# Import db for queries (avoid circular imports)
from models import db
