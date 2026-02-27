# Opportunity Intelligence Agent

Autonomous funding and contracting opportunity discovery for George Johnston — Wellington, NZ.

## Quick Start

### 1. Prerequisites

- Python 3.11+
- An Anthropic API key (for fit scoring, brief generation, application drafting)

### 2. Install

```bash
cd opportunity-agent
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 4. Run

```bash
python run.py
```

Open **http://localhost:5000** in your browser.

---

## First Use

1. Open the web UI at http://localhost:5000
2. Go to **Settings & Scraper**
3. Click **Start Scrape** (first run takes 2–5 minutes)
4. Refresh after ~60 seconds to see new opportunities
5. Browse the **Opportunities** list, sorted by fit score
6. Mark opportunities as **Interested** to track them
7. Use **Generate Draft** on any opportunity to get an AI-written application

---

## How It Works

### Fit Scoring (1–10)

Every opportunity is scored against your practitioner profile using Claude (claude-opus-4-6).

**Base score tiers:**
- **8–10**: Direct match — school counselling, community mental health, Māori-informed practice, mindfulness, creative/arts work
- **5–7**: Adjacent — achievable with partnership or some framing
- **1–4**: Tangential — wrong sector or missing credentials

**Automatic adjustments (B8 rules):**
| Condition | Score change |
|---|---|
| Māori community experience is a competitive edge | +1 |
| School-based background is directly relevant | +1 |
| Warm/Hot contact at this funder | +1 |
| Requires full NZAC registration | −1 |
| Requires organisational affiliation | −2 |
| Requires Te Reo Māori fluency | −1 |

> Opportunities requiring organisational affiliation are **flagged but not filtered** — partnership arrangements may be possible.

### Sources Scraped

**NZ Funders:**
- Creative New Zealand (all streams including music, writing, research)
- NZ On Air (music funding)
- Community Matters / Lottery Grants Board
- Ministry of Social Development
- Te Puni Kōkiri
- Foundation North
- Wellington Community Trust
- Tindall Foundation
- Todd Foundation

**International:**
- Wellcome Trust
- Open Society Foundations
- Robert Wood Johnson Foundation

**Tenders:**
- GETS (Government Electronic Tenders Service) — filtered for health, mental health, education, youth, community, Māori development, research

### Monthly Schedule

The scraper runs automatically on the **1st of each month at 08:00 NZT**.
Trigger a manual run anytime from the Settings page.

### Intelligence Brief

After each scrape, a 1–2 page intelligence brief is generated covering:
- What funders are prioritising this month
- Language and framing appearing across multiple sources
- Gaps between stated priorities and visible ground-level need
- Emerging opportunities worth watching

### Application Drafting

For any opportunity you mark as Interested, click **Generate Draft** to get a first-draft application tailored to your profile and the funder's stated priorities.

---

## Updating Your Profile

Edit `profile.json` to update your competencies, impact data, or affiliations. Changes take effect on the next scrape.

Key sections:
- `identity` — registration status, entity type, languages
- `competencies` — scoring keywords per domain
- `scoring_rules` — the B8 adjustments
- `funding_keywords` — terms used for matching

---

## CLI Commands

```bash
# Start web UI (with background scheduler)
python run.py

# Run scrape immediately
python run.py --scrape

# Scrape specific sources only
python run.py --scrape --sources creative_nz nz_on_air gets

# Regenerate this month's brief
python run.py --brief

# Disable scheduler (just run the web UI)
python run.py --no-scheduler
```

---

## Deployment on a VPS

```bash
# Install dependencies
pip install -r requirements.txt gunicorn

# Set environment variables
export ANTHROPIC_API_KEY=sk-ant-...
export SECRET_KEY=your-secret-key
export PORT=5000

# Run with gunicorn
gunicorn -w 1 -b 0.0.0.0:5000 "run:create_app()"
```

Note: use `-w 1` (single worker) to avoid APScheduler running multiple times.

---

## Project Structure

```
opportunity-agent/
├── run.py              # Entry point
├── app.py              # Flask web application
├── config.py           # Configuration + funder source list
├── models.py           # SQLAlchemy database models
├── scorer.py           # Fit scoring (Claude + rule-based adjustments)
├── intelligence.py     # Brief generation + application drafting
├── scheduler.py        # APScheduler monthly job
├── exporters.py        # Markdown and PDF export
├── profile.json        # George's practitioner profile (scoring ground truth)
├── scrapers/
│   ├── base.py         # Base scraper class
│   ├── nz_funders.py   # NZ funder scrapers
│   ├── intl_funders.py # International funder scrapers
│   └── gets.py         # GETS tender scraper
├── templates/          # Flask/Jinja2 HTML templates
└── data/               # SQLite database (auto-created)
```
