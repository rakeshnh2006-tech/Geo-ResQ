# Malenadu Resilience Impact Agent

An AI-powered disaster-response coordination platform for the Malenadu region (Karnataka, India). It uses IBM Granite via watsonx.ai to structure incoming field reports, verify data, assess road accessibility, rank relief needs, and generate coordinator briefings.

---

## Architecture

```
Citizen / Field Worker
        │
        ▼
  Public Intake Form  (/report, /relief)
        │
        ▼
  1. Intake Agent      — Granite extracts structured fields
  2. Verification      — Duplicate / completeness / conflict checks
  3. Accessibility     — NetworkX road-graph BFS (isolated villages)
  4. Relief Assessment — Granite classifies needs + urgency score
  5. Prioritization    — Deterministic composite score + Granite rationale
  6. Briefing          — Granite situation summary → PDF
  7. Dashboard         — Google Maps + tabbed coordinator UI
```

---

## Tech Stack

| Layer      | Technology                              |
|------------|-----------------------------------------|
| Backend    | Python 3.11, Flask, SQLAlchemy          |
| LLM        | IBM Granite via watsonx.ai              |
| Database   | MySQL 8 (IBM Cloud Databases)           |
| Frontend   | HTML5, CSS3, Vanilla JavaScript         |
| Map        | Google Maps JavaScript API              |
| Auth       | Flask-Login, bcrypt, role-based         |
| Deployment | Docker → IBM Cloud Code Engine          |
| OSM data   | pyosmium → MySQL road graph             |

---

## Quick Start (development)

```bash
# 1. Clone and enter the repo
git clone <repo-url> && cd georesq

# 2. Create a virtual environment
python -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 5. Run database migrations
mysql -u root -p < db/migrations/001_initial.sql

# 6. Start the development server
FLASK_ENV=development flask --app "backend.app:create_app()" run --port 5000
```

---

## Running Tests

```bash
pytest backend/tests/
```

---

## Deployment (IBM Cloud Code Engine)

```bash
bash scripts/deploy.sh
```

See `scripts/deploy.sh` and ST-14 for full details.

---

## Project Structure

```
.
├── backend/
│   ├── app.py              # Flask application factory
│   ├── config.py           # Environment-based configuration
│   ├── agents/             # 6 AI agent modules
│   ├── models/             # SQLAlchemy ORM models
│   ├── routes/             # Flask blueprints
│   ├── utils/              # Shared helpers (audit, watsonx client, decorators)
│   └── tests/              # pytest test suite
├── frontend/
│   ├── templates/          # Jinja2 HTML templates
│   └── static/             # CSS, JS, images
├── db/
│   ├── migrations/         # SQL migration scripts
│   └── seed.sql            # Development seed data
├── scripts/
│   ├── import_osm.py       # OSM road-network importer
│   └── deploy.sh           # IBM Cloud Code Engine deployment
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| LLM scope | Intake, similarity, classification, briefing only | Keeps scoring deterministic and auditable |
| Human-in-the-loop | No agent issues official alerts | Safety and regulatory requirement |
| Road graph | NetworkX in-memory | No separate graph database needed |
| Disclaimer | Template-injected, not LLM-generated | Cannot be accidentally omitted |
| Prioritization score | Pure Python formula | Transparent, reproducible, auditable |
