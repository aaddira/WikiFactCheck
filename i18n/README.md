# Bilingual UI (English / Arabic)

English is the source language. Arabic is an additional option, never a replacement.

## Rules that keep the languages from mixing
- **No fallback between languages.** A missing key is an error, not a silent English string.
- `i18n/translations/en.json` and `ar.json` must have identical keys and placeholders. `init_i18n()` checks
  this at startup and **refuses to boot** otherwise (a bad deploy fails its health check; the old one keeps serving).
- Emails are rendered with an **explicit** language (`email_templates.py`, driven by `user.email_language`),
  never from the request, so background threads cannot produce a mixed message.
- Stored values (label names like `Supported`, DB fields) stay English. Only display text is translated.
- English Wikipedia content (passages, citations, URLs) stays LTR inside an RTL page (`.wiki-content`, `.passage-text-box`, ...).

## Adding or changing text
1. Add the key to **both** JSON files (flat dotted keys, e.g. `login.submit`). Plural families use
   `.zero/.one/.two/.few/.many/.other` for `ar` and `.one/.other` for `en` (see `unit.day`).
2. Templates: `{{ t('login.submit') }}`, with params `{{ t('x', email=email) }}` (params are HTML-escaped; catalog text is trusted).
3. JavaScript: put the key under `js.` and call `i18n('js.key', {n: 3})`.
4. Run `python -m unittest tests.test_i18n -v`.

## Converting a page
Use logical CSS (`ms-/me-/ps-/pe-/text-start/border-s-*` in Tailwind; `margin-inline-*` in CSS), never `left/right`.
Then add its endpoint name to `TRANSLATED_ENDPOINTS` in `i18n/web.py`. Until an endpoint is listed, it always renders English
so no page is ever half Arabic.

## Rollout
`ARABIC_UI_ENABLED=true` (env) turns the switcher on and serves Arabic. Default is off.

## Language settings
- `users.language`: interface language (changed by the switcher or Preferences).
- `users.email_language`: language of every email sent to the user (Preferences). Accounts created through the
  Arabic UI default both to `ar`.
- Admins are always English.
