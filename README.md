# Pātaka — Wellington Community Grants Monitor

Keeping up with Wellington's funding landscape is a part-time job in itself — deadlines scattered across council websites, trust portals, and government funding pages, most of which don't tell you when things open or close. This tool watches those sources for you.

It scrapes Wellington and national funders on a monthly schedule, scores each opportunity against your organisation's profile, and presents the results in a local web dashboard — prioritised by fit, flagged by deadline, and ready to draft from.

## The name

**Pātaka** (pah-tah-kah) — a Māori word for storehouse or food repository. Traditionally, a pātaka was a raised structure where a community kept its provisions: food, resources, and the things needed to sustain people through leaner times.

This tool is a pātaka of funding information: a place where resources are gathered, held, and made accessible to the Wellington community organisations that need them.

## Who it's for

- Community trust and NGO managers
- Social workers and community developers
- Volunteer coordinators
- Anyone in the Wellington region applying for community, arts, environment, or social wellbeing grants

## What it monitors

### Wellington regional funders
| Funder | Type | Coverage |
|---|---|---|
| Wellington City Council | Local council | Community grants, Creative Communities Scheme, Neighbourhood Fund |
| Greater Wellington Regional Council | Regional council | Environment, heritage, and community wellbeing grants |
| Wellington Community Trust | Philanthropic trust | Arts, sport, social services, environment |
| Nikau Foundation | Community foundation | Health, social services, arts, environment |
| Hutt City Council | Local council | Lower Hutt community grants |
| Upper Hutt City Council | Local council | Upper Hutt community grants |
| Lion Foundation | Gaming trust | Sport, recreation, community, arts (monthly rounds) |
| Four Winds Foundation | Philanthropic trust | Community wellbeing, youth, families |
| Māngai Pāho | Crown entity | Te reo Māori broadcasting and community media |
| Pacific Trust Aotearoa | Community trust | Pasifika community funding; also Ministry for Pacific Peoples |

### National NZ funders
| Funder | Focus |
|---|---|
| Creative New Zealand | Arts grants, residencies, awards |
| NZ On Air | Music and media funding |
| Community Matters (Lottery Grants Board) | Community, welfare, environment, Māori purposes |
| Ministry of Social Development | Social services grants |
| Te Puni Kōkiri | Māori development, housing, and community funding |
| Tindall Foundation | Community development |
| Todd Foundation | Community and social wellbeing |

> **Note:** International funders (Wellcome Trust, Open Society Foundations, RWJF) are included but lower priority for most Wellington community orgs. They may be removed in a future release.

> **Not included:** Government procurement (GETS/tenders). That is handled by a separate project.

## How to configure it

1. Copy the example profile to `profile.json`:
   ```
   cp profile.example.json profile.json
   ```
   `profile.json` is gitignored and will never be committed — your organisation's data stays local.

2. Edit `profile.json` to describe your organisation:
   - **`identity`** — org name, type, region, focus areas, registration status, budget range
   - **`demonstrated_impact`** — concrete impact metrics and active programmes
   - **`competencies`** — your areas of strength with keywords and evidence. Higher `weight` = stronger match priority. These drive both Claude scoring and keyword fallback scoring.
   - **`funding_keywords`** — additional keywords for the fallback scorer
   - **`geographic_priority`** — how to weight NZ regions (10 = highest priority)

   `profile.example.json` contains a worked example (fictional Aro Valley Community Trust) you can use as a reference. `org_profile.template.json` is a blank template with placeholder instructions if you prefer to start from scratch.

3. Set your Anthropic API key in `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   Without this key, the tool falls back to keyword-based scoring (less nuanced but functional).

## How to run it

### One-off scrape
```bash
python run.py --scrape
```

### Start the web UI (with background scheduler)
```bash
python run.py
```
Opens at [http://localhost:5000](http://localhost:5000)

### Recurring scheduled scrape
The scheduler runs automatically on the 1st of each month at 08:00 NZT when the web UI is running. You can also trigger a manual scrape from the Settings page in the UI.

## Setup (first time)

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env to add ANTHROPIC_API_KEY
cp profile.example.json profile.json
# edit profile.json for your organisation (it's gitignored — safe to put real data here)
python run.py
```

## How scoring works

Each opportunity is scored 1–10 for fit against your `profile.json`:

- **8–10**: Direct match — funder priorities align with your demonstrated work
- **5–7**: Adjacent — relevant but requires some stretch or partnership framing
- **1–4**: Tangential — outside your focus or requires credentials not held

Scores are adjusted by deterministic rules:
- +1 if the opportunity has a Māori community focus (competitive edge)
- +1 if youth/community focus aligns with your work
- +1 if you have a warm contact at the funder (add them in Contacts)
- −1 if full clinical registration is required
- −2 if organisational affiliation is required (flags the constraint, doesn't filter it out)
- −1 if Te Reo Māori fluency is required

## Web UI

The dashboard shows:
- Upcoming deadlines (next 60 days, score ≥ 5)
- High-fit opportunities (score ≥ 8)
- Monthly intelligence brief (AI-written summary of funder patterns)
- Full opportunity list with filters (score, status, funder, flags)
- Application drafting (AI drafts a first-cut EOI or grant application)
- Contacts (track warm relationships with funders)
- Export to Markdown or PDF

## Licence

MIT
