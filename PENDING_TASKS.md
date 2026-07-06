# Pending Production Tasks (Post-UAT)

These items have been deferred from the current production release. They should be completed after UAT feedback is collected and reviewed.

---

## P1: Merge Admin Results & Submissions Tabs ⏳

**Priority**: High  
**Status**: Deferred (discussed multiple times, needs implementation)  
**Effort**: Medium (2-3 hours)

**Rationale**:
- `/admin#results` and `/admin#submissions` show overlapping data
- Results tab: per-annotator stats, agreement rates, quality flags
- Submissions tab: test submissions awaiting approval
- These should be unified into a single "Annotators" or "Results" dashboard

**What to do**:
1. Merge the two tabs into one cohesive view
2. Show annotators with:
   - Email, qualification score, agreement rate
   - Test submission status (pending/approved/rejected)
   - Action buttons (approve/reject) if still pending
   - Quick stats: annotations completed, target progress

3. Keep separate "Tests" tab for marking samples + viewing pending (as-is)

**Files affected**:
- `templates/admin.html` (merge tab content)
- `routes_dashboard.py` or `routes_admin.py` (may need new combined endpoint)

**Owner**: TBD  
**Target**: Post-UAT release 2

---

## P2: Email Confirmation + Permanent Wikipedia Username ⏳

**Priority**: High (security + UX)  
**Status**: Deferred (was A0 in original plan)  
**Effort**: Large (4-6 hours)

**Rationale**:
- Current design: email-only login, wiki_username optional
- Goal: prevent account hijacking, tie identity to email+username pair
- Email confirmation ensures user owns the email address

**What to do**:

1. **New registration flow**:
   - User enters email + wiki_username
   - System checks: email not already registered, wiki_username not taken by confirmed account
   - Send confirmation email with token link
   - User clicks link, confirms email
   - Account unlocked, can now log in with email+username combo

2. **Schema changes** (via Flask-Migrate):
   - Add to `User` model:
     - `email_confirmed` (Boolean, default False)
     - `confirmation_token` (String, nullable)
     - `confirmation_token_expires_at` (DateTime, nullable)
   - Make `wiki_username` NOT NULL (after backfill)
   - Add unique constraint on (email, wiki_username) pair

3. **New routes**:
   - `GET /register` — registration form
   - `POST /register` — create user, send confirmation email
   - `GET /confirm/<token>` — confirm email, enable account
   - Update `POST /login` — validate email+username combo against confirmed accounts only

4. **Settings page conflict resolution**:
   - Currently allows email change with no re-confirmation
   - Option A: Require re-confirmation on email change
   - Option B: Verify ownership via current email before changing
   - Decide which approach during implementation

5. **Existing users**:
   - Create migration to backfill missing wiki_usernames
   - Mark all existing users as confirmed (historical data)

**Files affected**:
- `models.py` (User schema)
- `main.py` (new routes)
- `templates/register.html` (new)
- `templates/login.html` (update to require wiki_username)
- `routes_settings.py` (email change flow update)
- `migrations/` (new migration)
- `.env.example` (EMAIL_CONFIRMATION_EXPIRES_HOURS config)

**Owner**: TBD  
**Target**: Post-UAT release 2 or 3  
**Blocking**: None (current login works without this, but strongly recommended before scaling)

---

## P3: Test Result Export & Detailed Reporting ⏳

**Priority**: Medium  
**Status**: Nice-to-have  
**Effort**: Small (1-2 hours)

**What to do**:
- Add endpoint to export test results with answer details (what each annotator answered per question, correct answer, score)
- Add CSV export button to "Tests" tab
- Format: per-annotator, per-pair, with correctness feedback

**Owner**: TBD  
**Target**: Post-UAT release 3

---

## P4: Annotator Progress Notifications ⏳

**Priority**: Low  
**Status**: Enhancement  
**Effort**: Medium (2-3 hours)

**What to do**:
- Send weekly digest email to annotators showing:
  - Annotations completed this week
  - Progress toward personal target
  - Current quality metrics
  - Leaderboard rank

**Owner**: TBD  
**Target**: Post-UAT release 3+

---

## P5: Performance Monitoring Dashboard ⏳

**Priority**: Medium (post-launch)  
**Status**: Enhancement  
**Effort**: Large (3-4 hours)

**What to do**:
- Admin dashboard: system health metrics
  - Active annotators
  - Pairs assigned this hour/day
  - Email delivery success rate
  - API response times
  - Database query performance

**Owner**: TBD  
**Target**: Post-UAT, before wider rollout

---

## Completed Items ✅

These were targeted for this release and are now done:

- ✅ Dark mode (full site coverage)
- ✅ Audit logging (all admin actions)
- ✅ Quality metrics (agreement rates, per-annotator stats)
- ✅ Race condition fix (safe pair assignment)
- ✅ Email approval/rejection workflow
- ✅ Settings page (profile, email change, wiki_username)
- ✅ Error handling & logging (comprehensive)
- ✅ Context processor (current_user available everywhere)

---

## Review Schedule

- **After UAT (1 week)**: Collect feedback, prioritize P1-P2
- **Post-UAT release 1 (2 weeks)**: Implement P1 + P2
- **Post-UAT release 2 (4 weeks)**: Implement P3-P4 based on user feedback
- **Ongoing**: P5 and future enhancements

---

**Last Updated**: 2026-07-05  
**Maintained By**: Abbad (AI Assistant) + Abbad (User)
