"""Translation catalogs: pure Python, no Flask, no request state.

Every lookup takes an EXPLICIT language. There is deliberately no fallback to
another language: an English string leaking into the Arabic UI (or vice versa)
is a bug we want to fail loudly, not paper over. `validate_catalogs()` runs at
app startup and refuses to boot when the catalogs disagree.

Keys are flat, dotted ("login.submit"). Plural families use a category suffix
("unit.day.one", "unit.day.few") and are resolved with `plural()`.
"""
import json
import logging
import re
from pathlib import Path

from markupsafe import Markup

logger = logging.getLogger(__name__)

SUPPORTED_LANGS = ("en", "ar")
DEFAULT_LANG = "en"
RTL_LANGS = frozenset({"ar"})
# Shown in the language switcher in their OWN script, never translated.
LANG_NAMES = {"en": "English", "ar": "العربية"}

# CLDR plural categories each language must define for every plural family.
PLURAL_CATEGORIES = {
    "en": ("one", "other"),
    "ar": ("zero", "one", "two", "few", "many", "other"),
}
_ALL_CATEGORIES = frozenset(c for cats in PLURAL_CATEGORIES.values() for c in cats)

_TRANSLATIONS_DIR = Path(__file__).parent / "translations"
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_ARABIC_LETTER_RE = re.compile(r"[؀-ۿ]")

_catalogs = {}


class MissingTranslation(KeyError):
    """Raised when a key is absent for the requested language."""


class CatalogError(RuntimeError):
    """Raised at startup when the language catalogs are inconsistent."""


def normalize_lang(lang):
    """Return a supported language code; unknown/empty input -> DEFAULT_LANG."""
    lang = (lang or "").strip().lower()
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def is_rtl(lang):
    return normalize_lang(lang) in RTL_LANGS


def text_dir(lang):
    return "rtl" if is_rtl(lang) else "ltr"


def load_catalogs(force=False):
    """Load all JSON catalogs once (idempotent)."""
    if _catalogs and not force:
        return _catalogs
    _catalogs.clear()
    for lang in SUPPORTED_LANGS:
        path = _TRANSLATIONS_DIR / f"{lang}.json"
        with open(path, encoding="utf-8") as f:
            _catalogs[lang] = json.load(f)
    return _catalogs


def _entry(key, lang):
    lang = normalize_lang(lang)
    try:
        return load_catalogs()[lang][key]
    except KeyError:
        raise MissingTranslation(f"{lang}:{key}") from None


def translate(key, lang, **params):
    """Translate `key` into `lang`.

    Returns Markup: catalog strings are trusted (they may contain <strong>, links),
    while every `params` value is HTML-escaped by Markup.format. Raises
    MissingTranslation if the key is absent -- callers decide how loud to be.
    """
    template = _entry(key, lang)
    if not params:
        return Markup(template)
    return Markup(template).format(**params)


def plural_category(lang, n):
    """CLDR plural category for integer n."""
    lang = normalize_lang(lang)
    n = abs(int(n))
    if lang == "ar":
        if n == 0:
            return "zero"
        if n == 1:
            return "one"
        if n == 2:
            return "two"
        if 3 <= n % 100 <= 10:
            return "few"
        if 11 <= n % 100 <= 99:
            return "many"
        return "other"
    return "one" if n == 1 else "other"


def plural(key, n, lang, **params):
    """Translate a plural family: plural('unit.day', 3, 'ar') -> 'key.few'. {n} is auto-supplied."""
    category = plural_category(lang, n)
    return translate(f"{key}.{category}", lang, n=n, **params)


def js_catalog(lang):
    """Raw (unescaped) strings under the `js.` namespace for client-side use."""
    lang = normalize_lang(lang)
    return {k: v for k, v in load_catalogs()[lang].items() if k.startswith("js.")}


def _split_plural(key):
    """('unit.day.few') -> ('unit.day', 'few'); non-plural keys -> (key, None)."""
    base, _, tail = key.rpartition(".")
    return (base, tail) if base and tail in _ALL_CATEGORIES else (key, None)


def validate_catalogs():
    """Fail fast if catalogs disagree. Returns a list of problems (empty == OK)."""
    catalogs = load_catalogs(force=True)
    problems = []

    # Plural families are validated per language; everything else must match exactly.
    def plain_keys(cat):
        return {k for k in cat if _split_plural(k)[1] is None}

    def families(cat):
        fam = {}
        for k in cat:
            base, category = _split_plural(k)
            if category:
                fam.setdefault(base, set()).add(category)
        return fam

    reference = catalogs[DEFAULT_LANG]
    for lang, cat in catalogs.items():
        if plain_keys(cat) != plain_keys(reference):
            only_here = sorted(plain_keys(cat) - plain_keys(reference))
            missing = sorted(plain_keys(reference) - plain_keys(cat))
            if only_here:
                problems.append(f"[{lang}] keys not in {DEFAULT_LANG}: {only_here}")
            if missing:
                problems.append(f"[{lang}] keys missing vs {DEFAULT_LANG}: {missing}")

        fams = families(cat)
        if set(fams) != set(families(reference)):
            problems.append(f"[{lang}] plural families differ from {DEFAULT_LANG}: "
                            f"{sorted(set(fams) ^ set(families(reference)))}")
        for base, cats in fams.items():
            required = set(PLURAL_CATEGORIES[lang])
            if cats != required:
                problems.append(f"[{lang}] plural '{base}' has {sorted(cats)}, needs {sorted(required)}")

        for key, value in cat.items():
            if not isinstance(value, str) or not value.strip():
                problems.append(f"[{lang}] {key}: empty or non-string value")

    # Placeholders must be identical across languages (compare plain keys + same category).
    for key, en_value in reference.items():
        en_ph = set(_PLACEHOLDER_RE.findall(en_value))
        for lang, cat in catalogs.items():
            if lang == DEFAULT_LANG:
                continue
            base, category = _split_plural(key)
            if category:  # plural categories differ per language; compare to 'other'
                continue
            value = cat.get(key)
            if value is not None and set(_PLACEHOLDER_RE.findall(value)) != en_ph:
                problems.append(f"[{lang}] {key}: placeholders {sorted(set(_PLACEHOLDER_RE.findall(value)))} "
                                f"!= {sorted(en_ph)}")
    return problems


def check_script_purity():
    """Heuristic anti-mixing check; returns warnings (not startup-fatal).

    - ar values with no Arabic letters at all (untranslated English left in ar.json)
    - en values containing Arabic letters (an Arabic string pasted into en.json)
    Strings listed in NEUTRAL_KEYS (brand names, pure URLs/symbols) are exempt.
    """
    cats = load_catalogs()
    warnings = []
    for key, value in cats["ar"].items():
        if key in NEUTRAL_KEYS:
            continue
        if not _ARABIC_LETTER_RE.search(value):
            warnings.append(f"[ar] {key}: no Arabic letters -> {value!r}")
    for key, value in cats["en"].items():
        if _ARABIC_LETTER_RE.search(value):
            warnings.append(f"[en] {key}: contains Arabic -> {value!r}")
    return warnings


# Keys whose value is intentionally identical / script-neutral in every language.
NEUTRAL_KEYS = frozenset({
    "common.brand",
    "common.email_placeholder",
    "register.username_placeholder_neutral",
})
