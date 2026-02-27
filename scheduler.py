"""
Scheduled job runner — APScheduler-based monthly automation.

The main job: scrape all sources → score → upsert to DB → generate brief.
Can be triggered manually via the web UI or run on schedule.
"""
import logging
import json
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Pacific/Auckland")
    return _scheduler


def start_scheduler(app):
    """Start the background scheduler (call after Flask app init)."""
    scheduler = get_scheduler()
    if not scheduler.running:
        # Run on the 1st of each month at 08:00 NZT
        scheduler.add_job(
            func=lambda: run_full_scrape(app),
            trigger=CronTrigger(day=1, hour=8, minute=0),
            id="monthly_scrape",
            name="Monthly opportunity scrape",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Scheduler started — monthly scrape on 1st of each month at 08:00 NZT")


def run_full_scrape(app=None, source_ids: list = None) -> dict:
    """
    Execute a full scrape cycle: scrape → score → upsert → brief.

    Args:
        app: Flask app instance (needed for app context if running in background)
        source_ids: Optional list of scraper IDs to run. If None, runs all enabled scrapers.

    Returns:
        Summary dict with counts and status.
    """
    if app:
        with app.app_context():
            return _run_scrape_in_context(source_ids)
    else:
        return _run_scrape_in_context(source_ids)


def _run_scrape_in_context(source_ids: list = None) -> dict:
    """The actual scraping logic — must be called within Flask app context."""
    from config import FUNDER_SOURCES, GETS_CONFIG, Config
    from models import db, Opportunity, ScraperRun, Brief, Contact
    from scrapers import get_scraper
    from scorer import score_opportunity

    started_at = datetime.utcnow()
    summary = {
        "started_at": started_at.isoformat(),
        "scrapers_run": [],
        "total_found": 0,
        "new_opportunities": 0,
        "updated_opportunities": 0,
        "errors": [],
    }

    # Determine which sources to run
    sources = [s for s in FUNDER_SOURCES if s.get("enabled", True)]
    if source_ids:
        sources = [s for s in sources if s["id"] in source_ids]

    # Add GETS if enabled and not filtered
    if GETS_CONFIG.get("enabled") and (source_ids is None or "gets" in source_ids):
        sources.append({
            "id": "gets",
            "name": "GETS (NZ Government Tenders)",
            "url": GETS_CONFIG["search_url"],
            "scraper": "gets",
            "category": "tenders",
            "country": "NZ",
        })

    # Get warm contact org names for scoring
    warm_orgs = [c.org_name for c in Contact.query.filter(Contact.warmth >= 2).all()]

    for source in sources:
        scraper_id = source["id"]
        run_log = ScraperRun(
            scraper_id=scraper_id,
            started_at=datetime.utcnow(),
            status="running",
        )
        db.session.add(run_log)
        db.session.commit()

        try:
            logger.info(f"Running scraper: {scraper_id}")
            scraper_cls = source.get("scraper", "generic_grant_listing")
            scraper = get_scraper(scraper_cls, source)
            scraped = scraper.scrape()

            new_count = 0
            updated_count = 0

            for s_opp in scraped:
                # Score the opportunity
                score_result = score_opportunity(
                    {
                        "funder_name": s_opp.funder_name,
                        "grant_name": s_opp.grant_name,
                        "description": s_opp.description,
                        "eligibility_summary": s_opp.eligibility_summary,
                        "url": s_opp.url,
                        "is_tender": s_opp.is_tender,
                    },
                    warm_contact=s_opp.funder_name in warm_orgs,
                )

                # Check for existing record (upsert by URL)
                existing = Opportunity.query.filter_by(url=s_opp.url).first()

                if existing:
                    # Update last_seen and re-score
                    existing.last_seen = datetime.utcnow()
                    existing.fit_score = score_result["score"]
                    existing.fit_justification = score_result["justification"]
                    existing.relevance_paragraph = score_result.get("relevance_paragraph")
                    existing.score_breakdown = score_result.get("score_breakdown")
                    existing.requires_org = score_result["requires_org"]
                    existing.maori_edge = score_result["maori_edge"]
                    existing.school_edge = score_result["school_edge"]
                    existing.requires_registration = score_result["requires_registration"]
                    existing.requires_maori_fluency = score_result["requires_maori_fluency"]
                    if s_opp.deadline:
                        existing.deadline = s_opp.deadline
                        existing.deadline_text = s_opp.deadline_text
                    if s_opp.description and not existing.description:
                        existing.description = s_opp.description
                    updated_count += 1
                else:
                    # Determine if high value
                    high_value = False
                    if s_opp.amount_max and s_opp.amount_max >= Config.HIGH_VALUE_THRESHOLD:
                        high_value = True
                    if s_opp.amount_min and s_opp.amount_min >= Config.HIGH_VALUE_THRESHOLD:
                        high_value = True

                    new_opp = Opportunity(
                        source_id=scraper_id,
                        funder_name=s_opp.funder_name,
                        grant_name=s_opp.grant_name,
                        url=s_opp.url,
                        is_tender=s_opp.is_tender,
                        amount_min=s_opp.amount_min,
                        amount_max=s_opp.amount_max,
                        amount_text=s_opp.amount_text,
                        high_value=high_value,
                        deadline=s_opp.deadline,
                        deadline_text=s_opp.deadline_text,
                        open_date=s_opp.open_date,
                        eligibility_summary=s_opp.eligibility_summary,
                        description=s_opp.description,
                        raw_data=json.dumps(s_opp.to_dict()),
                        fit_score=score_result["score"],
                        fit_justification=score_result["justification"],
                        relevance_paragraph=score_result.get("relevance_paragraph"),
                        score_breakdown=score_result.get("score_breakdown"),
                        requires_org=score_result["requires_org"],
                        maori_edge=score_result["maori_edge"],
                        school_edge=score_result["school_edge"],
                        requires_registration=score_result["requires_registration"],
                        requires_maori_fluency=score_result["requires_maori_fluency"],
                        status="new",
                    )
                    db.session.add(new_opp)
                    new_count += 1

            db.session.commit()

            run_log.completed_at = datetime.utcnow()
            run_log.status = "completed"
            run_log.opportunities_found = len(scraped)
            run_log.new_opportunities = new_count
            db.session.commit()

            summary["scrapers_run"].append({
                "id": scraper_id,
                "found": len(scraped),
                "new": new_count,
                "updated": updated_count,
            })
            summary["total_found"] += len(scraped)
            summary["new_opportunities"] += new_count
            summary["updated_opportunities"] += updated_count

        except Exception as e:
            logger.error(f"Scraper {scraper_id} failed: {e}", exc_info=True)
            run_log.completed_at = datetime.utcnow()
            run_log.status = "failed"
            run_log.error_message = str(e)
            db.session.commit()
            summary["errors"].append({"scraper": scraper_id, "error": str(e)})

    # Generate monthly brief if this is a full run
    if source_ids is None:
        _generate_monthly_brief()

    summary["completed_at"] = datetime.utcnow().isoformat()
    logger.info(f"Scrape complete: {summary['new_opportunities']} new, "
                f"{summary['updated_opportunities']} updated")
    return summary


def _generate_monthly_brief():
    """Generate (or regenerate) the intelligence brief for the current month."""
    from models import db, Opportunity, Brief
    from intelligence import generate_brief

    period = datetime.utcnow().strftime("%Y-%m")

    # Fetch this month's and last month's opportunities for context
    opportunities = Opportunity.query.filter(
        Opportunity.fit_score >= 5
    ).order_by(Opportunity.fit_score.desc()).limit(60).all()

    if not opportunities:
        logger.info("No scored opportunities — skipping brief generation")
        return

    try:
        brief_data = generate_brief(opportunities, period=period)

        # Upsert brief for this period
        existing = Brief.query.filter_by(period=period).first()
        if existing:
            existing.title = brief_data["title"]
            existing.content_md = brief_data["content_md"]
            existing.content_html = brief_data["content_html"]
            existing.opportunities_analysed = brief_data["opportunities_analysed"]
        else:
            brief = Brief(
                period=period,
                title=brief_data["title"],
                content_md=brief_data["content_md"],
                content_html=brief_data["content_html"],
                opportunities_analysed=brief_data["opportunities_analysed"],
            )
            db.session.add(brief)

        db.session.commit()
        logger.info(f"Brief generated for {period}")
    except Exception as e:
        logger.error(f"Brief generation failed: {e}", exc_info=True)
