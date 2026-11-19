# GeoResQ — Malenadu Resilience Impact Agent

AI-powered disaster-response coordination platform for the Malenadu region (Karnataka, India).

**Live demo:** _(deploy to Render — see below)_

---

## Architecture

```
Citizen / Field Worker
        │
        ▼
  Public Intake Form  →  1. Intake Agent (IBM Granite extracts fields)
                     →  2. Verification Agent (duplicate + completeness)
                     →  3. Accessibility Agent (NetworkX road graph)
                     →  4. Relief Assessment Agent (Granite classifies needs)
                     →  5. Prioritization Agent (deterministic score)
                     →  6. Briefing Agent (Granite summary + PDF)
                     →  7. Coordinator Dashboard (Google Maps)
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, Flask, SQLAlchemy |
| LLM | IBM Granite via watsonx.ai |
| Database | PostgreSQL (Render) / SQLite (dev) |
| Frontend | HTML5, CSS3, Vanilla JS, Google Maps API |
| Auth | Flask-Login, bcrypt, role-based (citizen / coordinator) |
| Deployment | Render.com (render.yaml Blueprint) |

---

## Quick Start (local dev)

```bash
# 1. Clone and create venv
git clone https://github.com/rakeshnh2006-tech/GeoResQ.git
cd GeoResQ
python3 -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — set WATSONX_API_KEY, WATSONX_PROJECT_ID, GOOGLE_MAPS_API_KEY

# 4. Initialise DB and run
python scripts/init_db.py
flask --app "backend.app:create_app('development')" run --port 5001
```

Open http://127.0.0.1:5001

**Default dev coordinator:** `coord@georesq.com` / `Admin123!`
_(created by `db/seed.sql` — run `python scripts/seed_db.py` after init)_

---

## Deploy to Render.com

1. Fork / push this repo to GitHub
2. Go to **render.com → New → Blueprint**
3. Connect your GitHub repo — Render picks up `render.yaml` automatically
4. Add the two secret env vars:
   - `WATSONX_API_KEY` — your IBM Cloud API key
   - `WATSONX_PROJECT_ID` — your watsonx.ai project ID
5. Click **Apply** — Render builds, creates the PostgreSQL DB, runs `scripts/init_db.py`, and starts gunicorn

---

## Running Tests

```bash
source .venv/bin/activate
pytest backend/tests/ -q
# Expected: 174 passed
```

---

## Project Structure

```
GeoResQ/
├── backend/
│   ├── agents/          # 7 AI agent modules
│   ├── models/          # SQLAlchemy models (11 tables)
│   ├── routes/          # Flask blueprints
│   ├── utils/           # decorators, audit, watsonx client
│   └── tests/           # 174 pytest tests
├── frontend/
│   ├── static/          # CSS, JS, uploads
│   └── templates/       # Jinja2 HTML templates
├── scripts/
│   ├── init_db.py       # Create tables on first deploy
│   ├── import_osm.py    # Load Karnataka OSM road data
│   └── deploy.sh        # IBM Cloud Code Engine deploy
├── db/
│   ├── migrations/      # SQL migration scripts
│   └── seed.sql         # Dev seed data
├── render.yaml          # Render.com Blueprint
├── Procfile             # Fallback start command
├── runtime.txt          # Python version pin
├── Dockerfile           # IBM Cloud Code Engine
└── requirements.txt     # Pinned dependencies
```

---

## Key Design Decisions

| Decision | Choice |
|---|---|
| LLM scope | Intake extraction, similarity rationale, need classification, briefing text only |
| Scoring | Pure Python formula — deterministic, auditable, no LLM |
| Human-in-the-loop | No agent issues official alerts; coordinator must verify |
| Disclaimer | Template-injected, never LLM-generated |
| Watsonx fallback | Rule-based keyword extractor when Watsonx unavailable |

---

## Roles

| Role | Can do |
|---|---|
| **Citizen** | Submit incident reports, submit relief requests, view public status |
| **Coordinator** | All citizen actions + dashboard, verify incidents, block roads, trigger prioritization, generate briefings, manage users |

Coordinator accounts are invite-only (`/auth/admin/users`).
