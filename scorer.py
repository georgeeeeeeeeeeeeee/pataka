"""
Fit scoring engine.

Scores each opportunity 1-10 against the organisation profile (profile.json).
Uses Claude for nuanced base scoring, then applies deterministic B8 rule adjustments.
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import anthropic

from config import Config

logger = logging.getLogger(__name__)

# Loaded once at module level
_profile: dict = None
_client: Optional[anthropic.Anthropic] = None


def _get_profile() -> dict:
    global _profile
    if _profile is None:
        _profile = Config.load_profile()
    return _profile


def _get_client() -> Optional[anthropic.Anthropic]:
    global _client
    if _client is None and Config.ANTHROPIC_API_KEY:
        _client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Flag detection (deterministic, keyword-based)
# ---------------------------------------------------------------------------

ORG_REQUIRED_PATTERNS = [
    r"(?:must|to) be (?:a|an) (?:registered )?(?:organisation|organization|charity|incorporated|trust|NGO)",
    r"organisations? only",
    r"not available to individuals",
    r"applicants? (?:must be|to be) (?:a|an) (?:legal entity|body corporate|registered)",
    r"charitable trust required",
    r"must have (?:a|an) (?:NZBN|IRD number as an organisation)",
    r"registered as (?:a|an) (?:charity|not.for.profit|NFP)",
    r"open to (?:registered )?(?:organisations?|charities|trusts|NGOs)",
    r"applicant must be an? (?:organisation|entity|trust)",
]

REGISTRATION_REQUIRED_PATTERNS = [
    r"must be (?:a )?(?:fully )?registered (?:counsellor|psychologist|social worker|therapist)",
    r"(?:full|fully) (?:NZAC|ACA|PACFA|MNZAC) (?:member|registration|membership)",
    r"requires (?:full )?(?:NZAC|ACA|PACFA|MNZAC) (?:member|registration|membership)",
    r"(?:NZAC|ACA|PACFA|MNZAC) (?:full )?members? only",
    r"applicants must be (?:fully )?(?:NZAC|ACA|PACFA|registered)",
    r"current (?:practising certificate|APC)",
    r"registered health professional",
    r"clinical registration required",
    r"registered (?:counsellor|psychologist|social worker)",
]

MAORI_FLUENCY_PATTERNS = [
    r"te reo m[aā]ori (?:fluency|proficiency|speaker|speaking)",
    r"fluent in te reo",
    r"m[aā]ori language (?:fluency|skills|proficiency)",
    r"native.level te reo",
    r"conversational te reo",
]

MAORI_COMMUNITY_PATTERNS = [
    r"m[aā]ori",
    r"kaupapa m[aā]ori",
    r"te ao m[aā]ori",
    r"iwi",
    r"hap[uū]",
    r"whānau|whanau",
    r"treaty",
    r"tangata whenua",
    r"indigenous.*new zealand",
    r"m[aā]ori health",
    r"m[aā]ori community",
    r"m[aā]ori development",
]

SCHOOL_PATTERNS = [
    r"school",
    r"secondary",
    r"intermediate",
    r"kura",
    r"education sector",
    r"teacher",
    r"student",
    r"young person",
    r"adolescent",
    r"youth",
    r"guidance counsellor",
    r"school counsellor",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    for p in patterns:
        if re.search(p, text, re.I):
            return True
    return False


def detect_flags(opp_text: str) -> dict:
    """Return a dict of boolean flags derived from opportunity text."""
    return {
        "requires_org": _matches_any(opp_text, ORG_REQUIRED_PATTERNS),
        "requires_registration": _matches_any(opp_text, REGISTRATION_REQUIRED_PATTERNS),
        "requires_maori_fluency": _matches_any(opp_text, MAORI_FLUENCY_PATTERNS),
        "maori_edge": _matches_any(opp_text, MAORI_COMMUNITY_PATTERNS),
        "school_edge": _matches_any(opp_text, SCHOOL_PATTERNS),
    }


# ---------------------------------------------------------------------------
# Claude-based base scoring
# ---------------------------------------------------------------------------

SCORING_PROMPT = """You are scoring a funding opportunity for a specific organisation.

## ORGANISATION PROFILE (Ground Truth)
{profile_summary}

## OPPORTUNITY
Funder: {funder_name}
Grant/Tender: {grant_name}
Description: {description}
Eligibility: {eligibility}
URL: {url}

## YOUR TASK
Score this opportunity 1-10 for fit with this organisation. Use these tiers:
- 8-10: Direct match — the organisation's demonstrated experience, current work, or stated competencies directly address what the funder is seeking
- 5-7: Adjacent — relevant but requires some stretch, partnership, or framing; the organisation could make a compelling case
- 1-4: Tangential — wrong sector, requires credentials not held, or the connection is too weak to justify pursuing

Be specific. Consider ALL competency domains listed in the profile. Do not underweight any domain.

Respond with ONLY valid JSON (no markdown, no commentary):
{{
  "base_score": <integer 1-10>,
  "justification": "<one concise sentence explaining the score>",
  "relevance_paragraph": "<2-3 sentences explaining relevance to this organisation's specific work>",
  "eligibility_issues": "<any eligibility concerns or null>",
  "primary_competency_match": "<which competency area is the strongest match>"
}}"""


def _build_profile_summary(profile: dict) -> str:
    """Build a profile summary string from the loaded org profile for use in prompts."""
    identity = profile.get("identity", {})
    org_name = identity.get("org_name", "Organisation")
    org_type = identity.get("org_type", "community organisation")
    region = identity.get("region", identity.get("location", "Wellington, NZ"))
    focus_areas = ", ".join(identity.get("focus_areas", []))
    registration = identity.get("registration", "")
    budget = identity.get("annual_budget_range", "")

    lines = [f"{org_name} | {region}", f"Type: {org_type}"]
    if focus_areas:
        lines.append(f"Focus areas: {focus_areas}")
    if registration:
        lines.append(f"Registration: {registration}")
    if budget:
        lines.append(f"Annual budget range: {budget}")

    impact = profile.get("demonstrated_impact", {})
    if impact:
        lines.append("DEMONSTRATED IMPACT:")
        for k, v in impact.items():
            if k.startswith("_"):
                continue  # skip template instruction keys
            if isinstance(v, list) and v:
                lines.append(f"  {k.replace('_', ' ')}: {', '.join(str(x) for x in v)}")
            elif v:
                lines.append(f"  {k.replace('_', ' ')}: {v}")

    competencies = profile.get("competencies", {})
    if competencies:
        lines.append("COMPETENCIES:")
        idx = 1
        for comp_name, comp in competencies.items():
            if comp_name.startswith("_") or not isinstance(comp, dict):
                continue  # skip template instruction keys
            evidence = comp.get("evidence", "")
            display_name = comp_name.replace("_", " ").title()
            lines.append(f"{idx}. {display_name}" + (f" — {evidence}" if evidence else ""))
            idx += 1

    notes = profile.get("notes", {})
    if notes:
        for k, v in notes.items():
            if k.startswith("_"):
                continue
            if v:
                lines.append(f"{k.replace('_', ' ').upper()}: {v}")

    return "\n".join(lines)


def _get_profile_summary() -> str:
    return _build_profile_summary(_get_profile())


def _is_registered_org() -> bool:
    """
    Return True if the loaded profile represents a registered organisation
    (charitable trust, incorporated society, iwi, etc.) rather than an individual.
    Used to skip the requires_org penalty — an org-affiliation requirement is not
    a constraint for a registered organisation.
    """
    identity = _get_profile().get("identity", {})
    entity_type = identity.get("entity_type", "").lower()
    return any(
        t in entity_type
        for t in ("organisation", "trust", "society", "incorporated", "iwi", "charity", "ngo")
    )


def score_opportunity(opp_data: dict, warm_contact: bool = False) -> dict:
    """
    Score an opportunity against the loaded org profile.

    Args:
        opp_data: dict with keys: funder_name, grant_name, description,
                  eligibility_summary, url, is_tender
        warm_contact: True if there's a warm contact at this funder

    Returns:
        dict with: score, base_score, justification, relevance_paragraph,
                   requires_org, maori_edge, school_edge, requires_registration,
                   requires_maori_fluency, score_breakdown
    """
    # Combine all text for flag detection
    combined_text = " ".join(filter(None, [
        opp_data.get("grant_name", ""),
        opp_data.get("description", ""),
        opp_data.get("eligibility_summary", ""),
        opp_data.get("funder_name", ""),
    ]))

    flags = detect_flags(combined_text)

    # Try Claude for base score
    base_score, justification, relevance_paragraph = _get_claude_score(opp_data)

    # Apply B8 adjustments
    score = base_score
    adjustments = []

    if flags["maori_edge"]:
        score += 1
        adjustments.append({"reason": "Maori community experience gives competitive edge", "delta": +1})

    if flags["school_edge"]:
        score += 1
        adjustments.append({"reason": "School-based background directly relevant", "delta": +1})

    if warm_contact:
        score += 1
        adjustments.append({"reason": "Warm contact at this funder", "delta": +1})

    if flags["requires_registration"]:
        score -= 1
        adjustments.append({"reason": "Requires full clinical registration", "delta": -1})

    if flags["requires_org"] and not _is_registered_org():
        score -= 2
        adjustments.append({"reason": "Requires organisational affiliation", "delta": -2})

    if flags["requires_maori_fluency"]:
        score -= 1
        adjustments.append({"reason": "Requires Te Reo fluency", "delta": -1})

    # Clamp to 1–10
    score = max(1, min(10, round(score)))

    return {
        "score": score,
        "base_score": base_score,
        "justification": justification,
        "relevance_paragraph": relevance_paragraph,
        "requires_org": flags["requires_org"],
        "maori_edge": flags["maori_edge"],
        "school_edge": flags["school_edge"],
        "requires_registration": flags["requires_registration"],
        "requires_maori_fluency": flags["requires_maori_fluency"],
        "score_breakdown": json.dumps({
            "base_score": base_score,
            "adjustments": adjustments,
            "final_score": score,
        }),
    }


def _get_claude_score(opp_data: dict) -> tuple[int, str, str]:
    """
    Use Claude to score an opportunity. Falls back to keyword scoring if API unavailable.
    Returns (base_score, justification, relevance_paragraph).
    """
    client = _get_client()
    if not client:
        logger.warning("No Anthropic API key — using keyword-based scoring fallback")
        return _keyword_score(opp_data)

    try:
        prompt = SCORING_PROMPT.format(
            profile_summary=_get_profile_summary(),
            funder_name=opp_data.get("funder_name", "Unknown"),
            grant_name=opp_data.get("grant_name", "Unknown"),
            description=(opp_data.get("description") or "")[:1500],
            eligibility=(opp_data.get("eligibility_summary") or "")[:800],
            url=opp_data.get("url", ""),
        )

        message = client.messages.create(
            model=Config.ANTHROPIC_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)

        base_score = max(1, min(10, int(result.get("base_score", 5))))
        justification = result.get("justification", "")
        relevance_paragraph = result.get("relevance_paragraph", "")

        return base_score, justification, relevance_paragraph

    except (json.JSONDecodeError, KeyError, anthropic.APIError) as e:
        logger.warning(f"Claude scoring failed: {e} — falling back to keyword scoring")
        return _keyword_score(opp_data)


def _keyword_score(opp_data: dict) -> tuple[int, str, str]:
    """
    Fallback keyword-based scoring when Claude is unavailable.
    Returns (base_score, justification, relevance_paragraph).
    """
    profile = _get_profile()
    combined = " ".join(filter(None, [
        opp_data.get("grant_name", ""),
        opp_data.get("description", ""),
        opp_data.get("eligibility_summary", ""),
        opp_data.get("funder_name", ""),
    ])).lower()

    score = 2  # default low
    matched_competencies = []

    for comp_name, comp in profile.get("competencies", {}).items():
        keywords = comp.get("keywords", [])
        weight = comp.get("weight", 5)
        matches = sum(1 for kw in keywords if kw.lower() in combined)
        if matches >= 2:
            score += min(3, matches)
            matched_competencies.append(comp_name)
        elif matches == 1:
            score += 1
            matched_competencies.append(comp_name)

    # Check funder keywords
    funding_keywords = profile.get("funding_keywords", [])
    kw_matches = sum(1 for kw in funding_keywords if kw.lower() in combined)
    score += min(2, kw_matches // 2)

    score = max(1, min(10, score))
    comp_list = ", ".join(matched_competencies[:3]) if matched_competencies else "general"
    justification = f"Keyword match across: {comp_list}."
    relevance_paragraph = (
        f"This opportunity aligns with the organisation's work in {comp_list}. "
        "Review the full description to assess fit more precisely."
    )
    return score, justification, relevance_paragraph


def score_batch(opp_data_list: list[dict], warm_contact_orgs: list[str] = None) -> list[dict]:
    """Score a batch of opportunities."""
    warm_orgs = set(o.lower() for o in (warm_contact_orgs or []))
    results = []
    for opp in opp_data_list:
        warm = opp.get("funder_name", "").lower() in warm_orgs
        result = score_opportunity(opp, warm_contact=warm)
        result["opportunity_id"] = opp.get("id")
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Qualification stage — combined qualify + score in one Claude call
# ---------------------------------------------------------------------------


@dataclass
class QualifiedOpportunity:
    """
    A scraped opportunity that has passed qualification gates and been scored.
    Python-only dataclass — not persisted directly; values are unpacked into
    Opportunity model fields by the scheduler.
    """
    # ScrapedOpportunity fields
    source_id: str = ""
    funder_name: str = ""
    grant_name: str = ""
    url: str = ""
    is_tender: bool = False
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    amount_text: Optional[str] = None
    deadline: Optional[datetime] = None
    deadline_text: Optional[str] = None
    open_date: Optional[datetime] = None
    eligibility_summary: Optional[str] = None
    description: Optional[str] = None
    raw_html: Optional[str] = None
    # Scoring result fields
    score: int = 5
    base_score: int = 5
    justification: str = ""
    relevance_paragraph: str = ""
    requires_org: bool = False
    maori_edge: bool = False
    school_edge: bool = False
    requires_registration: bool = False
    requires_maori_fluency: bool = False
    score_breakdown: Optional[str] = None
    # Qualification metadata
    qualification_note: str = ""

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "funder_name": self.funder_name,
            "grant_name": self.grant_name,
            "url": self.url,
            "is_tender": self.is_tender,
            "amount_min": self.amount_min,
            "amount_max": self.amount_max,
            "amount_text": self.amount_text,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "deadline_text": self.deadline_text,
            "open_date": self.open_date.isoformat() if self.open_date else None,
            "eligibility_summary": self.eligibility_summary,
            "description": self.description,
            "qualification_note": self.qualification_note,
        }


QUALIFICATION_AND_SCORING_PROMPT = """You are a qualification and scoring engine for a grant/tender discovery system.
Today's date is {today}.

## TASK
Analyse the opportunity text below. Complete TWO stages.

### STAGE 1 — QUALIFICATION GATES
Check each gate in order:
1. **gate_specific_round**: Is this a SPECIFIC, named funding round with its own eligibility criteria and application process? (Not a generic "we fund things" landing page, not a past/archived/closed round.)
2. **gate_deadline**: Does this round have an open deadline that falls within 90 days from today ({today})? Parse any date strings you find.
3. **gate_amount**: Is there a SPECIFIC dollar amount stated — either a fixed grant, a range, or an "up to" figure?
4. **gate_sole_practitioner**: Can a sole practitioner (an individual, not an organisation) apply — either directly, or via a clearly described partnership/fiscal-sponsorship pathway?

If the page looks like a funder landing page that lists multiple rounds (rather than a single round itself), set `is_landing_page: true` and extract up to 4 sub-round URLs from the page text.

### STAGE 2 — SCORING (only if all four gates pass)
Score 1–10 for fit with this practitioner:
{profile_summary}

Score tiers:
- 8–10: Direct match — practitioner's demonstrated experience directly addresses what the funder seeks
- 5–7: Adjacent — relevant but requires some stretch, partnership, or framing
- 1–4: Tangential — wrong sector, credentials not held, or connection too weak to justify pursuing

## OPPORTUNITY
Funder: {funder_name}
Name: {grant_name}
URL: {url}
Text:
{page_text}

## RESPONSE
Respond with ONLY valid JSON (no markdown, no commentary):
{{
  "is_landing_page": <true|false>,
  "sub_round_urls": [<up to 4 URL strings, only if is_landing_page=true, else empty list>],
  "gate_specific_round": <true|false>,
  "gate_deadline": <true|false>,
  "gate_deadline_parsed": "<ISO date string e.g. 2026-04-15, or null>",
  "gate_amount": <true|false>,
  "gate_amount_parsed": "<e.g. '$5,000 – $20,000' or null>",
  "gate_sole_practitioner": <true|false>,
  "qualified": <true if all four gates pass, false otherwise>,
  "disqualification_reason": "<brief reason if not qualified, or null>",
  "base_score": <integer 1-10, or null if not qualified>,
  "justification": "<one concise sentence, or null if not qualified>",
  "relevance_paragraph": "<2-3 sentences for the practitioner to read, or null if not qualified>"
}}"""


def _pre_filter(s_opp) -> tuple[bool, str]:
    """
    Fast pre-filter without any API calls.

    Returns:
        (True, "gets_fast_path") — GETS tender with deadline within 90 days, skip qualification
        (True, reason)           — rejected, caller should return None
        (False, "")              — continue to full qualification
    """
    name_url = ((s_opp.grant_name or "") + " " + (s_opp.url or "")).lower()
    for kw in ("closed", "archived", "historic", "past grants", "awarded"):
        if kw in name_url:
            return True, f"keyword '{kw}' in name/url"

    now = datetime.utcnow()
    if s_opp.deadline and s_opp.deadline < now:
        return True, "deadline already past"

    # GETS fast path: tender with deadline already parsed and within 90 days
    if s_opp.is_tender and s_opp.deadline:
        days_until = (s_opp.deadline - now).days
        if 0 <= days_until <= 90:
            return True, "gets_fast_path"

    return False, ""


def _parse_amount_inline(amount_text: str) -> tuple[Optional[float], Optional[float]]:
    """Replicate BaseScraper.parse_amount without requiring an instance."""
    text = amount_text.replace(",", "").replace("\u2013", "-").replace("\u2014", "-")
    nums = re.findall(r"\$?\s*(\d+(?:\.\d+)?)\s*(?:k|K)?", text)
    amounts = []
    for n in nums:
        val = float(n)
        idx = text.find(n)
        if idx >= 0 and idx + len(n) < len(text):
            suffix = text[idx + len(n): idx + len(n) + 1].strip().lower()
            if suffix == "k":
                val *= 1000
        amounts.append(val)
    if not amounts:
        return None, None
    if len(amounts) == 1:
        if "up to" in amount_text.lower() or "maximum" in amount_text.lower():
            return None, amounts[0]
        return amounts[0], amounts[0]
    return min(amounts), max(amounts)


def _build_qualified_opp(s_opp, score_result: dict, qualification_note: str) -> QualifiedOpportunity:
    """Assemble a QualifiedOpportunity from a ScrapedOpportunity and a scoring result dict."""
    return QualifiedOpportunity(
        source_id=s_opp.source_id,
        funder_name=s_opp.funder_name,
        grant_name=s_opp.grant_name,
        url=s_opp.url,
        is_tender=s_opp.is_tender,
        amount_min=s_opp.amount_min,
        amount_max=s_opp.amount_max,
        amount_text=s_opp.amount_text,
        deadline=s_opp.deadline,
        deadline_text=s_opp.deadline_text,
        open_date=s_opp.open_date,
        eligibility_summary=s_opp.eligibility_summary,
        description=s_opp.description,
        raw_html=s_opp.raw_html,
        score=score_result["score"],
        base_score=score_result["base_score"],
        justification=score_result["justification"],
        relevance_paragraph=score_result.get("relevance_paragraph", ""),
        requires_org=score_result["requires_org"],
        maori_edge=score_result["maori_edge"],
        school_edge=score_result["school_edge"],
        requires_registration=score_result["requires_registration"],
        requires_maori_fluency=score_result["requires_maori_fluency"],
        score_breakdown=score_result.get("score_breakdown"),
        qualification_note=qualification_note,
    )


def _fetch_and_build_sub_opp(url: str, parent_opp, fetch_fn) -> Optional[object]:
    """
    Fetch a sub-round URL and return a ScrapedOpportunity built from its content.
    Returns None on any failure or domain mismatch.
    """
    from urllib.parse import urlparse
    from scrapers.base import ScrapedOpportunity

    if not url or not url.startswith("http"):
        return None

    # Domain guard — only follow URLs on the same domain as the parent
    parent_domain = urlparse(parent_opp.url).netloc
    sub_domain = urlparse(url).netloc
    if parent_domain and sub_domain and parent_domain != sub_domain:
        logger.debug(f"Sub-URL domain mismatch: {sub_domain} vs {parent_domain} — skipping")
        return None

    if not fetch_fn:
        return None

    html = fetch_fn(url)
    if not html:
        return None

    try:
        from bs4 import BeautifulSoup
        from dateutil import parser as date_parser

        soup = BeautifulSoup(html, "lxml")

        # Title from h1 or <title>
        h1 = soup.find("h1")
        title_tag = soup.find("title")
        if h1:
            title = re.sub(r"\s+", " ", h1.get_text()).strip()
        elif title_tag:
            title = re.sub(r"\s+", " ", title_tag.get_text()).strip()
        else:
            title = f"{parent_opp.funder_name} — Grant Round"

        # Description from main/article/body (prefer main)
        content = soup.find("main") or soup.find("article") or soup.find("body")
        if content:
            for tag in content(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            description = re.sub(r"\s+", " ", content.get_text(" ")).strip()[:2500]
        else:
            description = ""

        opp = ScrapedOpportunity()
        opp.source_id = parent_opp.source_id
        opp.funder_name = parent_opp.funder_name
        opp.is_tender = parent_opp.is_tender
        opp.grant_name = title[:400]
        opp.url = url
        opp.description = description

        # Extract amount using the same pattern as nz_funders.py
        amount_match = re.search(
            r"(\$[\d,]+(?:\s*[–\-]\s*\$[\d,]+)?|\bup to \$[\d,]+)", description, re.I
        )
        if amount_match:
            opp.amount_text = amount_match.group(0)
            opp.amount_min, opp.amount_max = _parse_amount_inline(opp.amount_text)

        # Extract deadline using the same pattern as nz_funders.py
        deadline_match = re.search(
            r"(?:closes?|deadline|open until|applications? close)[:\s]+([^\n.]{5,40})",
            description, re.I,
        )
        if deadline_match:
            opp.deadline_text = deadline_match.group(1).strip()
            try:
                opp.deadline = date_parser.parse(opp.deadline_text, dayfirst=True)
            except Exception:
                pass

        return opp

    except Exception as e:
        logger.warning(f"Failed to parse sub-opp from {url}: {e}")
        return None


def _keyword_fallback_qualify(s_opp, warm_contact: bool = False) -> Optional[list]:
    """
    No-API fallback qualification.
    Passes only if deadline is within 90 days AND a dollar amount is set.
    Scores via keyword matching.
    Returns a list with one QualifiedOpportunity, or None.
    """
    now = datetime.utcnow()
    if not (s_opp.deadline and 0 <= (s_opp.deadline - now).days <= 90):
        return None
    if not (s_opp.amount_min or s_opp.amount_max):
        return None

    opp_data = {
        "funder_name": s_opp.funder_name,
        "grant_name": s_opp.grant_name,
        "description": s_opp.description,
        "eligibility_summary": s_opp.eligibility_summary,
        "url": s_opp.url,
    }
    base_score, justification, relevance_paragraph = _keyword_score(opp_data)

    combined_text = " ".join(filter(None, [
        s_opp.grant_name, s_opp.description, s_opp.eligibility_summary, s_opp.funder_name,
    ]))
    flags = detect_flags(combined_text)

    score = base_score
    adjustments = []
    if flags["maori_edge"]:
        score += 1
        adjustments.append({"reason": "Maori community experience gives competitive edge", "delta": +1})
    if flags["school_edge"]:
        score += 1
        adjustments.append({"reason": "School-based background directly relevant", "delta": +1})
    if warm_contact:
        score += 1
        adjustments.append({"reason": "Warm contact at this funder", "delta": +1})
    if flags["requires_registration"]:
        score -= 1
        adjustments.append({"reason": "Requires full clinical registration", "delta": -1})
    if flags["requires_org"] and not _is_registered_org():
        score -= 2
        adjustments.append({"reason": "Requires organisational affiliation", "delta": -2})
    if flags["requires_maori_fluency"]:
        score -= 1
        adjustments.append({"reason": "Requires Te Reo fluency", "delta": -1})
    score = max(1, min(10, round(score)))

    score_result = {
        "score": score,
        "base_score": base_score,
        "justification": justification,
        "relevance_paragraph": relevance_paragraph,
        **flags,
        "score_breakdown": json.dumps({
            "base_score": base_score,
            "adjustments": adjustments,
            "final_score": score,
        }),
    }
    return [_build_qualified_opp(s_opp, score_result, "keyword_fallback")]


def qualify_and_score(
    s_opp,
    warm_contact: bool = False,
    fetch_fn=None,
    depth: int = 0,
) -> Optional[list]:
    """
    Qualify and score a scraped opportunity in a single Claude call.

    Args:
        s_opp:       ScrapedOpportunity from a scraper
        warm_contact: True if there's a warm contact at this funder
        fetch_fn:    Callable(url) -> Optional[str] for fetching sub-round pages
        depth:       Recursion depth (max 1; landing pages are followed once)

    Returns:
        list[QualifiedOpportunity] if qualified (may include sub-round entries), or None if rejected.
    """
    # Step 1: fast pre-filter (no API call)
    pre_handled, reason = _pre_filter(s_opp)
    if pre_handled:
        if reason == "gets_fast_path":
            score_result = score_opportunity(
                {
                    "funder_name": s_opp.funder_name,
                    "grant_name": s_opp.grant_name,
                    "description": s_opp.description,
                    "eligibility_summary": s_opp.eligibility_summary,
                    "url": s_opp.url,
                    "is_tender": s_opp.is_tender,
                },
                warm_contact=warm_contact,
            )
            return [_build_qualified_opp(s_opp, score_result, "gets_fast_path")]
        else:
            logger.debug(f"Pre-filter rejected: {s_opp.grant_name[:60]} — {reason}")
            return None

    # Step 2: assemble page text (prefer description; fall back to cleaned raw_html)
    page_text = s_opp.description or ""
    if len(page_text) < 400 and s_opp.raw_html:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(s_opp.raw_html, "lxml")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            page_text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()[:2500]
        except Exception:
            page_text = s_opp.description or ""

    # No API key — fall back to keyword qualification
    client = _get_client()
    if not client:
        logger.warning("No Anthropic API key — using keyword-based qualification fallback")
        return _keyword_fallback_qualify(s_opp, warm_contact)

    # Step 3: single Claude call — qualify + score
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        prompt = QUALIFICATION_AND_SCORING_PROMPT.format(
            today=today,
            profile_summary=_get_profile_summary(),
            funder_name=s_opp.funder_name,
            grant_name=s_opp.grant_name,
            url=s_opp.url,
            page_text=page_text[:2500],
        )
        message = client.messages.create(
            model=Config.ANTHROPIC_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)

    except Exception as e:
        logger.warning(
            f"Qualification call failed for '{s_opp.grant_name[:60]}': {e} — using keyword fallback"
        )
        return _keyword_fallback_qualify(s_opp, warm_contact)

    # Step 4: landing page — follow sub-round URLs (depth limited to 1)
    if result.get("is_landing_page"):
        if depth < 1:
            sub_urls = result.get("sub_round_urls") or []
            sub_opps = []
            for url in sub_urls[:4]:
                if not isinstance(url, str):
                    continue
                sub = _fetch_and_build_sub_opp(url, s_opp, fetch_fn)
                if sub:
                    sub_results = qualify_and_score(
                        sub,
                        warm_contact=warm_contact,
                        fetch_fn=fetch_fn,
                        depth=depth + 1,
                    )
                    if sub_results:
                        sub_opps.extend(sub_results)
            return sub_opps if sub_opps else None
        else:
            # Already at max depth — don't follow further
            return None

    # Step 5: check qualification result
    if not result.get("qualified"):
        logger.debug(
            f"Not qualified: {s_opp.grant_name[:60]} — {result.get('disqualification_reason', 'no reason given')}"
        )
        return None

    # Step 6: backfill deadline from Claude parse if scraper missed it
    if not s_opp.deadline and result.get("gate_deadline_parsed"):
        try:
            from dateutil import parser as date_parser
            s_opp.deadline = date_parser.parse(result["gate_deadline_parsed"])
            if not s_opp.deadline_text:
                s_opp.deadline_text = result["gate_deadline_parsed"]
        except Exception:
            pass

    # Step 7: backfill amount from Claude parse if scraper missed it
    if not s_opp.amount_text and result.get("gate_amount_parsed"):
        s_opp.amount_text = result["gate_amount_parsed"]
        if not s_opp.amount_min and not s_opp.amount_max:
            s_opp.amount_min, s_opp.amount_max = _parse_amount_inline(s_opp.amount_text)

    # Step 8: apply B8 flag adjustments to Claude's base_score
    base_score = max(1, min(10, int(result.get("base_score") or 5)))
    justification = result.get("justification") or ""
    relevance_paragraph = result.get("relevance_paragraph") or ""

    combined_text = " ".join(filter(None, [
        s_opp.grant_name, s_opp.description, s_opp.eligibility_summary, s_opp.funder_name,
    ]))
    flags = detect_flags(combined_text)

    score = base_score
    adjustments = []
    if flags["maori_edge"]:
        score += 1
        adjustments.append({"reason": "Maori community experience gives competitive edge", "delta": +1})
    if flags["school_edge"]:
        score += 1
        adjustments.append({"reason": "School-based background directly relevant", "delta": +1})
    if warm_contact:
        score += 1
        adjustments.append({"reason": "Warm contact at this funder", "delta": +1})
    if flags["requires_registration"]:
        score -= 1
        adjustments.append({"reason": "Requires full clinical registration", "delta": -1})
    if flags["requires_org"] and not _is_registered_org():
        score -= 2
        adjustments.append({"reason": "Requires organisational affiliation", "delta": -2})
    if flags["requires_maori_fluency"]:
        score -= 1
        adjustments.append({"reason": "Requires Te Reo fluency", "delta": -1})
    score = max(1, min(10, round(score)))

    score_result = {
        "score": score,
        "base_score": base_score,
        "justification": justification,
        "relevance_paragraph": relevance_paragraph,
        **flags,
        "score_breakdown": json.dumps({
            "base_score": base_score,
            "adjustments": adjustments,
            "final_score": score,
        }),
    }

    return [_build_qualified_opp(s_opp, score_result, "claude_qualified")]
