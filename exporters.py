"""
Export opportunities and briefs to Markdown or PDF.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import markdown as md_lib

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------

def opportunity_to_markdown(opp) -> str:
    """Convert a single Opportunity instance to Markdown."""
    flags = []
    if opp.requires_org:
        flags.append("⚠️ **Requires organisational affiliation** — consider partnership")
    if opp.maori_edge:
        flags.append("✅ **Maori community experience gives competitive edge**")
    if opp.school_edge:
        flags.append("✅ **School-based background gives competitive edge**")
    if opp.requires_registration:
        flags.append("⚠️ **Requires full registration** (working toward NZAC)")
    if opp.requires_maori_fluency:
        flags.append("⚠️ **Requires Te Reo fluency** (George has developing proficiency)")
    if opp.high_value:
        flags.append("💰 **High-value opportunity** (>$50k)")

    deadline_str = ""
    if opp.deadline:
        days = opp.days_until_deadline
        if days is not None:
            deadline_str = f"{opp.deadline.strftime('%d %B %Y')} ({days} days)"
        else:
            deadline_str = opp.deadline.strftime("%d %B %Y")
    elif opp.deadline_text:
        deadline_str = opp.deadline_text

    amount_str = opp.amount_text or "Not specified"

    lines = [
        f"# {opp.grant_name}",
        f"**Funder:** {opp.funder_name}",
        f"**Type:** {'Tender / RFP' if opp.is_tender else 'Grant / Funding'}",
        f"**Amount:** {amount_str}",
        f"**Deadline:** {deadline_str or 'Not specified'}",
        f"**URL:** {opp.url}",
        f"**Fit Score:** {opp.fit_score:.0f}/10" if opp.fit_score else "**Fit Score:** Not scored",
        f"**Status:** {opp.status_label}",
        "",
    ]

    if flags:
        lines += ["## Flags", ""] + flags + [""]

    if opp.fit_justification:
        lines += ["## Fit Assessment", "", opp.fit_justification, ""]

    if opp.relevance_paragraph:
        lines += ["## Relevance to Your Work", "", opp.relevance_paragraph, ""]

    if opp.eligibility_summary:
        lines += ["## Eligibility Summary", "", opp.eligibility_summary, ""]

    if opp.description:
        lines += ["## Description", "", opp.description[:1000], ""]

    if opp.notes:
        lines += ["## Your Notes", "", opp.notes, ""]

    lines += [
        f"*First seen: {opp.first_seen.strftime('%d %b %Y') if opp.first_seen else 'unknown'}*",
        f"*Last updated: {opp.updated_at.strftime('%d %b %Y') if opp.updated_at else 'unknown'}*",
    ]

    return "\n".join(lines)


def export_opportunities_markdown(opportunities: list, title: str = None) -> str:
    """Export a list of opportunities to a single Markdown document."""
    if title is None:
        title = f"Opportunity List — {datetime.utcnow().strftime('%B %Y')}"

    lines = [
        f"# {title}",
        f"*Generated: {datetime.utcnow().strftime('%d %B %Y %H:%M')} UTC*",
        f"*Opportunities: {len(opportunities)}*",
        "",
        "---",
        "",
    ]

    for opp in opportunities:
        lines.append(opportunity_to_markdown(opp))
        lines.append("\n---\n")

    return "\n".join(lines)


def export_brief_markdown(brief) -> str:
    """Export a Brief instance as Markdown."""
    return f"# {brief.title}\n\n{brief.content_md}"


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

def export_to_pdf(markdown_content: str, output_path: str) -> bool:
    """
    Convert Markdown to PDF using fpdf2.

    Returns True on success, False on failure.
    """
    try:
        from fpdf import FPDF

        html_content = md_lib.markdown(markdown_content, extensions=["extra"])

        pdf = FPDF()
        pdf.add_page()

        # Use built-in font (UTF-8 support limited — for full Unicode use a TTF font)
        pdf.set_font("Helvetica", size=11)
        pdf.set_auto_page_break(auto=True, margin=15)

        # Strip HTML tags for plain-text PDF rendering
        import re
        text = re.sub(r"<[^>]+>", "", html_content)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')

        # Write as multi-cell paragraphs
        for paragraph in text.split("\n\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                pdf.ln(4)
                continue
            # Detect headings (lines starting with #)
            if paragraph.startswith("# "):
                pdf.set_font("Helvetica", "B", 16)
                pdf.multi_cell(0, 8, paragraph.lstrip("# ").strip())
                pdf.set_font("Helvetica", size=11)
            elif paragraph.startswith("## "):
                pdf.set_font("Helvetica", "B", 13)
                pdf.multi_cell(0, 7, paragraph.lstrip("# ").strip())
                pdf.set_font("Helvetica", size=11)
            elif paragraph.startswith("### "):
                pdf.set_font("Helvetica", "B", 11)
                pdf.multi_cell(0, 6, paragraph.lstrip("# ").strip())
                pdf.set_font("Helvetica", size=11)
            else:
                # Replace unicode chars that fpdf2 can't handle in built-in fonts
                paragraph = (
                    paragraph.replace("\u2014", "--")
                    .replace("\u2013", "-")
                    .replace("\u2019", "'")
                    .replace("\u2018", "'")
                    .replace("\u201c", '"')
                    .replace("\u201d", '"')
                    .replace("\u00e2", "a")
                    .replace("\u0101", "a")
                    .replace("\u016b", "u")
                    .replace("\u014d", "o")
                )
                pdf.multi_cell(0, 6, paragraph)
            pdf.ln(2)

        pdf.output(output_path)
        logger.info(f"PDF exported to {output_path}")
        return True

    except Exception as e:
        logger.error(f"PDF export failed: {e}")
        return False


def export_opportunity_pdf(opportunity, output_dir: str = None) -> Optional[str]:
    """Export a single opportunity as PDF. Returns file path or None."""
    from config import Config
    output_dir = output_dir or str(Config.DATA_DIR)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        c for c in opportunity.grant_name[:50] if c.isalnum() or c in " -_"
    ).strip().replace(" ", "_")
    filename = f"opportunity_{opportunity.id}_{safe_name}.pdf"
    output_path = str(Path(output_dir) / filename)

    md_content = opportunity_to_markdown(opportunity)
    if export_to_pdf(md_content, output_path):
        return output_path
    return None


def export_brief_pdf(brief, output_dir: str = None) -> Optional[str]:
    """Export a brief as PDF. Returns file path or None."""
    from config import Config
    output_dir = output_dir or str(Config.DATA_DIR)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    filename = f"brief_{brief.period}.pdf"
    output_path = str(Path(output_dir) / filename)

    md_content = export_brief_markdown(brief)
    if export_to_pdf(md_content, output_path):
        return output_path
    return None
