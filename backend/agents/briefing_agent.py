"""
backend/agents/briefing_agent.py
Briefing Agent — ST-10
=======================
Coordinator-triggered.  Builds a structured snapshot from the DB,
calls Granite to generate a situation summary, then renders the full
briefing to HTML (with a non-removable disclaimer injected at template
level) and exports to PDF via WeasyPrint.

Disclaimer is injected by the template, NOT by Granite.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select

from backend.app import db
from backend.models.briefing import Briefing
from backend.models.incident import Incident, IncidentStatus
from backend.models.prioritization_score import PrioritizationScore
from backend.models.relief_request import ReliefRequest
from backend.utils.watsonx_client import WatsonxError, generate

log = logging.getLogger(__name__)

def _get_pdf_dir() -> Path:
    """Return (and create) the briefings directory, safely falling back to /tmp on serverless."""
    try:
        from flask import current_app
        d = current_app.config.get("PDF_DIR")
        if d:
            p = Path(d)
            p.mkdir(parents=True, exist_ok=True)
            return p
    except Exception:
        pass
    fallback = "/tmp/briefings" if os.environ.get("VERCEL") else "instance/briefings"
    p = Path(os.environ.get("PDF_DIR", fallback))
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        p = Path("/tmp/briefings")
        p.mkdir(parents=True, exist_ok=True)
    return p


# Directory for generated PDF files (relative to project root)
PDF_DIR = Path(os.environ.get("PDF_DIR", "/tmp/briefings" if os.environ.get("VERCEL") else "instance/briefings"))

DISCLAIMER = (
    "⚠ DISCLAIMER: This briefing is AI-generated and intended as a decision-support "
    "tool only.  All critical actions must be verified and authorized by a qualified "
    "human coordinator.  This report does not constitute an official government or "
    "emergency-services communication."
)


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def _build_snapshot() -> dict:
    """Collect aggregate counts and top-5 relief requests from the DB."""
    total_incidents = db.session.scalar(select(func.count(Incident.id))) or 0
    verified = db.session.scalar(
        select(func.count(Incident.id)).where(Incident.status == IncidentStatus.verified)
    ) or 0
    pending = db.session.scalar(
        select(func.count(Incident.id)).where(Incident.status == IncidentStatus.pending)
    ) or 0

    from backend.models.accessibility_result import AccessibilityResult
    isolated_villages = db.session.scalars(
        select(AccessibilityResult).where(AccessibilityResult.is_isolated == True)  # noqa: E712
    ).all()

    top_scores = db.session.scalars(
        select(PrioritizationScore)
        .order_by(PrioritizationScore.composite_score.desc())
        .limit(5)
    ).all()

    top_relief = []
    for ps in top_scores:
        relief = db.session.get(ReliefRequest, ps.relief_request_id)
        incident = db.session.get(Incident, relief.incident_id) if relief else None
        top_relief.append({
            "relief_id": ps.relief_request_id,
            "score": ps.composite_score,
            "category": relief.need_category.value if relief and relief.need_category else None,
            "location": incident.location_name if incident else None,
            "severity": incident.severity if incident else None,
        })

    return {
        "generated_at": datetime.now().isoformat(),
        "incident_counts": {
            "total": total_incidents,
            "verified": verified,
            "pending": pending,
        },
        "isolated_village_count": len(isolated_villages),
        "isolated_villages": [
            {"name": r.village.name if r.village else None, "id": r.village_id}
            for r in isolated_villages
        ],
        "top_relief_requests": top_relief,
    }


# ---------------------------------------------------------------------------
# Granite summary prompt
# ---------------------------------------------------------------------------

_SUMMARY_PROMPT = """\
You are a disaster-response coordinator assistant.
Write a concise situation summary (3–5 paragraphs) for a coordinator briefing \
based on the following data snapshot.  Be factual, specific, and actionable.

Data:
- Total incidents reported: {total_incidents}
- Verified incidents: {verified}
- Pending incidents: {pending}
- Isolated villages: {isolated_count}
{isolated_names}
- Top 5 relief priorities:
{top_relief}

Situation Summary:
"""


def _build_summary_prompt(snapshot: dict) -> str:
    isolated_names = ""
    if snapshot["isolated_village_count"] > 0:
        names = [v["name"] or f"village_id={v['id']}"
                 for v in snapshot["isolated_villages"]]
        isolated_names = "  Isolated: " + ", ".join(names)

    top_lines = []
    for i, r in enumerate(snapshot["top_relief_requests"], 1):
        top_lines.append(
            f"  {i}. {r['category'] or 'unknown'} at {r['location'] or 'unknown'}"
            f" (severity {r['severity'] or '?'}, score {r['score']:.3f})"
        )

    return _SUMMARY_PROMPT.format(
        total_incidents=snapshot["incident_counts"]["total"],
        verified=snapshot["incident_counts"]["verified"],
        pending=snapshot["incident_counts"]["pending"],
        isolated_count=snapshot["isolated_village_count"],
        isolated_names=isolated_names,
        top_relief="\n".join(top_lines) if top_lines else "  None",
    )


# ---------------------------------------------------------------------------
# HTML + PDF rendering
# ---------------------------------------------------------------------------

_BRIEFING_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>GeoResQ Situation Briefing — {date}</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 12pt; margin: 2cm; color: #111; }}
  h1 {{ font-size: 18pt; color: #1a3c6e; border-bottom: 2px solid #1a3c6e; padding-bottom: 6px; }}
  h2 {{ font-size: 14pt; color: #1a3c6e; margin-top: 24px; }}
  .disclaimer {{
    background: #fff3cd; border: 1px solid #ffc107;
    padding: 10px 14px; font-size: 10pt; margin-bottom: 20px;
    border-radius: 4px; color: #664d03;
  }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; font-size: 11pt; }}
  th {{ background: #f0f0f0; font-weight: bold; }}
  pre {{ background: #f8f8f8; padding: 10px; font-size: 10pt; border-radius: 4px; white-space: pre-wrap; }}
  .footer {{ font-size: 9pt; color: #888; border-top: 1px solid #ccc;
             margin-top: 40px; padding-top: 8px; text-align: center; }}
</style>
</head>
<body>

<h1>GeoResQ Situation Briefing</h1>
<p><strong>Generated:</strong> {date} &nbsp;|&nbsp;
   <strong>By:</strong> {author}</p>

<!-- DISCLAIMER — injected by template, not by LLM -->
<div class="disclaimer"><strong>DISCLAIMER:</strong> {disclaimer}</div>

<h2>Situation Summary</h2>
<pre>{summary}</pre>

<h2>Incident Overview</h2>
<table>
  <tr><th>Metric</th><th>Count</th></tr>
  <tr><td>Total incidents</td><td>{total_incidents}</td></tr>
  <tr><td>Verified</td><td>{verified}</td></tr>
  <tr><td>Pending review</td><td>{pending}</td></tr>
  <tr><td>Isolated villages</td><td>{isolated_count}</td></tr>
</table>

<h2>Top 5 Relief Priorities</h2>
<table>
  <tr><th>Rank</th><th>Category</th><th>Location</th><th>Severity</th><th>Score</th></tr>
  {relief_rows}
</table>

<div class="footer">Generated by GeoResQ · IBM Granite via watsonx.ai ·
This report is AI-assisted and requires human coordinator sign-off.</div>
</body>
</html>
"""


def _render_html(snapshot: dict, summary: str, author: str) -> str:
    relief_rows = ""
    for i, r in enumerate(snapshot["top_relief_requests"], 1):
        relief_rows += (
            f"<tr><td>{i}</td>"
            f"<td>{r['category'] or '—'}</td>"
            f"<td>{r['location'] or '—'}</td>"
            f"<td>{r['severity'] or '—'}</td>"
            f"<td>{r['score']:.3f}</td></tr>\n"
        )

    return _BRIEFING_HTML.format(
        date=snapshot["generated_at"][:19].replace("T", " "),
        author=author,
        disclaimer=DISCLAIMER,
        summary=summary,
        total_incidents=snapshot["incident_counts"]["total"],
        verified=snapshot["incident_counts"]["verified"],
        pending=snapshot["incident_counts"]["pending"],
        isolated_count=snapshot["isolated_village_count"],
        relief_rows=relief_rows or "<tr><td colspan='5'>No scored requests yet.</td></tr>",
    )


def _sanitize_fpdf_text(text: object) -> str:
    """Sanitize strings for fpdf2 standard Helvetica font (Latin-1)."""
    if text is None:
        return ""
    s = str(text)
    replacements = {
        "\u2014": "--",
        "\u2013": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "*",
        "\u2026": "...",
        "\xa0": " ",
    }
    for orig, repl in replacements.items():
        s = s.replace(orig, repl)
    return s.encode("latin-1", "replace").decode("latin-1")


def _export_pdf_fpdf2(snapshot: dict, summary: str, author: str, briefing_id: int) -> str | None:
    """Pure-Python PDF generator using fpdf2 (zero external C dependencies)."""
    try:
        from fpdf import FPDF
        pdf_dir = _get_pdf_dir()
        pdf_path = pdf_dir / f"briefing_{briefing_id}.pdf"

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Header
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(26, 60, 110)
        pdf.cell(text="GeoResQ Situation Briefing", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(80, 80, 80)
        date_str = str(snapshot.get("generated_at", ""))[:19].replace("T", " ")
        author_str = _sanitize_fpdf_text(author)
        pdf.cell(text=f"Generated: {date_str}  |  Author: {author_str}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # Non-removable disclaimer box
        pdf.set_fill_color(255, 243, 205)
        pdf.set_text_color(102, 77, 3)
        pdf.set_font("Helvetica", "B", 8)
        clean_disclaimer = _sanitize_fpdf_text(DISCLAIMER)
        pdf.multi_cell(w=0, h=4.5, text=clean_disclaimer, border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # Situation Summary
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(26, 60, 110)
        pdf.cell(text="Situation Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 30, 30)
        clean_summary = _sanitize_fpdf_text(summary)
        pdf.multi_cell(w=0, h=5, text=clean_summary, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        # Incident Overview Table
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(26, 60, 110)
        pdf.cell(text="Incident Overview", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        counts = snapshot.get("incident_counts", {})
        metrics = [
            ("Total incidents reported", str(counts.get("total", 0))),
            ("Verified incidents", str(counts.get("verified", 0))),
            ("Pending review", str(counts.get("pending", 0))),
            ("Isolated villages", str(snapshot.get("isolated_village_count", 0))),
        ]

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(110, 6, "Metric", border=1, fill=True)
        pdf.cell(50, 6, "Count", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 9)
        for metric, val in metrics:
            pdf.cell(110, 6, _sanitize_fpdf_text(metric), border=1)
            pdf.cell(50, 6, _sanitize_fpdf_text(val), border=1, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        # Top 5 Relief Priorities Table
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(26, 60, 110)
        pdf.cell(text="Top 5 Relief Priorities", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(12, 6, "#", border=1, fill=True)
        pdf.cell(38, 6, "Category", border=1, fill=True)
        pdf.cell(60, 6, "Location", border=1, fill=True)
        pdf.cell(24, 6, "Severity", border=1, fill=True)
        pdf.cell(26, 6, "Score", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 8.5)
        top_reqs = snapshot.get("top_relief_requests", [])
        if top_reqs:
            for i, r in enumerate(top_reqs, 1):
                pdf.cell(12, 5.5, str(i), border=1)
                pdf.cell(38, 5.5, _sanitize_fpdf_text(r.get("category") or "--")[:20], border=1)
                loc_txt = _sanitize_fpdf_text(r.get("location") or "--")[:28]
                pdf.cell(60, 5.5, loc_txt, border=1)
                pdf.cell(24, 5.5, _sanitize_fpdf_text(r.get("severity") or "--")[:12], border=1)
                score_str = f"{r.get('score', 0):.3f}"
                pdf.cell(26, 5.5, score_str, border=1, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.cell(160, 6, "No scored relief requests yet.", border=1, new_x="LMARGIN", new_y="NEXT")

        pdf.output(str(pdf_path))
        log.info("PDF exported via fpdf2: %s", pdf_path)
        return str(pdf_path)
    except Exception as exc:
        log.warning("fpdf2 export failed: %s", exc)
        return None


def _export_pdf(html: str, briefing_id: int, snapshot: dict | None = None, summary: str = "", author: str = "") -> str | None:
    """Write PDF and HTML to disk; returns relative path or None on failure."""
    pdf_dir = _get_pdf_dir()

    # Always persist HTML representation for web viewing / browser print
    try:
        html_path = pdf_dir / f"briefing_{briefing_id}.html"
        html_path.write_text(html, encoding="utf-8")
    except Exception as exc:
        log.warning("Saving HTML briefing failed: %s", exc)

    # Try WeasyPrint first
    try:
        from weasyprint import HTML as WP
        pdf_path = pdf_dir / f"briefing_{briefing_id}.pdf"
        WP(string=html).write_pdf(str(pdf_path))
        return str(pdf_path)
    except Exception as exc:
        log.info("WeasyPrint unavailable (%s) — falling back to pure-Python fpdf2", exc)

    # Fallback to fpdf2
    if snapshot is not None:
        return _export_pdf_fpdf2(snapshot, summary, author, briefing_id)
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_briefing(generated_by_id: int | None = None) -> Briefing:
    """Build snapshot → Granite summary → HTML → PDF → persist Briefing."""
    snapshot = _build_snapshot()
    prompt = _build_summary_prompt(snapshot)

    try:
        summary_text = generate(prompt, max_new_tokens=600, temperature=0.3)
    except WatsonxError as exc:
        log.warning("Granite briefing summary failed (%s) — using rule summary", exc)
        counts = snapshot.get("incident_counts", {})
        iso_c = snapshot.get("isolated_village_count", 0)
        summary_text = (
            f"[AI summary unavailable — automated overview]:\n\n"
            f"A total of {counts.get('total', 0)} incidents have been reported ({counts.get('verified', 0)} verified, "
            f"{counts.get('pending', 0)} pending review). "
            f"Currently, {iso_c} village(s) are cut off due to road blockages.\n\n"
            f"Emergency relief prioritization is active. Priority dispatch is recommended for water and medical aid "
            f"in isolated areas."
        )

    from backend.models.user import User
    author = "Coordinator"
    if generated_by_id:
        user = db.session.get(User, generated_by_id)
        if user:
            author = user.full_name

    # Persist (without PDF path first so we have the ID)
    briefing = Briefing(
        generated_by_id=generated_by_id,
        snapshot_json=snapshot,
        summary_text=summary_text,
    )
    db.session.add(briefing)
    db.session.commit()

    # Render + export PDF
    html = _render_html(snapshot, summary_text, author)
    pdf_path = _export_pdf(html, briefing.id, snapshot=snapshot, summary=summary_text, author=author)
    if pdf_path:
        briefing.pdf_path = pdf_path
        db.session.commit()

    log.info("Briefing %d generated by user %s (pdf=%s)", briefing.id, generated_by_id, briefing.pdf_path)
    return briefing
