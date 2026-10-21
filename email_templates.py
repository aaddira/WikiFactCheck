"""User-facing email content, one language per message, no request context.

Every function takes an explicit `lang` (use `email_lang(user)`) and returns
`(subject, html)` entirely in that language. Nothing here reads flask.request,
cookies or the UI language, so a background thread or scheduler job can never
produce a mixed-language message. Strings live in i18n/translations/*.json.

Transport (SMTP / SendGrid) stays in email_utils.py / routes_admin.py.
"""
from markupsafe import Markup

from i18n import catalog

_FONT_STACK = {
    "en": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif",
    "ar": "Tahoma, 'Segoe UI', 'Noto Naskh Arabic', 'Noto Sans Arabic', Arial, sans-serif",
}


def email_lang(user):
    """The language this user chose for emails (falls back to default)."""
    return catalog.normalize_lang(getattr(user, "email_language", None))


def _name(user):
    """Display name, bidi-isolated so an English name inside Arabic text can't scramble punctuation."""
    return Markup("<bdi>{}</bdi>").format(user.wiki_username or user.email)


def _ltr(value):
    """Wrap URLs/code so they stay left-to-right inside an RTL message."""
    return Markup('<span dir="ltr" style="unicode-bidi:embed;">{}</span>').format(value)


def _layout(lang, body):
    direction = catalog.text_dir(lang)
    align = "right" if direction == "rtl" else "left"
    return Markup(
        """<!DOCTYPE html>
<html lang="{lang}" dir="{dir}">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: {font}; line-height: 1.7; color: #333; direction: {dir}; text-align: {align}; }}
  a.button {{ background: #059669; color: white !important; padding: 12px 24px; border-radius: 6px; text-decoration: none; display: inline-block; font-weight: bold; }}
  .footer {{ color: #666; font-size: 0.9em; margin-top: 2em; border-top: 1px solid #eee; padding-top: 1em; }}
</style>
</head>
<body dir="{dir}">
{body}
</body>
</html>"""
    ).format(lang=lang, dir=direction, align=align, font=Markup(_FONT_STACK[lang]), body=body)


def _footer(lang, app_url):
    tr = lambda key, **p: catalog.translate(key, lang, **p)
    return Markup('<div class="footer"><p>{}</p><p>{}</p></div>').format(
        tr("email.footer_regards"), tr("email.footer_visit", url=_ltr(app_url)))


def render_confirmation(user, confirmation_link, app_url, lang, *, reminder=False, days=None):
    """Registration confirmation, or the one-time verification reminder (`reminder=True`).

    `days` is the token lifetime for reminders; registration links last 24 hours.
    """
    tr = lambda key, **p: catalog.translate(key, lang, **p)
    prefix = "email.reminder" if reminder else "email.confirm"

    if reminder:
        intro = Markup("<p>{}</p><p>{}</p>").format(tr("email.reminder.intro1"), tr("email.reminder.intro2"))
        expiry = tr("email.confirm.expiry_days", duration=catalog.plural("unit.day", days or 7, lang))
    else:
        intro = Markup("<p>{}</p>").format(tr("email.confirm.intro"))
        expiry = tr("email.confirm.expiry_24h")

    body = Markup(
        """<h2>{heading}</h2>
<p>{hello}</p>
{intro}
<p style="margin: 20px 0;"><a href="{link}" class="button">{button}</a></p>
<p>{copy}</p>
<p><code style="background:#f5f5f5; padding:10px; display:inline-block; border-radius:4px;">{link_text}</code></p>
<p>{important}</p>
<p>{ignore}</p>
{footer}"""
    ).format(
        heading=tr(f"{prefix}.heading"),
        hello=tr("email.hello", name=_name(user)),
        intro=intro,
        link=confirmation_link,
        button=tr("email.confirm.button"),
        copy=tr("email.confirm.copy_link"),
        link_text=_ltr(confirmation_link),
        important=tr("email.confirm.important", expiry=expiry),
        ignore=tr("email.confirm.ignore"),
        footer=_footer(lang, app_url),
    )
    return tr(f"{prefix}.subject"), _layout(lang, body)


def render_username_reminder(user, app_url, lang):
    tr = lambda key, **p: catalog.translate(key, lang, **p)
    username = user.wiki_username or tr("email.username.not_set")
    body = Markup(
        """<h2>{heading}</h2>
<p>{hello}</p>
<p>{intro}</p>
<p><strong style="font-size:1.2em; font-family:monospace; background:#f5f5f5; padding:10px; border-radius:4px; display:inline-block;"><bdi>{username}</bdi></strong></p>
<p>{login}</p>
<p>{ignore}</p>
{footer}"""
    ).format(
        heading=tr("email.username.heading"),
        hello=tr("email.hello", name=_name(user)),
        intro=tr("email.username.intro"),
        username=username,
        login=tr("email.username.login_html", login_url=f"{app_url}/login"),
        ignore=tr("email.username.ignore"),
        footer=_footer(lang, app_url),
    )
    return tr("email.username.subject"), _layout(lang, body)


def render_approval(user, app_url, lang):
    tr = lambda key, **p: catalog.translate(key, lang, **p)
    body = Markup(
        """<h2>{heading}</h2>
<p>{hi}</p>
<p>{p1}</p>
<p>{p2}</p>
<p>{p3}</p>
<p><a href="{url}/">{cta}</a></p>
<p>{thanks}</p>"""
    ).format(
        heading=tr("email.approval.heading"),
        hi=tr("email.hi", name=_name(user)),
        p1=tr("email.approval.p1"), p2=tr("email.approval.p2"), p3=tr("email.approval.p3"),
        url=app_url, cta=tr("email.approval.cta"),
        thanks=tr("email.approval.thanks"),
    )
    return tr("email.approval.subject"), _layout(lang, body)


def render_rejection(user, app_url, lang, reason=None):
    """`reason` is admin-written free text, inserted verbatim (escaped) in whatever language the
    admin wrote it. Pass None to use the standard reason in the user's language."""
    tr = lambda key, **p: catalog.translate(key, lang, **p)
    reason_text = (reason or "").strip() or tr("email.rejection.default_reason")
    body = Markup(
        """<h2>{heading}</h2>
<p>{hi}</p>
<p>{p1}</p>
<p>{status}</p>
<p>{p2}</p>
<p>{p3}</p>"""
    ).format(
        heading=tr("email.rejection.heading"),
        hi=tr("email.hi", name=_name(user)),
        p1=tr("email.rejection.p1"),
        status=tr("email.rejection.status", reason=reason_text),
        p2=tr("email.rejection.p2_html", login_url=f"{app_url}/"),
        p3=tr("email.rejection.p3"),
    )
    return tr("email.rejection.subject"), _layout(lang, body)
