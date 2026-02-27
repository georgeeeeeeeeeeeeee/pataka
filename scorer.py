"""
Fit scoring engine.

Scores each opportunity 1-10 against George's practitioner profile (profile.json).
Uses Claude for nuanced base scoring, then applies deterministic B8 rule adjustments.
"""
import json
import logging
import re
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

SCORING_PROMPT = """You are scoring a funding/contracting opportunity for a specific practitioner.

## PRACTITIONER PROFILE (Ground Truth)
{profile_summary}

## OPPORTUNITY
Funder: {funder_name}
Grant/Tender: {grant_name}
Description: {description}
Eligibility: {eligibility}
URL: {url}

## YOUR TASK
Score this opportunity 1-10 for fit with this practitioner. Use these tiers:
- 8-10: Direct match — the practitioner's demonstrated experience, current roles, or stated competencies directly address what the funder is seeking
- 5-7: Adjacent — relevant but requires some stretch, partnership, or framing; practitioner could make a compelling case
- 1-4: Tangential — wrong sector, requires credentials not held, or the connection is too weak to justify pursuing

Be specific. Consider ALL competency domains (school-based mental health, community mental health, Maori-informed practice, mindfulness, research, creative/arts practice). Do not underweight the creative/arts domain.

Respond with ONLY valid JSON (no markdown, no commentary):
{{
  "base_score": <integer 1-10>,
  "justification": "<one concise sentence explaining the score>",
  "relevance_paragraph": "<2-3 sentences explaining relevance to this practitioner's specific work, written for him to read>",
  "eligibility_issues": "<any eligibility concerns or null>",
  "primary_competency_match": "<which competency area is the strongest match>"
}}"""

PROFILE_SUMMARY = """
George Johnston, 36, Wellington NZ. Current guidance counsellor at Newlands College (secondary school).
Completing Master of Counselling at Massey University (Year 1 done). Sole practitioner — private practice
accepting NZ and international clients.

IMPACT: ~150,000 children reached through national programme delivery; 960+ professionals trained.
Delivered Coliberate (communication skills) and Pause Breathe Smile (mindfulness) nationally.
Co-facilitated Nga Whetuu Marama community mental health programme in Opotiki (kaupapa Maori framework).

COMPETENCIES:
1. School-based mental health (current role, Newlands College)
2. Community mental health at scale (150k children, 960+ trained)
3. Culturally responsive / Maori-community-informed practice (Nga Whetuu Marama, diverse school communities)
4. Mindfulness in education (Pause Breathe Smile national delivery; Buddhist personal practice)
5. Workshop facilitation and experiential education (national delivery, trainer training)
6. Research/academic (Master of Counselling, continental philosophy writing)
7. Creative practice: experimental music production, cultural criticism (Substack with academic readership)

REGISTRATION: Working toward NZAC (student registration in progress — not yet fully registered).
ENTITY: Sole practitioner — not an organisation (flag org-required opportunities, don't filter).
TE REO: Developing/basic — not conversational. Has Maori community practice experience.
CREATIVE GRANTS: Creative NZ, NZ On Air music grants are as relevant as clinical/health grants.
"""


def score_opportunity(opp_data: dict, warm_contact: bool = False) -> dict:
    """
    Score an opportunity against George's profile.

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
        adjustments.append({"reason": "Requires full registration (George is working toward NZAC)", "delta": -1})

    if flags["requires_org"]:
        score -= 2
        adjustments.append({"reason": "Requires organisational affiliation (sole practitioner)", "delta": -2})

    if flags["requires_maori_fluency"]:
        score -= 1
        adjustments.append({"reason": "Requires Te Reo fluency (George has developing, not conversational)", "delta": -1})

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
            profile_summary=PROFILE_SUMMARY,
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
        f"This opportunity aligns with George's work in {comp_list}. "
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
