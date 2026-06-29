# Getting Started — WikiFactCheck Annotation Platform

Your annotation platform is **ready to use**. Here's how to get started in the next 15 minutes.

## 1. Import Your Data

First, load your annotation dataset:

```bash
cd "C:\Users\aaddi\Downloads\Wiki RAG\annotation-platform"
python main.py
```

Visit: **http://localhost:5000**

- **Log in** with your email (no password needed) — e.g., `aaddira@gmail.com`
- You'll be redirected to **/admin** since you're in `ADMIN_EMAILS`
- Click **"Upload Dataset"** tab
- Select the JSONL file (e.g., `C:\Users\aaddi\Downloads\Wiki RAG\WikiFactCheck\output\journal_book_pairs.jsonl`)
- Give it a name like **"Journal Citations - June 2026"**
- Click **Upload**

You'll see: `✓ Loaded: 46` (or however many pairs are in your file)

## 2. Set Up the Qualification Test

Still in Admin panel:

1. Click **"Test Samples"** tab
2. Select 5 pairs that will be your test qualification samples
3. For each, select the **correct label** (True/False/Mixed/No Sufficient Info/Unverifiable)
4. Click **Save Test Samples**

Example:
- Pair jb_0010 → True
- Pair jb_0025 → False
- Pair jb_0057 → Mixed
- Pair jb_0066 → No Sufficient Info
- Pair jb_0159 → Unverifiable

## 3. Configure Settings (Optional)

Still in Admin:

1. Click **"Configuration"** tab
2. Adjust if desired:
   - `ANNOTATORS_PER_SAMPLE`: 3 (default — how many people label each pair)
   - `MIN_SAMPLES_FOR_TARGET`: 300 (default — pairs needed to complete project)
   - `ANNOTATION_TARGET`: Stays at 300 unless you change above
   - Others can stay default for now
3. Click **Save Configuration**

## 4. Test as an Annotator

Open a **new incognito/private browser window**:

1. Go to **http://localhost:5000**
2. Log in with a *different* email — e.g., `test.annotator@example.com`
3. You'll see the **Qualification Test** page
4. Label the 5 test samples with the correct labels you set in step 2
5. Click **Submit Test**
6. If score ≥80%, you'll pass and be redirected to annotation
7. If score <80%, you'll see "You did not pass" and can retry

## 5. Annotate (Real Data)

After passing the test:

1. You'll see the **Annotation Interface**
2. Left side: Wikipedia passage to evaluate
3. Right side: Full journal article citation text
4. **Your task**:
   - Select a label (True/False/Mixed/No Sufficient Info/Unverifiable)
   - Paste the exact **quote** from the citation that supports/contradicts the passage
   - Write a brief **explanation** of how the quote relates
   - Click **Save & Next** or **Skip**

The platform automatically:
- Saves your annotation with timestamp
- Tracks your progress
- Loads the next pair (smart assignment: prioritizes pairs needing more annotations)
- Prevents duplicate annotations (you won't see the same pair twice)

## 6. View Dashboard

Visit **http://localhost:5000/dashboard**:

- **Summary stats**: Total pairs, annotations, progress
- **Bar chart**: Annotations per annotator
- **Pie chart**: Label distribution (True/False/Mixed/etc %)
- **Dataset progress**: Pairs annotated vs. total

Refreshes in real-time as annotators submit labels.

## 7. Export Results

When done annotating:

1. Return to **/admin**
2. Click **"Export"** tab
3. Download:
   - **Annotations as JSONL** — Full records with annotator email + timestamp
   - **Annotations as CSV** — Spreadsheet format
   - **Test Results as CSV** — Who passed/failed qualification

Import into your analysis pipeline.

---

## Common Tasks

### Add More Annotators
Just share the login URL: **http://localhost:5000/login**

They log in with their email, take the qualification test (using your test samples), then annotate.

### Change Annotation Cap

In Admin > Configuration:
- Set `MAX_ANNOTATIONS_PER_USER` to a number (e.g., 50) to limit each person
- Leave blank for unlimited

### Mark Project Complete

Smart assignment stops offering pairs when:
- `MIN_SAMPLES_FOR_TARGET` pairs have reached `ANNOTATORS_PER_SAMPLE` annotations

Example: With defaults (300 target, 3 per sample), once 300 pairs have 3+ annotations each, project is complete.

### Reset an Annotator's Progress

Delete them from `/admin` and create a new account (same email logs them back in fresh).

### Change Labels

Edit `templates/annotate.html` and `routes_annotate.py` to change the 5 label types.

---

## Deployment to the Web (Optional)

When ready to run on the internet:

1. **Push to GitHub**:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR/repo
   git push -u origin main
   ```

2. **Deploy to Railway.app**:
   - Sign up at railway.app
   - Connect GitHub repo
   - Railway auto-builds from Dockerfile
   - Set env vars: `ADMIN_EMAILS`, `SECRET_KEY`, `FLASK_ENV=production`
   - Add volume at `/app/data` for persistent database
   - Deploy!

Your app will be live at `https://<project>.up.railway.app`

---

## Architecture at a Glance

```
┌─────────────────────────────────────────┐
│  Browser (Login, Annotate, Dashboard)  │
└──────────────────┬──────────────────────┘
                   │
        ┌──────────▼──────────┐
        │   Flask REST API    │
        │  (routes_*.py)      │
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │  SQLAlchemy Models  │
        │   (users, pairs,    │
        │  annotations, etc)  │
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────┐
        │  SQLite Database    │
        │  (data/app.db)      │
        └─────────────────────┘
```

No external services. Everything runs in one container.

---

## Troubleshooting

**Server won't start**:
- Ensure `python main.py` runs without errors
- Check `.env` file exists in project root
- Verify `data/` directory exists

**Login not working**:
- Any email works for login
- But only emails in `ADMIN_EMAILS` (.env) get admin access

**Annotation not saving**:
- Check browser console for errors (F12)
- Ensure quote and explanation are filled in
- Verify all required fields are complete

**Charts not showing on dashboard**:
- Wait for data (need some annotations first)
- Check Chart.js CDN is accessible
- Reload the page

---

## Next Steps

1. **Import real data** (step 1 above)
2. **Set up test samples** (step 2)
3. **Share login URL with annotators** — they log in and start
4. **Monitor dashboard** — http://localhost:5000/dashboard
5. **Export results** when ready for analysis

---

**Questions?** Check README.md or look at the code — it's clean and well-commented.

**Ready to launch?** Open http://localhost:5000 now.
