# WikiFactCheck Citation-Support Annotation Platform

> **[🚀 Live Platform](https://wikifactcheck.up.railway.app)** — Start annotating now

## What is this?

**WikiFactCheck** is an open-source annotation platform built to crowdsource testing of LLMs as a tool for the verficiation of Wikipedia's sources. The tool is part of a [Wikimedia Rapid Grant project](https://meta.wikimedia.org/wiki/Grants:Programs/Wikimedia_Community_Fund/Rapid_Fund/Wikipedia%27s_Factual_GenAI_Assistant_Experiment_(ID:_23544856)), which aims to systemaically compare Claude, GPT and the open soruce fact-checking model MiniCheck on this task. A related project with which we're partnering is [Wikipedia Citation Verification - LLM Benchmarking](https://github.com/alex-o-748/citation-checker-script/blob/main/docs/llm-benchmarking-overview.md), an effort led by the WikiProject AI Tools of English Wikipedia's community.

This matters because:
- **For Wikipedia editors**: Identifying broken or misplaced citations improves the encyclopedia's reliability at scale
- **For LLM research**: Citation support patterns (or lack thereof) help researchers understand what makes sources trustworthy and how to train better fact-checking models
- **For the open web**: Every annotation generated here feeds into a public dataset that anyone can use

The platform is **lightweight and self-hosted** — no cloud lock-in, no email services, no OAuth. Spin up an instance locally or on Railway in minutes, upload your data, and start collecting high-quality human annotations.

## Quick Start

### Setup

```bash
cd "C:\Users\aaddi\Downloads\Wiki RAG\annotation-platform"

# Install dependencies (first time only)
pip install -r requirements.txt

# Initialize database (first time only)
python -c "
from dotenv import load_dotenv
load_dotenv()
from main import app, db
with app.app_context():
    db.create_all()
    from data_loader import seed_default_config
    seed_default_config()
"

# Start the server
python main.py
```

Visit **http://localhost:5000** in your browser.

### Uploading Data

1. Log in with any email (e.g., aaddira@gmail.com)
2. Go to **/admin** (you'll be redirected there as admin)
3. Click **Upload Dataset**
4. Select your JSONL file (e.g., `journal_book_pairs.jsonl`) and give it a name

### Annotation Workflow

1. **Login** with your email (no password needed)
2. **Qualification Test** — Pass a 5-sample test to qualify
   - Test samples marked by admin with correct labels
   - Must score ≥80% (configurable) to proceed
3. **Annotation** — Label passage/citation pairs:
   - **True** — Citation clearly supports the passage
   - **False** — Citation contradicts the passage
   - **Mixed** — Some claims supported, others not
   - **No Sufficient Information** — Cannot determine support
   - **Unverifiable** — No factual claims to verify
4. **Quote & Explanation** — Provide exact text from citation + brief reasoning
5. **Skip** — Defer any pair you're unsure about (no penalty)

### Admin Panel (/admin)

- **Upload Dataset**: JSONL file → create new annotation project
- **Datasets**: Toggle active/inactive, view sample counts, delete
- **Configuration**:
  - `ANNOTATORS_PER_SAMPLE`: How many annotators per pair (default: 3)
  - `MIN_SAMPLES_FOR_TARGET`: Pairs needed to complete project (default: 300)
  - `DOMAIN_DISTRIBUTION`: % allocation by research domain (medicine/history/animals/artists)
  - `QUALIFICATION_THRESHOLD`: Test pass threshold % (default: 80)
  - `MAX_ANNOTATIONS_PER_USER`: Per-annotator cap (blank = unlimited)
  - `ANNOTATOR_CAP_ENABLED`: Toggle cap enforcement
  - `SESSION_TIMEOUT_MINUTES`: Session duration (default: 7 days)
- **Test Samples**: Mark 5 pairs as qualification test samples + set correct labels
- **Test Results**: View all annotators' qualification scores
- **Export**: Download JSONL/CSV of all annotations and test results

### Dashboard (/dashboard)

View real-time statistics:
- Total pairs, annotations, progress toward target
- Per-annotator breakdown (bar chart, colored by qualification status)
- Label distribution (pie chart: True/False/Mixed/Insufficient/Unverifiable)
- Dataset progress (per-dataset annotation completion %)

## Architecture

### Tech Stack
- **Backend**: Flask + SQLAlchemy
- **Database**: SQLite (single file, no setup)
- **Frontend**: Vanilla HTML/CSS/JavaScript + Tailwind CDN + Chart.js
- **Deployment**: Docker + Railway (ready-to-deploy)

### Database Schema

- **users**: Annotator accounts (email-based login, no passwords)
- **datasets**: Import batches (JSONL uploads)
- **pairs**: Passage/citation records (with real-schema field mapping from WikiFactCheck pipeline)
- **annotations**: User labels + quotes + explanations (with timestamp)
- **claims**: Temporary lock records (prevent two annotators getting same pair simultaneously)
- **skips**: Records of pairs annotators skipped
- **config**: Runtime configuration (all settable via admin panel)

### Key Features

✓ **Smart Assignment** — Queue prioritizes pairs with 1-2 annotations to ensure all pairs get 3x coverage  
✓ **Domain Weighting** — Samples drawn proportionally from medicine/history/animals/artists per config  
✓ **Qualification Test** — Annotators must pass before accessing real dataset; tracks individual accuracy  
✓ **Annotation Cap** — Limit per-user annotations (configurable or unlimited)  
✓ **Skip Logic** — Annotators can defer with no penalty; skipped pairs appear to others  
✓ **Real-Time Dashboard** — Live charts showing annotator progress, label distribution, project completion  
✓ **Multi-Dataset** — Multiple import batches in one project, tracked separately  
✓ **Export** — JSONL/CSV download of all annotations with full metadata for downstream research  
✓ **No External Services** — All-in-one: no Auth0, no cloud storage, no paid email, no OAuth  
✓ **Open Source** — Built in Python/Flask; deploy anywhere (local, Railway, self-hosted)

## Data Format

### Import (JSONL)

Each line is a JSON record with WikiFactCheck schema:

```json
{
  "pair_id": "jb_0010",
  "article_title": "Neurosyphilis",
  "research_domains": ["medicine"],
  "passage_text": "and delirium.",
  "passage_word_count": 3,
  "passage_sentence_count": 1,
  "passage_context": "These symptoms can include dementia, mania, psychosis, <fact>and delirium</fact>.",
  "citation_fields": {
    "title": "A Narrative Review of the Many Psychiatric Manifestations of Neurosyphilis",
    "journal": "Cureus",
    "doi": "10.7759/cureus.44866",
    "date": "September 7, 2023",
    "first1": "Baneet",
    "last1": "Kaur"
  },
  "citation_raw_text": "[full article text...]",
  "citation_source_url": "https://..."
}
```

### Export (JSONL)

Annotated records include:

```json
{
  "pair_id": "jb_0010",
  ...original fields...,
  "label": "TRUE",
  "quote": "Neurosyphilis is an infection of the central nervous system...",
  "explanation": "The citation clearly states that neurosyphilis affects the CNS, supporting the passage.",
  "annotator": "aaddira@gmail.com",
  "timestamp": "2026-06-20T14:32:10Z"
}
```

## Smart Assignment Algorithm

When an annotator clicks "Get next pair":

1. **Check caps**: Skip if annotator hit `MAX_ANNOTATIONS_PER_USER`
2. **Check completion**: Skip if project reached `MIN_SAMPLES_FOR_TARGET` (sufficient 3x coverage)
3. **Build candidate pool**:
   - Pairs not yet annotated by this user
   - Not already skipped by this user
   - Not test samples
   - Not claimed by another annotator (or claim expired 30 min)
   - Filtered by `DOMAIN_DISTRIBUTION` (exclude domains that hit target)
4. **Tier by coverage**:
   - Tier 1: Pairs with 2 annotations (need 3rd)
   - Tier 2: Pairs with 1 annotation (need 2nd)
   - Tier 3: Pairs with 0 annotations (fresh)
5. **Randomize within tier**: Different order per user/session
6. **Claim & return**: Lock pair to user for 30 min, return first available

Result: Balanced coverage across all pairs, no duplicates per user.

## Deployment to Railway

### Step 1: Prepare Git repo

```bash
cd annotation-platform
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/annotation-platform.git
git push -u origin main
```

### Step 2: Railway Setup

1. Go to [railway.app](https://railway.app)
2. Create new project → "Deploy from GitHub repo"
3. Select your annotation-platform repo
4. Railway auto-detects Dockerfile and builds
5. Set environment variables:
   - `FLASK_ENV=production`
   - `SECRET_KEY=<generate random string>`
   - `ADMIN_EMAILS=aaddira@gmail.com`
6. Add a **volume** mounted at `/app/data` for persistent SQLite
7. Deploy

Your app will be live at `https://<project-name>.up.railway.app`

## Customization

### Change labels

Edit the 5 labels in `routes_annotate.py` and `templates/annotate.html`.

### Customize instructions

Edit the HTML block in `templates/annotate.html` (the `<div class="instructions">` section).

### Change domain list

Update `DOMAIN_DISTRIBUTION` in the config panel or in `data_loader.py`'s seed defaults.

### Adjust test threshold

Edit `QUALIFICATION_THRESHOLD` in admin panel (default: 80%).

### Styling

All styles are in `static/css/style.css` (Tailwind + custom classes). Modify freely.

## Troubleshooting

### "Database locked" error
SQLite has issues with concurrent writes. Increase the timeout:
```python
# main.py, line ~11
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"timeout": 30}}
```

### Server won't start
Check the `.env` file is in the project root and `DATA_URL` is correct:
```
DATABASE_URL=sqlite:////path/to/data/app.db
```

### Admin login not working
Verify `ADMIN_EMAILS` in `.env` includes your email:
```
ADMIN_EMAILS=aaddira@gmail.com,other@example.com
```

## Future Enhancements (v2+)

- [ ] Inter-annotator agreement (Cohen's kappa)
- [ ] Disagreement resolution workflow
- [ ] Real-time collaboration (WebSocket)
- [ ] Mobile-responsive design
- [ ] Dataset versioning & rollback
- [ ] Batch operations (bulk reassign, reset)
- [ ] User-per-domain quotas
- [ ] Custom label sets per project
- [ ] Anonymous mode (no email collection)

## Using the Data

All exported annotations are in open format (JSONL) with no vendor lock-in. Use them for:
- **Wikipedia citation audits** — Identify problematic citations at scale
- **LLM training** — Fine-tune fact-checking and citation-ranking models
- **Citation analysis** — Study patterns in how sources support claims (or don't)
- **Your own research** — The data is yours to analyze and publish

## License

[MIT License](LICENSE) — Use freely, contribute back if you improve it.

---

**Built with**: Flask, SQLAlchemy, SQLite, Tailwind, Chart.js, Vanilla JS  
**Status**: Production-ready for small teams (1-50 annotators)  
**Python**: 3.10+  
**Last Updated**: July 7, 2026
