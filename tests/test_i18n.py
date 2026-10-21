"""i18n regression tests. Run from the project root: python -m unittest tests.test_i18n -v

Covers: catalog consistency, every referenced key exists, no English leaking into rendered Arabic
pages (and no Arabic into English ones), RTL attributes, account language defaults, and that each
email is rendered entirely in one language.
"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolated sqlite DB + Arabic UI on, before main is imported.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ARABIC_UI_ENABLED"] = "true"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("ADMIN_EMAILS", "admin@example.com")

from i18n import catalog  # noqa: E402

ARABIC = re.compile(r"[؀-ۿ]")
# Latin words that legitimately appear inside Arabic pages (brand, proper nouns, example inputs).
LATIN_ALLOWED = {"wikifactcheck", "wikipedia", "admin", "login", "mywikiusername", "your", "email", "example", "com"}


def visible_text(html):
    attrs = " ".join(re.findall(r'(?:placeholder|title|aria-label|alt)="([^"]*)"', html))
    html = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", html)
    html = re.sub(r"(?s)<!--.*?-->", " ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    return f"{text} {attrs}"


class CatalogTests(unittest.TestCase):
    def test_catalogs_consistent(self):
        self.assertEqual(catalog.validate_catalogs(), [])

    def test_script_purity(self):
        self.assertEqual(catalog.check_script_purity(), [])

    def test_plural_arabic(self):
        got = [str(catalog.plural("unit.day", n, "ar")) for n in (0, 1, 2, 3, 10, 11, 99, 100)]
        self.assertEqual(got, ["0 يوم", "يوم واحد", "يومان", "3 أيام", "10 أيام", "11 يومًا", "99 يومًا", "100 يوم"])

    def test_no_fallback_between_languages(self):
        with self.assertRaises(catalog.MissingTranslation):
            catalog.translate("does.not.exist", "ar")

    def test_all_referenced_keys_exist(self):
        keys = set()
        files = list(ROOT.glob("templates/*.html")) + list(ROOT.glob("*.py")) + list(ROOT.glob("static/js/*.js"))
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            keys |= set(re.findall(r"""\bt[n]?\(\s*['"]([a-z_]+(?:\.[a-z_0-9]+)+)['"]""", text))
            keys |= set(re.findall(r"""\btr\(\s*['"]([a-z_]+(?:\.[a-z_0-9]+)+)['"]""", text))
            keys |= set(re.findall(r"""i18n\(\s*['"]([a-z_]+(?:\.[a-z_0-9]+)+)['"]""", text))
        en = catalog.load_catalogs()["en"]
        missing = sorted(k for k in keys if k not in en and not any(x.startswith(k + ".") for x in en))
        self.assertEqual(missing, [])


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main
        main.app.config.update(TESTING=True)
        with main.app.app_context():
            main.db.create_all()

    def client(self, lang=None):
        c = self.main.app.test_client()
        if lang:
            c.set_cookie("lang", lang)
        return c

    def test_english_default_has_no_arabic(self):
        for path in ("/", "/login", "/register", "/resend-confirmation", "/forgot-username"):
            html = self.client().get(path).get_data(as_text=True)
            self.assertIn('lang="en" dir="ltr"', html, path)
            self.assertFalse(ARABIC.search(visible_text(html).replace("العربية", "")), f"Arabic leaked into EN {path}")

    def test_arabic_pages_rtl_and_no_english_leak(self):
        for path in ("/", "/login", "/register", "/resend-confirmation", "/forgot-username"):
            html = self.client("ar").get(path).get_data(as_text=True)
            self.assertIn('lang="ar" dir="rtl"', html, path)
            words = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", visible_text(html))}
            leaked = sorted(words - LATIN_ALLOWED - {"english"})
            self.assertEqual(leaked, [], f"English words leaked into AR {path}: {leaked}")

    def test_arabic_labels_follow_terminology(self):
        html = self.client("ar").get("/").get_data(as_text=True)
        for term in ("مصدر صحيح", "مصدر غير صحيح", "تدقيق المصادر"):
            self.assertIn(term, html)

    def test_label_values_stay_english(self):
        html = self.client("ar").get("/").get_data(as_text=True)
        self.assertIn('value="Supported"', html)
        self.assertIn('value="Not Supported"', html)

    def test_switcher_and_safe_redirect(self):
        c = self.client()
        r = c.get("/set-language/ar?next=/login")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))
        self.assertIn("lang=ar", r.headers["Set-Cookie"])
        self.assertEqual(c.get("/set-language/ar?next=//evil.com").headers["Location"], "/")
        self.assertEqual(c.get("/set-language/ar?next=https://evil.com").headers["Location"], "/")
        self.assertEqual(c.get("/set-language/fr").status_code, 400)

    def test_unconverted_pages_not_in_translated_set(self):
        from i18n.web import TRANSLATED_ENDPOINTS
        self.assertNotIn("annotate_page", TRANSLATED_ENDPOINTS)

    def test_disabled_flag_serves_english_only(self):
        app = self.main.app
        app.config["ARABIC_UI_ENABLED"] = False
        try:
            html = self.client("ar").get("/login").get_data(as_text=True)
            self.assertIn('lang="en" dir="ltr"', html)
            self.assertNotIn("lang-switch", html)
        finally:
            app.config["ARABIC_UI_ENABLED"] = True

    def test_register_language_defaults(self):
        main = self.main
        sent = {}
        orig = main.send_confirmation_email
        main.send_confirmation_email = lambda user, token, url, app=None, **kw: sent.update(lang=user.email_language)
        try:
            c = self.client("ar")
            r = c.post("/register", data={"email": "ar.user@example.com", "wiki_username": "مستخدم"})
            self.assertEqual(r.status_code, 200)
            with main.app.app_context():
                u = main.User.query.filter_by(email="ar.user@example.com").first()
                self.assertEqual((u.language, u.email_language), ("ar", "ar"))
            self.assertEqual(sent["lang"], "ar")
            dup = c.post("/register", data={"email": "ar.user@example.com", "wiki_username": "x"}).get_data(as_text=True)
            self.assertIn("هذا البريد الإلكتروني مسجّل مسبقًا", dup)

            self.client("en").post("/register", data={"email": "en.user@example.com", "wiki_username": "EnUser"})
            with main.app.app_context():
                u = main.User.query.filter_by(email="en.user@example.com").first()
                self.assertEqual((u.language, u.email_language), ("en", "en"))
        finally:
            main.send_confirmation_email = orig


class EmailTests(unittest.TestCase):
    class U:
        wiki_username = "TestUser"
        email = "u@example.com"

    def _check(self, subject, html, lang):
        text = visible_text(html) + " " + subject
        words = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", text)}
        if lang == "ar":
            self.assertIn('dir="rtl"', html)
            leaked = sorted(words - {"wikifactcheck", "wikipedia", "testuser", "https", "app", "example", "com", "confirm", "abc"})  # "abc" = token in the test link
            self.assertEqual(leaked, [], f"English in Arabic email: {leaked}")
        else:
            self.assertIn('dir="ltr"', html)
            self.assertFalse(ARABIC.search(text), "Arabic in English email")

    def test_all_emails_single_language(self):
        import email_templates as et
        u, link, url = self.U(), "https://app.example.com/confirm/abc123", "https://app.example.com"
        for lang in ("en", "ar"):
            for subject, html in [
                et.render_confirmation(u, link, url, lang),
                et.render_confirmation(u, link, url, lang, reminder=True, days=7),
                et.render_username_reminder(u, url, lang),
                et.render_approval(u, url, lang),
                et.render_rejection(u, url, lang),
            ]:
                self._check(str(subject), str(html), lang)

    def test_user_data_is_escaped(self):
        import email_templates as et

        class Evil:
            wiki_username = "<script>x</script>"
            email = "e@example.com"
        _, html = et.render_confirmation(Evil(), "https://x/confirm/1", "https://x", "ar")
        self.assertNotIn("<script>x", str(html))

    def test_reminder_days_plural(self):
        import email_templates as et
        _, html = et.render_confirmation(self.U(), "https://x/c/1", "https://x", "ar", reminder=True, days=7)
        self.assertIn("7 أيام", str(html))
        _, html = et.render_confirmation(self.U(), "https://x/c/1", "https://x", "en", reminder=True, days=1)
        self.assertIn("1 day.", str(html))


if __name__ == "__main__":
    unittest.main()
