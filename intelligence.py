"""
Intelligence brief generator and application drafter.

Phase 3: Monthly intelligence brief
Phase 4: Application/EOI drafting
"""
import json
import logging
import re
from datetime import datetime
from typing import Optional

import anthropic
import markdown as md_lib

from config import Config

logger = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> Optional[anthropic.Anthropic]:
    global _client
    if _client is None and Config.ANTHROPIC_API_KEY:
        _client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Monthly Intelligence Brief (Phase 3)
# ---------------------------------------------------------------------------

BRIEF_PROMPT = """You are writing a monthly funding intelligence brief for Wellington-region
community organisations in New Zealand.

This brief will be read by community trust managers, NGO coordinators, volunteer coordinators,
social workers, and community developers who need to understand where funding is flowing.
Write clean, professional prose — informed, analytical, no filler.

## DATA: Opportunities identified this month
{opportunities_json}

## DATA: Funder context
- Period: {period}
- Total opportunities found: {total_count}
- Grants: {grant_count}  |  Tenders/RFPs: {tender_count}
- NZ funders: {nz_count}  |  International: {intl_count}
- High fit (score 8+): {high_fit_count}

## YOUR TASK
Write a 1-2 page intelligence brief (800-1200 words) covering:

1. **What funders are prioritising this month** — patterns across sources, not just a list
2. **Language and framing appearing across multiple sources** — what terminology signals funder intent
3. **Gaps between stated priorities and visible ground-level need**
4. **Emerging opportunities worth watching** — anything building, shifting, or opening up
5. **Standout opportunities this month** — 2-3 specific grants/tenders worth close attention
   (reference them by funder name and grant name)

Format in clean Markdown with section headings. Do not use bullet points excessively —
prefer analytical prose. Write for an informed external reader, not internal notes."""


def generate_brief(opportunities: list, period: str = None) -> dict:
    """
    Generate a monthly intelligence brief from a list of Opportunity model instances.

    Returns dict with: title, content_md, content_html, period
    """
    if period is None:
        period = datetime.utcnow().strftime("%Y-%m")

    client = _get_client()

    # Summarise opportunities for the prompt
    opp_summaries = []
    for o in opportunities[:50]:  # cap to avoid token limits
        opp_summaries.append({
            "funder": o.funder_name,
            "grant": o.grant_name,
            "score": o.fit_score,
            "amount": o.amount_text or "not specified",
            "deadline": o.deadline_text or "not specified",
            "type": "tender" if o.is_tender else "grant",
            "country": _infer_country(o.source_id),
            "flags": {
                "requires_org": o.requires_org,
                "maori_edge": o.maori_edge,
                "school_edge": o.school_edge,
            },
            "justification": o.fit_justification or "",
        })

    grants = [o for o in opportunities if not o.is_tender]
    tenders = [o for o in opportunities if o.is_tender]
    nz_opps = [o for o in opportunities if _infer_country(o.source_id) == "NZ"]
    high_fit = [o for o in opportunities if (o.fit_score or 0) >= 8]

    if not client:
        logger.warning("No Anthropic API key — generating placeholder brief")
        content_md = _placeholder_brief(period, opportunities)
    else:
        try:
            prompt = BRIEF_PROMPT.format(
                opportunities_json=json.dumps(opp_summaries[:30], indent=2),
                period=period,
                total_count=len(opportunities),
                grant_count=len(grants),
                tender_count=len(tenders),
                nz_count=len(nz_opps),
                intl_count=len(opportunities) - len(nz_opps),
                high_fit_count=len(high_fit),
            )
            message = client.messages.create(
                model=Config.ANTHROPIC_MODEL,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            content_md = message.content[0].text.strip()
        except anthropic.APIError as e:
            logger.error(f"Brief generation failed: {e}")
            content_md = _placeholder_brief(period, opportunities)

    # Parse period for title
    try:
        dt = datetime.strptime(period, "%Y-%m")
        month_name = dt.strftime("%B %Y")
    except ValueError:
        month_name = period

    title = f"Funding Intelligence Brief — {month_name}"
    content_html = md_lib.markdown(content_md, extensions=["extra", "toc"])

    return {
        "period": period,
        "title": title,
        "content_md": content_md,
        "content_html": content_html,
        "opportunities_analysed": len(opportunities),
    }


def _infer_country(source_id: str) -> str:
    nz_sources = {
        # National NZ funders
        "creative_nz", "nz_on_air", "community_matters", "msd", "tpk",
        "tindall", "todd",
        # Wellington regional funders
        "wcc", "gwrc", "wct", "nikau", "hutt_city", "upper_hutt",
        "lion", "four_winds", "mangai_paho", "pacific_trust",
    }
    if source_id in nz_sources:
        return "NZ"
    return "International"


def _placeholder_brief(period: str, opportunities: list) -> str:
    """Generate a simple placeholder brief when Claude is unavailable."""
    try:
        dt = datetime.strptime(period, "%Y-%m")
        month_name = dt.strftime("%B %Y")
    except ValueError:
        month_name = period

    high_fit = sorted(
        [o for o in opportunities if (o.fit_score or 0) >= 8],
        key=lambda o: o.fit_score or 0,
        reverse=True,
    )[:5]

    lines = [
        f"# Funding Intelligence Brief — {month_name}",
        "",
        "*Note: This is an auto-generated summary. Set ANTHROPIC_API_KEY for full AI-written briefs.*",
        "",
        f"**{len(opportunities)} opportunities** identified this month across "
        f"{len(set(o.source_id for o in opportunities))} sources.",
        "",
        "## Standout Opportunities This Month",
        "",
    ]
    for o in high_fit:
        lines.append(f"- **{o.funder_name}** — {o.grant_name} (fit score: {o.fit_score:.0f}/10)")
        if o.fit_justification:
            lines.append(f"  _{o.fit_justification}_")
        lines.append("")

    lines += [
        "## Upcoming Deadlines",
        "",
    ]
    deadline_opps = sorted(
        [o for o in opportunities if o.deadline and (o.fit_score or 0) >= 6],
        key=lambda o: o.deadline,
    )[:8]
    for o in deadline_opps:
        lines.append(
            f"- **{o.deadline.strftime('%d %b %Y')}** — {o.funder_name}: {o.grant_name}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Application Drafter (Phase 4)
# ---------------------------------------------------------------------------

APPLICATION_PROMPT = """You are drafting a funding application or expression of interest for {org_name}.

## ORGANISATION PROFILE
{profile_summary}

## OPPORTUNITY
Funder: {funder_name}
Grant/Tender: {grant_name}
Description: {description}
Eligibility: {eligibility}
Amount: {amount}
Deadline: {deadline}
URL: {url}
Fit Score: {fit_score}/10 — {fit_justification}

## KEY FLAGS
- Requires organisational affiliation: {requires_org}
- Māori community focus is a competitive edge: {maori_edge}
- Community/youth focus is a competitive edge: {school_edge}

## TASK
Write a first-draft application or expression of interest in clean, professional Markdown.

Structure it appropriately for the opportunity type (grant application, EOI, proposal).
Use the most relevant aspects of the organisation's profile for this funder's stated priorities.

IMPORTANT:
- If requires_org is True: confirm organisational status and note any registration details.
- If maori_edge is True: foreground the organisation's kaupapa Māori relationships and
  culturally responsive practice.
- If school_edge is True: foreground the organisation's community and youth-facing work.
- Do not fabricate credentials. Flag with [VERIFY] where the organisation should check or add detail.
- Include a section: ## Notes for the Applicant — specific things to personalise or verify.

Word length: 600–1200 words (adjust for opportunity complexity)."""


def _build_app_profile_summary(profile: dict) -> str:
    """Build a narrative profile summary for application drafting prompts."""
    from scorer import _build_profile_summary
    return _build_profile_summary(profile)


def draft_application(opportunity, additional_notes: str = None) -> str:
    """
    Generate a first-draft application for an opportunity.

    Args:
        opportunity: Opportunity model instance
        additional_notes: Optional extra context from the applicant

    Returns:
        Markdown string of the draft application
    """
    client = _get_client()
    if not client:
        return _placeholder_application(opportunity)

    profile = Config.load_profile()
    org_name = profile.get("identity", {}).get("org_name", "the organisation")
    profile_summary = _build_app_profile_summary(profile)
    if additional_notes:
        profile_summary += f"\n\nAdditional context from applicant: {additional_notes}"

    try:
        prompt = APPLICATION_PROMPT.format(
            org_name=org_name,
            profile_summary=profile_summary,
            funder_name=opportunity.funder_name,
            grant_name=opportunity.grant_name,
            description=(opportunity.description or "")[:1500],
            eligibility=(opportunity.eligibility_summary or "")[:800],
            amount=opportunity.amount_text or "not specified",
            deadline=opportunity.deadline_text or "not specified",
            url=opportunity.url,
            fit_score=opportunity.fit_score or "N/A",
            fit_justification=opportunity.fit_justification or "not scored",
            requires_org="YES — confirm organisational status" if opportunity.requires_org else "No",
            maori_edge="YES — foreground kaupapa Māori relationships and culturally responsive practice" if opportunity.maori_edge else "No",
            school_edge="YES — foreground community and youth-facing work" if opportunity.school_edge else "No",
        )

        message = client.messages.create(
            model=Config.ANTHROPIC_MODEL,
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    except anthropic.APIError as e:
        logger.error(f"Application drafting failed: {e}")
        return _placeholder_application(opportunity)


def _placeholder_application(opportunity) -> str:
    try:
        profile = Config.load_profile()
        org_name = profile.get("identity", {}).get("org_name", "Your Organisation")
        focus_areas = ", ".join(profile.get("identity", {}).get("focus_areas", []))
    except Exception:
        org_name = "Your Organisation"
        focus_areas = ""

    return f"""# Application Draft — {opportunity.grant_name}
**Funder:** {opportunity.funder_name}
**Applicant:** {org_name}
**Amount:** {opportunity.amount_text or 'not specified'}
**Deadline:** {opportunity.deadline_text or 'not specified'}

---

*Set ANTHROPIC_API_KEY to generate a full AI-drafted application.*

## Key Points to Cover

- {org_name}'s mission and track record in the community
{f"- Focus areas: {focus_areas}" if focus_areas else ""}
{"- **NOTE: This opportunity requires organisational affiliation — confirm registration status.**" if opportunity.requires_org else ""}
{"- Foreground kaupapa Māori relationships and culturally responsive practice" if opportunity.maori_edge else ""}
{"- Foreground community and youth-facing work" if opportunity.school_edge else ""}

## Notes for the Applicant
- [VERIFY] Check eligibility criteria match your organisation's registration and structure
- [ADD] Specific outcomes data and evidence of community impact
- [ADD] Any letters of support from community partners or stakeholders
- Review the funder's stated priorities at: {opportunity.url}
"""
