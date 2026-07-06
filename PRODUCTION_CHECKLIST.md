# WikiFactCheck Production Readiness Checklist

**Status**: Ready for UAT (User Acceptance Testing) before wider rollout  
**Last Updated**: 2026-07-05  
**Deployment Method**: Railway (auto-deploy on main branch push)

---

## Overview

This checklist covers all 9 core production features and validates the complete implementation against the production readiness plan. Each section includes step-by-step verification procedures.

**Platform**: Python 3.13 + Flask 3.0 + PostgreSQL on Railway  
**Workers**: Gunicorn with 2 workers (handles concurrent requests safely)  
**Database**: Flask-Migrate with Alembic for schema safety

---

## A. Core Infrastructure (Blockers)

### A1: Database Migrations & Schema Safety ✅
- [x] Flask-Migrate initialized (`migrations/` exists with `alembic.ini`, `env.py`, `script.py.mako`)
- [x] Baseline migration exists (`migrations/versions/001_baseline_postgres.py`)
- [x] Claim constraint fixed: unique on `pair_id` only (race condition safe)
- [x] AuditLog table created with proper indices
- [x] Dockerfile updated: `CMD ["sh", "-c", "flask db upgrade && gunicorn ..."]`

**Verify**:
```bash
# Check migrations directory exists
ls -la migrations/

# On Railway via SSH: migrations should run automatically on deploy
# No manual DB setup needed
```

**Expected**: Deployment completes without SQL errors. If DB init fails, check Railway logs for traceback.

---

### A2: Logging & Error Handling ✅
- [x] Logging configured in `main.py` (outputs to stdout for Railway capture)
- [x] `app.config["DEBUG"]` env-driven (default false)
- [x] Error handler logs exceptions via `app.logger.exception()`
- [x] Routes catch and log errors before returning JSON
- [x] Annotation endpoint includes comprehensive try-except logging

**Verify**:
```bash
# Locally: trigger a 500 error and check stdout
# On Railway: check Logs tab for exception tracebacks

# Example: POST invalid JSON to any route
curl -X POST http://localhost:5000/api/settings/email \
  -H "Content-Type: application/json" \
  -d "{ INVALID JSON"

# Should see error in logs, generic "Internal server error" JSON response
```

**Expected**: All errors logged. With `FLASK_DEBUG=false`, client sees generic message; with `FLASK_DEBUG=true`, full traceback visible.

---

## B. User Management & Auth (Critical)

### B1: Login & Session Management ✅
- [x] Annotator login: email + wiki_username required
- [x] Admin login: secret token (`ADMIN_SECRET_TOKEN` env var)
- [x] Session cookie secure flag env-driven (`SESSION_COOKIE_SECURE`)
- [x] Context processor: `current_user` available in all templates
- [x] Logout clears session properly

**Verify**:
```bash
# 1. Annotator login flow
Navigate to http://localhost:5000/login (or Railway URL)
  Enter: email=test@example.com, wiki_username=testuser
  Click Sign In
  → Should redirect to /dashboard
  → Nav bar should show email, Dashboard, Annotate, Qualification Test, Preferences, Logout

# 2. Admin login flow
Navigate to /admin/login
  Enter: ADMIN_SECRET_TOKEN from .env
  Click "Access Admin Panel"
  → Should redirect to /admin
  → Admin dashboard tabs visible

# 3. Session check
Open browser dev tools → Application → Cookies
  → SESSION cookie should exist
  → Refresh page: should still be logged in
  → On logout: cookie deleted

# 4. Set SESSION_COOKIE_SECURE on Railway
  On Railway dashboard: Settings → Variables
  Add: SESSION_COOKIE_SECURE=true
  Redeploy
```

**Expected**: Smooth login/logout. Admin can only access via token. Regular annotators blocked from /admin.

---

### B2: Settings Page ✅
- [x] Route: `GET /settings` redirects to template
- [x] API: `GET /api/settings/profile` returns user profile
- [x] API: `PUT /api/settings/profile` updates wiki_username
- [x] API: `POST /api/settings/email` changes email (with validation)
- [x] Template: `templates/settings.html` with dark mode support
- [x] Email change validation: uniqueness check, 409 on conflict
- [x] Email change auto-updates `is_admin` flag if admin EMAILS list changes

**Verify**:
```bash
# 1. Load settings page
Login as annotator
  Click "Preferences" in nav (or go to /settings)
  → Page should load with Account Info card showing:
     - Current email
     - Current wiki_username (or "Not set")
     - Account created date
     - Last login time

# 2. Edit wiki username
Click in "Edit Wikipedia Username" card
  Enter: "MyWikipediaUser"
  Click "Save Wikipedia Username"
  → Green success message
  → Refresh page: username persists

# 3. Change email (valid flow)
Click in "Change Email" card
  Enter new email: newemail@example.com (unused)
  Confirm: newemail@example.com
  "Change Email" button should enable
  Click "Change Email"
  → Confirmation dialog appears
  → Approve
  → Green success message
  → Nav bar email updates (no re-login needed)
  → Refresh: still logged in, email persisted

# 4. Change email (conflict flow)
Try to change email to one already in use (or admin email)
  → "Email already in use" error appears

# 5. Browser console test (dark mode in Settings)
  Open dev tools → toggle theme button
  → All text should remain readable
  → Form inputs should have visible borders and text
  → No white-on-white or black-on-black text
```

**Expected**: All form interactions work smoothly. Email change doesn't require re-login. Admin flag updates if email moves in/out of ADMIN_EMAILS.

---

## C. Annotation Assignment & Claims (Race Condition Fix)

### C1: Pair Assignment (Race-Condition Safe) ✅
- [x] `Claim` constraint: unique on `pair_id` only
- [x] `get_next_pair()` uses try-except IntegrityError loop
- [x] Two simultaneous requests can't claim same pair
- [x] Fallback: if claim fails, next candidate is tried

**Verify**:
```bash
# 1. Basic assignment
Login as annotator
  Go to /annotate
  → Pair should load (pair ID visible at top)
  → Form should be enabled (not disabled)

# 2. Claim test (local only, requires two terminals)
Terminal 1: curl with slow HTTP client
Terminal 2: curl same /api/pair/next endpoint simultaneously
  → One succeeds with {status: "ok", pair: {...}}
  → Other succeeds with {status: "ok", pair: {...}} (different pair)
  → Both get valid pairs, no race condition error

# 3. Long-running annotation
Click "Save & Next" on a pair
  → Claim released, next pair loaded
  → No "pair already claimed" errors

# Check Rails logs (if available):
  - No "UNIQUE constraint failed" errors
  - No database deadlocks
```

**Expected**: Smooth pair assignment. Two annotators working simultaneously get different pairs automatically.

---

## D. Quality Metrics & Analytics

### D1: Agreement Rate Calculation ✅
- [x] Endpoint: `GET /api/results/agreement` (with optional `citation_type` / `dataset_id`)
- [x] Counts pairs with 2+ annotations only
- [x] Includes ties in denominator, only non-ties in agreement count
- [x] Returns: overall %, by_dataset, by_citation_type

**Verify**:
```bash
# 1. Create test data
Login as 2 different annotators
  - Annotator 1: pair A → TRUE, pair B → FALSE
  - Annotator 2: pair A → TRUE, pair B → TRUE
  Result: pair A agrees (2/2), pair B disagrees (1/2)
  Expected: 50% agreement

# 2. Test endpoint
curl -s "http://localhost:5000/api/results/agreement" \
  -H "Authorization: Bearer <token>" | jq

# Expected response:
{
  "overall_agreement_pct": 50.0,
  "pairs_evaluated": 2,
  "by_dataset": {
    "1": {
      "agreement_pct": 50.0,
      "pairs": 2
    }
  },
  "by_citation_type": {
    "JOURNAL": {
      "agreement_pct": 50.0,
      "pairs": 2
    }
  }
}

# 3. Test with tie case
Add annotator 3 to pair A:
  - Annotator 3: pair A → MIXED
  Result: pair A has 3-way tie (TRUE, TRUE, MIXED)
  - Pair A should be excluded from agreement denominator
  Expected: 0% agreement (only pair B evaluated: 1 agreement, 1 total)

curl -s "http://localhost:5000/api/results/agreement" | jq '.overall_agreement_pct'
# Should show lower % than before
```

**Expected**: Correct calculation of agreement rates. Ties properly excluded.

---

### D2: Annotation Distribution Chart ✅
- [x] Endpoint: `GET /api/annotation-distribution` returns {count: sample_count}
- [x] Admin dashboard tab: "Annotations" shows distribution chart
- [x] Chart type: bar chart (not pie)
- [x] Shows samples with 1, 2, 3+ annotations

**Verify**:
```bash
# 1. Admin dashboard
Login as admin → go to /admin
  Click "Dashboard" tab
  → Should see 2 cards at top:
    1. "Label Distribution" - bar chart showing TRUE/FALSE/MIXED/etc label counts
    2. "Annotation Distribution" - bar chart showing "1 anno", "2 annos", "3 annos"

# 2. Test chart responds to theme toggle
In admin dashboard
  Click theme toggle (☀️ / 🌙 icon)
  → Charts should update colors instantly (no page reload)
  → No console errors

# 3. Endpoint test
curl -s "http://localhost:5000/api/results/annotation-distribution" | jq

# Expected:
{
  "0": 5,    # 5 samples with 0 annotations
  "1": 10,   # 10 samples with 1 annotation
  "2": 8,    # 8 samples with 2 annotations
  "3": 2,    # 2 samples with 3+ annotations
  "max_annotations": 3
}
```

**Expected**: Chart renders correctly. Responds to theme changes. Bar chart, not pie.

---

### D3: Per-Annotator Quality Metrics ✅
- [x] Endpoint: `GET /api/results/by-annotator` returns qual score + live agreement rate
- [x] Qual score from test (qualification_score)
- [x] Live agreement rate (% of annotations matching pair majority)

**Verify**:
```bash
# 1. Test endpoint
curl -s "http://localhost:5000/api/results/by-annotator" | jq '.[] | {email, qualification_score, agreement_rate_pct}'

# Expected response (example):
[
  {
    "email": "alice@example.com",
    "qualification_score": 8,
    "annotation_count": 25,
    "agreement_rate_pct": 78.5
  },
  {
    "email": "bob@example.com",
    "qualification_score": 7,
    "annotation_count": 30,
    "agreement_rate_pct": 65.0
  }
]

# 2. Quality flag calculation (client-side in dashboard)
For each annotator:
  - qual_score >= 8 AND agreement >= 75% → "Excellent" (green)
  - qual_score >= 6 AND agreement >= 60% → "Good" (blue)
  - Else → "Needs Review" (yellow)
```

**Expected**: Scores and agreement rates match the test data. Quality flag logic is intuitive.

---

## E. Audit Logging (Production Safety)

### E1: Audit Log Creation & Persistence ✅
- [x] `AuditLog` model created (models.py)
- [x] AuditLog records all admin actions:
  - Dataset upload/update/delete
  - Config changes
  - Test submission approve/reject
  - Admin login
- [x] Snapshot pattern: data captured before deletion
- [x] JSON-safe details field (auto-serializes dicts)

**Verify**:
```bash
# 1. Trigger audit entries
Login as admin → /admin

# Upload a dataset
  Click "Datasets" tab
  Click "Upload Dataset"
  Select JSONL file
  Click "Upload"
  → "Audit Log" tab should show new entry:
    Action: "dataset_upload"
    Target: "Dataset" (ID shown)
    Details: {name, citation_type, loaded, skipped}

# Update config
  Click "Config" tab
  Set: ANNOTATORS_PER_SAMPLE = 4
  → Audit Log shows:
    Action: "config_set"
    Details: {old_value: 3, new_value: 4}

# Test rejection (captures answer snapshot)
  Click "Tests" tab → "Pending" → Reject a submission
  → Audit Log shows:
    Action: "test_submission_reject"
    Details: {email, reason, answers: [...]}
  → Confirms answers are captured even after TestSubmission rows deleted

# 2. Verify persistence (critical: data survives after deletion)
Check that rejection entry still shows answers:
  curl -s "http://localhost:5000/admin/audit-log?action=test_submission_reject" \
    -H "Authorization: Bearer <admin_token>" | jq '.logs[0].details.answers'
  → Should show array of answer objects with pair_id, user_answer, correct_answer
  → Proves snapshot was saved before rows were deleted

# 3. Pagination
In audit log, generate 50+ entries
  Click through pages: Prev/Next buttons work
  Filter by action/actor/date range: filters apply correctly
```

**Expected**: All admin actions logged. Rejections capture answer snapshot. Log survives data deletion. Pagination works.

---

### E2: Audit Log Viewing (Admin Dashboard) ✅
- [x] Endpoint: `GET /admin/audit-log` (paginated, filterable)
- [x] UI: "Audit Log" tab in admin dashboard
- [x] Columns: Timestamp, Action, Actor, Target, Details
- [x] Filters: action, actor_email (substring), target_type, date range
- [x] Pagination: 50 per page (cap 200), Prev/Next buttons

**Verify**:
```bash
# 1. Load audit log page
Login as admin
  Click "Audit Log" tab
  → Page should load (no eternal loading spinner)
  → Table should show entries
  → Each row: timestamp, action, actor email, target type, details

# 2. Test pagination
If 100+ entries exist
  → "Prev" disabled on page 1
  → Click "Next" → page 2 loads
  → "Prev" now enabled
  → Can go back/forward

# 3. Test filters
Actor email filter: type "alice@" → only alice's entries shown
Action filter: select "dataset_upload" → only uploads shown
Target type: "Dataset" → only dataset actions shown
Date range: set from yesterday to today → only today's entries shown

# 4. Details JSON parsing
Click into a "dataset_delete" entry
  → Details should display as readable JSON (not raw string)
  → Should show: name, citation_type, sample_count
```

**Expected**: Audit log loads instantly. All filters work. Details parse correctly.

---

## F. Dark Mode (Complete Site Coverage)

### F1: Theme Toggle & Persistence ✅
- [x] Theme button in nav (☀️ / 🌙 icon), visible on all pages
- [x] Click toggles light ↔ dark
- [x] Preference persists in localStorage
- [x] Respects `prefers-color-scheme` system setting on first visit
- [x] No flash-of-wrong-theme on reload (anti-FOUC script in `<head>`)

**Verify**:
```bash
# 1. Toggle theme
Visit http://localhost:5000 (not logged in)
  See landing page in light mode
  Click theme button (🌙 icon)
  → Page instantly switches to dark mode
  → Icon changes to ☀️
  → Refresh page: still in dark mode
  → Open in new incognito window: respects system preference

# 2. Verify anti-FOUC
Close dev tools
Hard reload (Ctrl+Shift+R)
  → Page should NOT flash white then turn dark
  → Should load in dark mode immediately (no blink)

# 3. Per-page verification
Visit these pages in dark mode:
  - / (landing) → all text readable
  - /login → form inputs have visible borders/text
  - /admin/login → same
  - /admin → all tabs and tables readable
  - /settings → forms and display text visible
  - /dashboard → no white text on white background
  - /annotate → passage/citation text readable

# 4. Theme change event listener (charts)
In admin dashboard
  Switch theme button
  → Label Distribution chart colors update instantly
  → Annotation Distribution chart colors update instantly
  → No console errors about undefined chart objects
```

**Expected**: Smooth theme toggle. Persistence works. All pages readable in both modes. Charts update live without refresh.

---

### F2: Template Coverage ✅
All templates have `dark:` variants for backgrounds, text, borders:
- [x] base.html - nav, body, links
- [x] login.html - form, card, button
- [x] admin_login.html - form, card, button
- [x] landing.html - banner, demo card
- [x] settings.html - all cards and forms
- [x] admin.html - tabs, tables, modals
- [x] dashboard.html - cards, tables
- [x] annotate.html - panels, forms

**Verify**:
```bash
# Spot-check key elements (use browser dev tools → Elements)
Login → Settings page in dark mode
  <input> element: should have dark:bg-gray-700 dark:border-gray-600 dark:text-white
  <label> element: should have dark:text-gray-300
  No bare text-gray-900 without dark:text-white counterpart

Admin page in dark mode
  Table headers: should be dark:bg-gray-700
  Tab inactive: dark:text-gray-400
  Tab active: dark:text-emerald-400
  Modal backdrop: should dim in dark mode

Annotate page in dark mode
  Passage panel: dark:bg-gray-800
  Citation panel: dark:bg-gray-800
  Form inputs: dark:bg-gray-700
  No unreadable contrast anywhere
```

**Expected**: All critical elements have dark mode variants. No unreadable text in either mode.

---

## G. Email Configuration (Approval/Rejection Workflow)

### G1: SMTP Setup & Sending ✅
- [x] Flask-Mail configured
- [x] Routes: send_approval_email(), send_rejection_email()
- [x] Both include CC admin feature (MAIL_CC_ADMIN env var)
- [x] Errors logged, don't block approval/rejection

**Verify on Railway**:
```bash
# 1. Set environment variables (Railway dashboard)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=<your-gmail-email> (not app password yet)
MAIL_PASSWORD=<gmail-app-password>
MAIL_CC_ADMIN=your-email@gmail.com  # Optional: get copies
MAIL_DEFAULT_SENDER=noreply@wikifactcheck.com

# Generate Gmail app password:
  1. Google Account → Security (myaccount.google.com/security)
  2. App passwords (requires 2FA enabled)
  3. Select Mail, Windows
  4. Copy 16-char password
  5. Paste as MAIL_PASSWORD

# 2. Test in admin panel
Approve a user's test submission
  → Email should arrive in user's inbox (+ CC admin if set)
  Subject: "WikiFactCheck: You're Approved to Start Annotating"
  Body: Congratulations + login link

Reject a submission
  → Email should arrive with reason
  Subject: "WikiFactCheck: Test Result"

# 3. Check Railway logs for errors
If email fails:
  "Error sending approval email to alice@example.com"
  But approval still succeeds (user can log in)

# 4. Test CC admin
If MAIL_CC_ADMIN set:
  Approve email goes to user AND admin
  Rejection email goes to user AND admin
```

**Expected**: Emails send to users. CC admin optional but works if set. Approval/rejection succeed even if email fails.

---

## H. Admin Features (Complete Workflow)

### H1: Dataset Management ✅
- [x] Upload JSONL (with cite type, error reporting)
- [x] List all datasets
- [x] Update (name, active status)
- [x] Delete (with snapshot in audit log)
- [x] Export annotations as JSONL/CSV

**Verify**:
```bash
# 1. Upload dataset
Admin panel → Datasets tab → Upload
  File: test.jsonl (valid format)
  Name: "Test Dataset"
  Citation Type: JOURNAL
  Click "Upload"
  → Should show: loaded: X, skipped duplicates: Y
  → Dataset appears in list

# 2. Update dataset
Click dataset in list → Name edit → Save
  → Audit log: dataset_update entry created

# 3. Delete dataset
Click dataset → Delete icon
  → Audit log: dataset_delete entry created with snapshot
  → Verify snapshot includes: name, citation_type, sample_count
  → Dataset gone from list

# 4. Export
Bottom of datasets tab: Export Annotations (JSONL/CSV)
  → File downloads with all annotations
  → JSONL: one record per line
  → CSV: headers + rows
```

**Expected**: Dataset CRUD works smoothly. All actions audit-logged. Exports include all fields.

---

### H2: Test Qualification Workflow ✅
- [x] Mark pairs as test samples with correct labels
- [x] View pending test submissions
- [x] Approve → user can start annotating, email sent
- [x] Reject → reason stored, user can retake, email sent

**Verify**:
```bash
# 1. Mark test samples
Admin panel → Tests tab → Mark Samples
  Select dataset
  Pick 5 pairs
  Assign correct labels (TRUE/FALSE/MIXED/etc)
  Click "Mark as Test Samples"
  → Pairs flagged as is_test_sample=True

# 2. User takes test
Logout, login as new user
  → Redirected to test
  → Shows 5 marked pairs
  → User answers all
  → Click "Submit Test"

# 3. Admin approves
Admin panel → Tests tab → Pending
  → User's submission shown with score
  Click "Approve"
  → User can now annotate
  → Approval email sent

# OR: Admin rejects
Click "Reject"
  Enter reason: "Too many errors on facts about medicine"
  → User sees rejection email with reason
  → Audit log captures answers + reason
  → User can retake test anytime

# 4. Retake after rejection
User logs back in
  → Redirect to test (not annotate)
  → Can answer test again
```

**Expected**: Test flow smooth. Approvals/rejections work. Emails informative.

---

### H3: Configuration Management ✅
- [x] View/edit config values:
  - ANNOTATORS_PER_SAMPLE (default 3)
  - MIN_SAMPLES_FOR_TARGET (default 300)
  - DOMAIN_DISTRIBUTION (JSON)
  - ANNOTATOR_CAP_ENABLED

**Verify**:
```bash
# 1. View current config
Admin panel → Config tab
  → Lists all settings
  → Current values shown

# 2. Change a setting
Set ANNOTATORS_PER_SAMPLE = 4
  → Audit log: config_set {old_value: 3, new_value: 4}
  → Future assignments require 4 annos instead of 3

# 3. Domain distribution
Expand DOMAIN_DISTRIBUTION
  → Shows JSON: {medicine: 50, history: 30, ...}
  → Change: {medicine: 40, history: 40, history: 20}
  → Audit log: config_set with old/new values
```

**Expected**: Config changes persist. Audit logged. Affect downstream assignment logic immediately.

---

## I. Annotation Workflow (Full Stack)

### I1: Qualified Annotator Flow ✅
- [x] Login → Dashboard (personal stats)
- [x] Click "Annotate" → pair loads (claim created)
- [x] Fill form (label, quote, explanation)
- [x] Save → claim released, next pair loads
- [x] Skip → claim released, next pair loads
- [x] History shows all completed annotations

**Verify**:
```bash
# 1. Login + dashboard
Login as qualified user (test_approved_by_admin=True)
  → Redirected to /dashboard
  → Shows stats: annotations_count, annotation_target, etc

# 2. Annotate pair
Click "Annotate"
  → Pair loads (pair_id shown, passage + citation visible)
  → Form is ENABLED (not disabled)
  → Select label: TRUE
  → Paste quote from citation
  → Type explanation
  → Click "Save & Next"
  → Pair saves to Annotation table
  → Claim released
  → Next pair loads

# 3. Skip
On another pair → Click "Skip"
  → Skip record created
  → Claim released
  → Next pair loads (skip won't be offered again)

# 4. History
Click "History" in nav
  → Lists all completed annotations
  → Can filter/search
  → Shows pair_id, label, quote, explanation, date

# 5. Check database
psql: SELECT COUNT(*) FROM annotations WHERE user_id=X;
  → Should match count displayed in dashboard
```

**Expected**: Smooth annotation workflow. No claim conflicts. Skip/save both work. History accurate.

---

### I2: Unqualified Annotator (Preview Mode) ✅
- [x] If not test_approved_by_admin, redirect to test first
- [x] Admin can view annotate in read-only mode (/admin/preview)

**Verify**:
```bash
# 1. Unqualified user
Login as new user (not yet approved)
  Click "Annotate"
  → Redirected to /test/post-login
  → Form is DISABLED
  → Cannot fill or submit

# 2. Admin preview
Admin → Admin Panel
  Click "Admin Preview" (top right)
  → Annotate page loads in read-only mode
  → Form is DISABLED
  → No pair claim created
  → Can see interface without needing test
```

**Expected**: Unqualified users can't annotate. Admin can preview interface.

---

## J. System Resilience (Error Handling)

### J1: Graceful Degradation ✅
- [x] Email failures don't block test approval/rejection
- [x] Invalid JSON in audit log details doesn't crash endpoint
- [x] Missing pair relationships handled (NULL checks)
- [x] Expired claims auto-released after 30 min

**Verify**:
```bash
# 1. Email failure (intentional)
Set MAIL_USERNAME to invalid email
  Admin → Approve a user
  → Page succeeds (200)
  → Email fails silently
  → Check Railway logs: "Error sending approval email..."
  → User still approved (can log in + annotate)

# 2. Invalid details JSON (historical)
(This shouldn't happen with current code, but verify recovery)
  curl -s "http://localhost:5000/admin/audit-log" | jq '.logs[].details'
  → Should either be valid JSON or readable string
  → No TypeError crashes

# 3. Missing relationships
Delete a pair, check annotations endpoint
  → Should handle gracefully
  → Return pair_title=null or skip that annotation

# 4. Expired claims
Create a claim
  Wait 31 minutes
  Request next pair for that user
  → Old claim auto-released
  → New pair assignment succeeds
```

**Expected**: No silent failures. Errors logged. User experience degraded gracefully.

---

## K. Deployment & Operations (Railway)

### K1: Environment Variables ✅
All required vars documented in `.env.example`:
- [x] `FLASK_DEBUG` (default: false)
- [x] `SECRET_KEY` (set on Railway)
- [x] `DATABASE_URL` (PostgreSQL on Railway)
- [x] `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`
- [x] `MAIL_CC_ADMIN` (optional)
- [x] `SESSION_COOKIE_SECURE` (true on Railway, false local)
- [x] `ADMIN_SECRET_TOKEN` (set on Railway)
- [x] `APP_URL` (set to Railway domain)

**Verify on Railway**:
```bash
# 1. Check Railway variables
Railway dashboard → Project → Settings → Variables
  Confirm all required vars set (except MAIL_CC_ADMIN which is optional)

# 2. Missing var test
Temporarily remove a var (e.g., ADMIN_SECRET_TOKEN)
  Try admin login
  → Should fail with error or use default

# 3. Redeploy
Push to main branch
  → Railway auto-deploys
  → Check Logs tab for: "Migrate" step and "gunicorn" startup
  → No SQL or import errors
```

**Expected**: Deployment completes without errors. All features work post-deploy.

---

### K2: Database Backup & Recovery ✅
- [x] PostgreSQL on Railway (auto-backup included)
- [x] Migrations enable forward/backward compat
- [x] No data is lost on redeploy (persistent volume)

**Verify**:
```bash
# 1. Data persistence after redeploy
Annotate a few samples
  → Stored in database
Push a code change
  → Railway redeploys
  Check annotations still present
  → psql: SELECT COUNT(*) FROM annotations;

# 2. Migration safety
Create a new migration (schema change)
  → Old data preserved
  → New schema applied
  → Queries still work

# 3. Backup (manual verification)
Railway → Backups tab
  → Recent backups listed
  → Can restore if needed
```

**Expected**: Data survives redeploy. Migrations are safe. Backups available.

---

## Sign-Off

**Testing Completed By**: _______________________________  
**Date**: _______________________________  
**Notes/Issues Found**:
```
(List any issues discovered during testing, even minor ones)



```

**Ready for Production**: ☐ YES  ☐ NO  

**If NO, blockers**:
```
(Describe blocking issues)



```

---

## Quick Reference

### Critical User Journeys

**Annotator Onboarding** (5 min):
1. Visit landing page
2. Click "Log In to Start"
3. Enter email + wiki_username
4. Complete qualification test (manual setup by admin required)
5. Admin approves test
6. Receive approval email
7. Log in → Annotate pairs
8. View personal dashboard stats

**Admin Setup** (15 min):
1. Log in via /admin/login with secret token
2. Upload dataset (JSONL file)
3. Mark 5+ pairs as test samples
4. View audit log of uploads
5. Approve/reject test submissions
6. View quality metrics

**Dark Mode** (1 min):
1. Visit any page (logged out or logged in)
2. Click theme button (☀️ / 🌙 icon)
3. Page switches instantly
4. Preference persists across pages/reload

### Common Issues & Recovery

| Issue | Cause | Fix |
|-------|-------|-----|
| Eternal loading on audit log | Response.ok not checked | ✅ Fixed |
| Dark mode text unreadable (e.g., "Settings") | Missing dark: classes | ✅ Fixed |
| Charts blank (Label Distribution) | Data format mismatch | ✅ Fixed |
| Annotations tab eternally loading | Complex SQLAlchemy joins | ✅ Fixed (simplified) |
| Two users get same pair | Claim race condition | ✅ Fixed (unique constraint) |
| No audit record of rejections | No snapshot before delete | ✅ Fixed (AuditLog.record) |

---

## Rollout Plan

1. **UAT** (User Acceptance Testing) — this checklist
2. **Staging** — Production-like env for extended testing
3. **Soft Launch** — 2-3 trusted annotators on production
4. **Full Launch** — Open to all annotators
5. **Monitoring** — Weekly check of logs, quality metrics, email delivery

**Estimated Timeline**: 1-2 weeks from UAT start to full launch (pending test feedback)

---

**Document Version**: 1.0  
**Last Reviewed**: 2026-07-05  
**Maintained By**: Abbad (AI Assistant)
