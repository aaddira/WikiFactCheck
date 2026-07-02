# Migration Guide: New Test Submission Flow

## Database Changes
The following columns and tables have been added to support the new workflow:

### User Model Updates
- `test_submitted` (bool) - Whether user has submitted their test
- `test_submission_date` (datetime) - When test was submitted
- `test_approved_by_admin` (bool) - Whether admin approved them
- `test_approval_date` (datetime) - When admin approved

### New Table: TestSubmission
Tracks individual test answers for save/resume functionality:
- `id` - Primary key
- `user_id` - FK to users
- `pair_id` - FK to pairs (test samples only)
- `label` - Their answer (TRUE/FALSE/MIXED/etc)
- `quote` - Quote from citation
- `explanation` - Their reasoning
- `is_submitted` - Whether this is part of final submission
- `submission_batch_id` - Groups answers from same attempt
- `created_at`, `updated_at` - Timestamps

## Setup Instructions

### Local Development
```bash
# Fresh database
rm -f data/app.db
python -c "from dotenv import load_dotenv; load_dotenv(); from main import app, db; with app.app_context(): db.create_all(); from data_loader import seed_default_config; seed_default_config()"
```

### Railway Deployment

#### Option 1: Fresh Database on Railway (Recommended)
1. In Railway dashboard, connect to your app's database service via the terminal
2. Delete existing database:
   ```bash
   rm /data/app.db  # Or wherever your volume is mounted
   ```
3. Initialize database by redeploying the app (which runs `db.create_all()`)
4. Seed default config:
   ```bash
   cd /app
   python -c "from dotenv import load_dotenv; load_dotenv(); from main import app, db; with app.app_context(): db.create_all(); from data_loader import seed_default_config; seed_default_config()"
   ```

#### Option 2: Migrate Existing Database on Railway
If you already have data on Railway, add columns and table manually via Railway's SQL terminal:

1. Add columns to users table:
```sql
ALTER TABLE users ADD COLUMN test_submitted BOOLEAN DEFAULT 0;
ALTER TABLE users ADD COLUMN test_submission_date DATETIME;
ALTER TABLE users ADD COLUMN test_approved_by_admin BOOLEAN DEFAULT 0;
ALTER TABLE users ADD COLUMN test_approval_date DATETIME;
```

2. Create test_submissions table:
```sql
CREATE TABLE test_submissions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    pair_id INTEGER NOT NULL,
    label VARCHAR(50),
    quote TEXT,
    explanation TEXT,
    is_submitted BOOLEAN DEFAULT 0,
    submission_batch_id VARCHAR(255),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(pair_id) REFERENCES pairs(id),
    UNIQUE(user_id, pair_id, submission_batch_id)
);
```

## Workflow Changes

### Before (Old Flow)
1. Login → Test Page → Pass test → Immediate access to annotation

### After (New Flow)
1. **Public** → Landing page with preview
2. **Login** → Email login
3. **Test** → Submit test (can save progress)
4. **Pending** → Show results, waiting for admin approval
5. **Admin** → Review test answers, approve/reject user
6. **Approved** → Email sent, user can annotate

## Code Changes Summary

### Templates
- `landing.html` - Public landing page with preview
- `test_post_login.html` - Test page with Save/Submit buttons
- `test_results.html` - Results and pending approval view
- `base.html` - Updated nav with "Start Annotating" button

### Routes
- `main.py` - Updated home redirect logic, new test pages
- `routes_annotate.py` - New test submission flow:
  - `/api/test/save-progress` - Save without submitting
  - `/api/test/submit` - Submit for review
  - `/api/test/retake` - Reset for retaking
  - `/api/pair/preview` - Public preview (no auth)

### Models
- `models.py` - Added TestSubmission table + User fields

## Completed

✅ **Admin Test Review Dashboard** (routes_admin.py):
   - `/api/admin/test/submissions/pending` - List pending submissions with answers
   - `/api/admin/test/submissions/<user_id>/approve` - Approve user + send email
   - `/api/admin/test/submissions/<user_id>/reject` - Reject user + optional message
   - UI tab in admin.html to review and action on pending tests

✅ **Email Configuration** (main.py):
   - Flask-Mail setup configured
   - Email templates for approval and rejection
   - Email sending on admin action

✅ **Database Init Instructions** (MIGRATION_NEW_FLOW.md):
   - Fresh database setup for Railway
   - Migration guide for existing databases

## Still TODO (Optional)

1. **Annotate Page Protection** (templates/annotate.html):
   - Add check to verify user has `test_approved_by_admin = True`
   - Show message if trying to access without approval

2. **Email Template Enhancement**:
   - More polished HTML email templates
   - Branded header/footer
   
3. **Analytics Dashboard**:
   - Track test submission completion rates
   - Approval/rejection ratios

## Testing the Flow

1. Deploy to Railway
2. Clear database and re-init (or migrate)
3. Create test samples in admin panel
4. Visit landing page (no login) - should see preview
5. Click "Start Annotating" - go to login
6. Enter email - redirect to test page
7. Fill test, click "Save Progress" - should save
8. Click "Submit Test" - should mark as submitted
9. Redirect to test results page (pending)
10. Admin logs in, approves user
11. User sees approval, can now annotate
