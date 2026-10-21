"""Bilingual (English/Arabic) support. See catalog.py (pure) and web.py (Flask)."""
from i18n.catalog import (  # noqa: F401
    DEFAULT_LANG, SUPPORTED_LANGS, LANG_NAMES, normalize_lang, translate, plural,
    text_dir, is_rtl, MissingTranslation,
)
