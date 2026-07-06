# WikiFactCheck Production Testing Checklist

**Deploy Date**: 2026-07-05  
**Git Commit**: b9b1937 (Production readiness: Complete dark mode + security hardening)  
**Railway URL**: https://wikifactcheck.up.railway.app  

---

## Overview

All production infrastructure is complete and deployed. This checklist verifies that each feature works correctly in the live environment. **Estimated testing time: 30-45 minutes**.

---

## Part A: Database & Infrastructure ✓

### A1: Flask-Migrate & Database Initialization
- [ ] **Database tables exist**: SSH into Railway and run:
  ```bash
  psql $DATABASE_URL -c "SELECT COUNT(*) FROM audit_logs; SELECT COUNT(*) FROM users;"
  ```
  - Expected: Two rows with counts (e.g., `count: 23` for audit_logs, `count: 4` for users)
  - **Why**: Migrations must run on deployment before gunicorn starts

- [ ] **Audit log schema validated**: SSH into Railway and run:
  ```bash
  psql $DATABASE_URL -c "\d audit_logs"
  ```
  - Expected: Shows all columns: `id, action, actor_user_id, actor_email, target_type, target_id, details, created_at`
  - Expected indexes: Primary key on `id`, indexes on `action`, `actor_user_id`, `created_at`, and composite `(action, created_at)`
  - **Why**: AuditLog model must be fully functional for production logging

- [ ] **Sample audit entries**: SSH into Railway and run:
  ```bash
  psql $DATABASE_URL -c "SELECT action, actor_email, target_type, created_at FROM audit_logs ORDER BY created_at DESC LIMIT 5;"
  ```
  - Expected: Shows recent actions like `admin_login`, `dataset_upload`, `config_set`, etc.
  - **Why**: Confirms logging is actively recording actions

### A2: Admin Login & Session Security
- [ ] **Admin login still works**: Visit `/admin/login`, enter your secret token, verify redirect to `/admin`
  - Expected: Redirect to `/admin` with admin panel visible
  - **Why**: Token-based admin auth is security-critical

- [ ] **SESSION_COOKIE_SECURE is enforced**: 
  - On Railway: `SESSION_COOKIE_SECURE=true` (cookies sent only over HTTPS)
  - Verify via browser devtools: Check cookies marked "Secure" ✓
  - **Why**: Production must enforce HTTPS-only cookies

- [ ] **Regular login still rejects admin emails**: 
  - Attempt to log in via `/login` with an admin email address
  - Expected: Error message "Admin accounts must log in via /admin/login with a secret token"
  - **Why**: Prevents admin accounts from using user login path

---

## Part B: Audit Logging (A2b) 🔍

### B1: Audit Log Endpoint
- [ ] **Endpoint works**: Visit `/admin#audit-log` tab in admin panel
  - Expected: Tab loads, displays table with columns: Timestamp, Action, Actor, Target, Details
  - **Why**: Core audit visibility feature

- [ ] **Pagination works**: 
  - Load audit log with 50+ entries
  - Click "Next" button
  - Expected: Page 2 loads with different entries, "Prev" enabled, "Next" conditional
  - **Why**: Prevents excessive data loading

- [ ] **Filtering by action**: 
  - Filter by action = "dataset_upload"
  - Expected: Only upload entries shown
  - **Why**: Admins need to find specific action types

- [ ] **Filtering by actor email**: 
  - Filter by actor email substring
  - Expected: Only that user's actions shown
  - **Why**: Admins need accountability per-user

- [ ] **Filtering by date range**: 
  - Set date_from and date_to
  - Expected: Only entries within range shown
  - **Why**: Compliance requires date-range auditing

### B2: Actions Logged
- [ ] **Dataset upload logged**: 
  - Admin: Upload a JSONL dataset
  - Check audit log for action="dataset_upload"
  - Expected: Entry shows dataset name, citation_type, loaded count, skipped count
  - **Why**: Critical for data provenance

- [ ] **Dataset update logged**: 
  - Admin: Edit dataset name or active status
  - Check audit log for action="dataset_update"
  - Expected: Entry shows what was changed
  - **Why**: Tracks modifications

- [ ] **Dataset delete logged (with snapshot)**: 
  - Admin: Delete a test dataset
  - Check audit log for action="dataset_delete"
  - Expected: Entry includes dataset name/type/sample_count in details (preserved after delete)
  - **Why**: Recovery trail for accidental deletes

- [ ] **Config change logged (with old/new values)**: 
  - Admin: Change ANNOTATORS_PER_SAMPLE config
  - Check audit log for action="config_set"
  - Expected: Entry shows old_value and new_value
  - **Why**: Change tracking for operational configs

- [ ] **Test submission approved logged**: 
  - Admin: Approve a pending test submission
  - Check audit log for action="test_submission_approve"
  - Expected: Entry shows user email and qualification score
  - **Why**: Approvals must be auditable

- [ ] **Test submission rejected logged (with snapshot)**: 
  - Admin: Reject a pending test submission with reason "Poor passage comprehension"
  - Check audit log for action="test_submission_reject"
  - Expected: Entry includes reason AND full answers array (user's labels, quotes, explanations)
  - **Why**: CRITICAL—answers deleted from main table, must survive in audit log
  - **Action to verify**: In audit log details, ensure you can see the full test answers even though TestSubmission rows are gone

- [ ] **Admin login logged**: 
  - Log out, log in via `/admin/login`
  - Check audit log for action="admin_login"
  - Expected: Entry shows actor IP address
  - **Why**: Access tracking for security

---

## Part C: Dark Mode (C) 🌙

### C1: Dark Mode Infrastructure
- [ ] **Theme toggle button visible**: 
  - Check nav bar top-right
  - Expected: Button with moon/sun icon (🌙 in light mode, ☀️ in dark mode)
  - **Why**: User-facing control

- [ ] **Click toggle**: 
  - Click theme toggle button
  - Expected: Page darkens, icon changes, localStorage updated
  - **Why**: Theme must persist and apply globally

- [ ] **Theme persists across page reload**: 
  - Toggle to dark, refresh page (F5)
  - Expected: Page stays dark, localStorage "theme" = "dark"
  - **Why**: State persistence required

- [ ] **System preference respected (first visit)**: 
  - Incognito window, no localStorage
  - Expected: If system dark mode is on (OS settings), page loads dark; if light, loads light
  - **Why**: Respects user OS preference

- [ ] **No flash of wrong theme (anti-FOUC)**: 
  - Incognito window, toggle to dark, full page reload
  - Expected: NO white flash before dark mode applies
  - **Why**: Inline script must run before Tailwind renders

### C2: Dark Mode Styling (Audit Template Coverage)
Test each page in BOTH light and dark mode:

- [ ] **Landing page (`/`)**: 
  - Colors readable, no harsh contrast, gradient smooth
  - Test both modes

- [ ] **Login page (`/login`)**: 
  - Card visible, text readable, button distinct
  - Test both modes

- [ ] **Annotate page (`/annotate`)**: 
  - Passage panel readable
  - Citation panel readable
  - Buttons distinct
  - `<fact>` highlights visible (red underlined text)
  - **Critical**: Fact highlight color must NOT be white-on-black (should be accent color like pink/red)
  - Test both modes

- [ ] **Dashboard (`/dashboard` or `/annotate` for admins)**: 
  - Statistics cards visible
  - Progress bar colors clear
  - Chart.js charts render with correct colors
  - Test both modes

- [ ] **Admin panel (`/admin`)**: 
  - All tabs readable (Summary, Datasets, Tests, Audit Log)
  - Tables readable with distinct header
  - Status badges (Good/Fair/Poor) colors distinct
  - Chart.js charts readable
  - Test both modes

- [ ] **Settings page (`/settings`)**: 
  - Form inputs visible with borders
  - Labels readable
  - Buttons distinct
  - Test both modes

### C3: Chart.js Theming
- [ ] **Charts respond to theme toggle**: 
  - On admin dashboard, open Annotator Breakdown chart (bar chart)
  - Toggle dark mode
  - Expected: Chart colors update live (labels, grid, bars change to dark theme)
  - No page reload needed
  - **Why**: Chart.js must listen to `themechange` event

---

## Part D: Quality Metrics (B) 📊

### D1: Quality Metrics Endpoints
- [ ] **`/api/results/agreement` works**: 
  - Open browser, log in as admin, paste into console:
  ```javascript
  fetch('/api/results/agreement').then(r => r.json()).then(data => console.log(JSON.stringify(data, null, 2)))
  ```
  - Expected: JSON with `overall_agreement_pct`, `pairs_evaluated`, `by_dataset`, `by_citation_type`
  - **Example**: `{"overall_agreement_pct": 75.5, "pairs_evaluated": 12, "by_dataset": {...}, ...}`
  - **Why**: Core metric for quality assessment

- [ ] **`/api/results/agreement/by-annotator` works**: 
  - Paste into browser console (as admin):
  ```javascript
  fetch('/api/results/agreement/by-annotator').then(r => r.json()).then(data => console.log(data))
  ```
  - Expected: Array of objects, each with `email`, `agreement_rate_pct`, `annotations_evaluated`
  - **Example**: `[{email: "user1@example.com", agreement_rate_pct: 80, annotations_evaluated: 10}, ...]`
  - **Why**: Per-annotator quality tracking

- [ ] **`/api/results/by-annotator` includes qualification_score**: 
  - Paste into browser console (as admin):
  ```javascript
  fetch('/api/results/by-annotator').then(r => r.json()).then(data => console.log(data[0]))
  ```
  - Expected: First object has `qualification_score` field (e.g., `qualification_score: 85`)
  - **Why**: Needed for quality flag calculation

### D2: Dashboard Quality Metrics UI
- [ ] **Annotator Details table visible**: 
  - Admin: `/admin#dashboard` → scroll to Annotator Details table
  - Expected: Table with columns:
    - Email
    - Annotation Count
    - Qualification Score
    - **Agreement %** (new column)
    - **Quality Flag** (Good/Fair/Poor badges) (new column)
    - Status
  - **Why**: Consolidated view for annotator evaluation

- [ ] **Quality Flag calculation correct**: 
  - Verify one "Good" annotator (score 80, agreement 90)
  - Verify one "Fair" annotator (score 60, agreement 50)
  - Verify one "Poor" annotator (score 40, agreement 30)
  - Expected: Badges show ✅ Good, ⚠️ Fair, ❌ Poor with correct colors (green/yellow/red)
  - **Formula**: avgQuality = (qualification_score + agreement_rate_pct) / 2
    - >= 70 = Good
    - >= 50 = Fair
    - < 50 = Poor
  - **Why**: Actionable quality indicator

- [ ] **Inter-Annotator Agreement card displays**: 
  - Admin: `/admin#dashboard` → scroll to "Inter-Annotator Agreement" card
  - Expected: Shows overall_agreement_pct and caveat text:
    - *"Proxy metric based on annotator consensus, not verified accuracy — qualification score above is ground truth"*
  - **Why**: Prevents conflating consensus with correctness

- [ ] **Chart.js Annotator breakdown renders**: 
  - Admin: `/admin#dashboard` → Annotator Breakdown bar chart
  - Expected: X-axis = annotator emails, Y-axis = annotation counts, bars visible
  - Verify colors change when toggling dark mode
  - **Why**: Visual annotator performance comparison

---

## Part E: Error Handling & Logging (A4b) 🔧

### E1: Error Message Gating (FLASK_DEBUG-aware)
- [ ] **On Production (FLASK_DEBUG=false)**: 
  - Trigger an error (e.g., invalid JSON POST to an endpoint)
  - Expected: Response shows generic message *"An unexpected error occurred. Please try again."*
  - NO stack trace, NO secrets leaked
  - **Why**: Production security

- [ ] **Full traceback in logs**: 
  - Check Railway logs for the same request
  - Expected: Full exception traceback visible in stderr
  - **Why**: Debugging without exposing to clients

### E2: Error Logging Verification
- [ ] **Failed email send logged, doesn't crash**: 
  - Temporarily break MAIL_SERVER config (set to fake host)
  - Admin: Approve a test submission (triggers email)
  - Expected: Approval succeeds, user marked test_approved_by_admin=True, but email fails gracefully
  - Check Railway logs: Error logged with `current_app.logger.exception("Error sending approval email...")`
  - **Why**: Email is non-critical; ops should not fail on email issues

---

## Part F: Production Deployment Verification ✅

### F1: Railway Configuration
- [ ] **Environment variables set on Railway**: 
  - Check Railway dashboard → Variables
  - Required vars present:
    - `SESSION_COOKIE_SECURE=true` ✅ (user added)
    - `FLASK_DEBUG=false`
    - `ADMIN_SECRET_TOKEN=...`
    - `MAIL_SERVER=smtp.gmail.com` (TODO: add if missing)
    - `MAIL_PORT=587`
    - `MAIL_USE_TLS=True`
    - `MAIL_USERNAME=...` (Gmail app password) (TODO: add if missing)
    - `MAIL_PASSWORD=...` (Gmail app password) (TODO: add if missing)
    - `MAIL_DEFAULT_SENDER=noreply@wikifactcheck.com`
    - `DATABASE_URL` (PostgreSQL on Railway)
    - `SECRET_KEY`
    - `APP_URL=https://wikifactcheck.up.railway.app` ✅ (user added)
  - **Why**: Production config must be complete
  - **Note on emails**: If you want to be CC'd on all annotator emails, add a new env var `MAIL_CC_ADMIN=your-email@gmail.com` and the app will forward all outgoing emails to that address

- [ ] **Entrypoint runs migrations**: 
  - Push a dummy commit to trigger redeploy
  - Check Railway logs during startup
  - Expected log lines:
    - *"[INFO] Starting application initialization..."*
    - *"[INFO] Flask-Migrate found, attempting upgrade..."*
    - *"[INFO] Database upgraded successfully via Flask-Migrate"*
    - *"[INFO] All tables created/verified via SQLAlchemy"*
    - *"[INFO] Database initialization complete"*
    - *"[INFO] Starting gunicorn..."*
  - **Why**: DB schema must initialize before app starts

- [ ] **gunicorn starts with 2 workers**: 
  - Check Railway logs for gunicorn startup
  - Expected: `gunicorn --bind 0.0.0.0:5000 --timeout 60 --workers 2 main:app`
  - **Why**: Multiple workers handle concurrent requests (race condition risk)

### F2: Live Smoke Tests
- [ ] **Home page loads**: `https://wikifactcheck.up.railway.app/` → redirects correctly
- [ ] **Annotate page loads**: `/annotate` → pairs load (not eternally loading)
- [ ] **Admin panel loads**: `/admin` → dashboard visible with all tabs
- [ ] **Settings page loads**: `/settings` → form visible
- [ ] **API endpoints respond**: 
  - `/api/results/summary` → JSON
  - `/api/results/agreement` → JSON
  - `/admin/audit-log` → paginated JSON

---

## Part G: Regression Testing 🔄

### G1: Core Features Still Work
- [ ] **Annotation flow works end-to-end**: 
  - Log in as annotator
  - Load a pair
  - Enter label, quote, explanation
  - Save & Next
  - Expected: Pair saved, next pair loads, count increments
  - **Why**: Primary feature must not regress

- [ ] **Test submission flow works**: 
  - Log in as test user
  - Take qualification test
  - Submit answers
  - Admin approves
  - Expected: User marked test_approved_by_admin, can now annotate
  - **Why**: Qualification gate must work

- [ ] **Dataset upload still works**: 
  - Admin: Upload JSONL dataset
  - Expected: File parsed, pairs created, audit log entry
  - **Why**: Data ingestion must not break

- [ ] **No console errors**: 
  - Open browser DevTools Console (F12)
  - Perform all above smoke tests
  - Expected: No red errors (warnings OK)
  - **Why**: Detects JS regressions

---

## Part H: Final Sign-Off

### Security Checklist
- [ ] No admin accounts can log in via `/login`
- [ ] All audit log entries have actor_email snapshots
- [ ] SESSION_COOKIE_SECURE=true on production
- [ ] Error responses don't leak stack traces
- [ ] No hardcoded secrets in .env.example (all marked "your-..." placeholders)

### Performance Checklist
- [ ] Admin dashboard loads in < 3 seconds
- [ ] Audit log pagination handles 1000+ entries
- [ ] Dark mode toggle is instant (no flicker)
- [ ] No N+1 queries on annotator agreement calculation

### Completeness Checklist
- [ ] All 9 production tasks from plan are verified working:
  1. ✅ Flask-Migrate initialized with baseline schema
  2. ✅ Claim race condition fix (pair_id unique constraint)
  3. ✅ AuditLog model with record() helper
  4. ✅ Audit logging wired to all admin actions + `/admin/audit-log` endpoint
  5. ✅ Error message gating implemented (FLASK_DEBUG-aware)
  6. ✅ Settings page complete
  7. ✅ Dark mode complete (anti-FOUC, Tailwind, CSS variables, theme.js)
  8. ✅ Quality metrics endpoints + dashboard UI
  9. ✅ SESSION_COOKIE_SECURE env-driven

---

## Known Fixes Applied (2026-07-06)

**Issue**: Audit Log tab showed "Cannot read properties of undefined (reading 'page')" error
- **Root cause**: JavaScript wasn't checking for HTTP errors before parsing response JSON
- **Fix**: Updated `loadAuditLog()` in admin.html to check `response.ok` before processing, and added optional chaining for all pagination fields
- **Status**: ✅ Fixed — Audit Log should now load correctly

**Issue**: Dark mode text unreadable on Settings page (email, created_at, last_login)
- **Root cause**: Missing `dark:text-gray-100` class on display text; containers also missing `dark:bg-gray-800`
- **Fix**: Added dark mode classes throughout settings.html (text, backgrounds, form inputs)
- **Status**: ✅ Fixed — Settings page now renders correctly in dark mode

---

## Sign-Off

- **All tests passing**: _____________________________ (Date: _______) 
  
- **Ready for production**: ✅ / ⚠️ (flag if issues found)

**Notes/Issues Found**:
```
(Use this space to document any issues found during testing)


```

---

## Quick Reference: Key URLs

| Page | URL | Purpose |
|------|-----|---------|
| Landing | `/` | Home page |
| Login | `/login` | User login (annotators only) |
| Admin Login | `/admin/login` | Admin token-based login |
| Annotate | `/annotate` | Annotation interface |
| Dashboard | `/dashboard` | Personal stats (annotators) |
| Admin Panel | `/admin` | Admin control center |
| Settings | `/settings` | User account settings |
| Audit Log Tab | `/admin#audit-log` | Audit log viewer (admin only) |

## Quick Reference: Key API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/results/agreement` | GET | Inter-annotator agreement % |
| `/api/results/agreement/by-annotator` | GET | Per-annotator agreement rates |
| `/admin/audit-log` | GET | Paginated audit log with filters |
| `/admin/dataset/upload` | POST | Upload JSONL dataset |
| `/admin/test/submissions/pending` | GET | Pending test submissions |
| `/admin/test/submissions/<id>/approve` | POST | Approve test submission |
| `/admin/test/submissions/<id>/reject` | POST | Reject test submission |
