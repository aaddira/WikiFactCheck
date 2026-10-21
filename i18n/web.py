"""Flask integration: language resolution, template helpers, /set-language.

Resolution order for the UI language of a request:
    admin  -> always English (admin panel is not translated)
    logged-in annotator -> users.language
    anonymous -> `lang` cookie
    otherwise -> English
Then a rollout gate: endpoints that are not translated yet always render English,
so a page is never half Arabic. Shrink TRANSLATED_ENDPOINTS' counterpart
(i.e. grow the set) as pages are converted; delete the gate when all are done.
"""
import logging
from urllib.parse import urlparse

from flask import Blueprint, current_app, g, jsonify, make_response, redirect, request, session

from i18n import catalog

logger = logging.getLogger(__name__)

LANG_COOKIE = "lang"
LANG_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

# Endpoints whose templates / JSON responses are fully translated.
TRANSLATED_ENDPOINTS = frozenset({
    "index",
    "login_page",
    "register_page",
    "confirm_email_page",
    "resend_confirmation_page",
    "forgot_username_page",
    "api_resend_confirmation",
    "i18n.set_language",
})

i18n_bp = Blueprint("i18n", __name__)


def _request_user():
    """The logged-in user (cached on g by auth.get_current_user), or None."""
    from auth import get_current_user
    try:
        return get_current_user()
    except Exception:  # DB hiccup must never take the language layer (and the page) down
        logger.exception("i18n: could not load current user")
        return None


def resolve_lang():
    """Preferred language for this request, ignoring the rollout gate."""
    if request.path.startswith("/admin"):
        return catalog.DEFAULT_LANG
    user = _request_user()
    if user is not None:
        if user.is_admin:
            return catalog.DEFAULT_LANG
        return catalog.normalize_lang(getattr(user, "language", None))
    return catalog.normalize_lang(request.cookies.get(LANG_COOKIE))


def current_lang():
    """Language used to render THIS request (cached per request)."""
    if "lang" in g:
        return g.lang
    if not current_app.config.get("ARABIC_UI_ENABLED", False):
        lang = catalog.DEFAULT_LANG
    else:
        lang = resolve_lang()
        if lang != catalog.DEFAULT_LANG and request.endpoint not in TRANSLATED_ENDPOINTS:
            lang = catalog.DEFAULT_LANG
    g.lang = lang
    return lang


def t(key, **params):
    """Template/route translation for the current request's language.

    A missing key is a programming error: log it loudly and show the key itself
    (never another language's text).
    """
    lang = current_lang()
    try:
        return catalog.translate(key, lang, **params)
    except catalog.MissingTranslation:
        logger.error(f"i18n: missing translation {lang}:{key}")
        return f"[[{key}]]"


def tn(key, n, **params):
    lang = current_lang()
    try:
        return catalog.plural(key, n, lang, **params)
    except catalog.MissingTranslation:
        logger.error(f"i18n: missing plural translation {lang}:{key} (n={n})")
        return f"[[{key}]]"


def switcher_visible():
    """Show the language switcher only where it works and Arabic is enabled."""
    return (
        current_app.config.get("ARABIC_UI_ENABLED", False)
        and request.endpoint in TRANSLATED_ENDPOINTS
        and not request.path.startswith("/admin")
        and not (getattr(_request_user(), "is_admin", False))
    )


def template_context():
    lang = current_lang()
    other = next(l for l in catalog.SUPPORTED_LANGS if l != lang)
    return {
        "lang": lang,
        "text_dir": catalog.text_dir(lang),
        "is_rtl": catalog.is_rtl(lang),
        "lang_switcher_visible": switcher_visible(),
        "other_lang": other,
        "other_lang_name": catalog.LANG_NAMES[other],
        "js_i18n": catalog.js_catalog(lang),
    }


def is_safe_next(target):
    """Allow only same-site relative paths (blocks open redirects like //evil.com)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc


def apply_lang_cookie(response, lang):
    response.set_cookie(LANG_COOKIE, catalog.normalize_lang(lang),
                        max_age=LANG_COOKIE_MAX_AGE, samesite="Lax",
                        secure=request.is_secure, httponly=True)
    return response


@i18n_bp.route("/set-language/<lang>")
def set_language(lang):
    """Switch UI language. Persists to the user's profile when logged in."""
    from models import db
    if lang not in catalog.SUPPORTED_LANGS:
        return jsonify({"error": "Unsupported language"}), 400

    user = _request_user()
    if user is not None and not user.is_admin:
        user.language = lang
        db.session.commit()

    target = request.args.get("next", "/")
    response = make_response(redirect(target if is_safe_next(target) else "/"))
    return apply_lang_cookie(response, lang)


def init_i18n(app):
    """Validate catalogs (fail the boot on mismatch), register helpers."""
    problems = catalog.validate_catalogs()
    if problems:
        raise catalog.CatalogError("Translation catalogs are inconsistent:\n  " + "\n  ".join(problems))
    for warning in catalog.check_script_purity():
        app.logger.warning(f"i18n purity: {warning}")

    app.config.setdefault("ARABIC_UI_ENABLED", False)
    app.jinja_env.globals.update(t=t, tn=tn)  # globals so imported macros can call them too
    app.context_processor(template_context)
    app.register_blueprint(i18n_bp)
