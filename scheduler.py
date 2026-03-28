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
    from config import FUNDER_SOURCES, Config
    from models import db, Opportunity, ScraperRun, Brief, Contact
    from scrapers import get_scraper
    from scorer import score_opportunity, qualify_and_score

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
            rejected_count = 0

            for s_opp in scraped:
                qualified_opps = qualify_and_score(
                    s_opp,
                    warm_contact=s_opp.funder_name in warm_orgs,
                    fetch_fn=scraper.fetch,
                )
                if not qualified_opps:
                    rejected_count += 1
                    logger.debug(f"[{scraper_id}] Rejected: {s_opp.grant_name[:60]}")
                    continue

                for q_opp in qualified_opps:
                    existing = Opportunity.query.filter_by(url=q_opp.url).first()

                    if existing:
                        # Update score + deadline/amount if improved
                        existing.last_seen = datetime.utcnow()
                        existing.fit_score = q_opp.score
                        existing.fit_justification = q_opp.justification
                        existing.relevance_paragraph = q_opp.relevance_paragraph
                        existing.score_breakdown = q_opp.score_breakdown
                        existing.requires_org = q_opp.requires_org
                        existing.maori_edge = q_opp.maori_edge
                        existing.school_edge = q_opp.school_edge
                        existing.requires_registration = q_opp.requires_registration
                        existing.requires_maori_fluency = q_opp.requires_maori_fluency
                        if q_opp.deadline:
                            existing.deadline = q_opp.deadline
                            existing.deadline_text = q_opp.deadline_text
                        if q_opp.amount_text and not existing.amount_text:
                            existing.amount_text = q_opp.amount_text
                        if q_opp.amount_min and not existing.amount_min:
                            existing.amount_min = q_opp.amount_min
                        if q_opp.amount_max and not existing.amount_max:
                            existing.amount_max = q_opp.amount_max
                        if q_opp.description and not existing.description:
                            existing.description = q_opp.description
                        updated_count += 1
                    else:
                        high_value = False
                        if q_opp.amount_max and q_opp.amount_max >= Config.HIGH_VALUE_THRESHOLD:
                            high_value = True
                        if q_opp.amount_min and q_opp.amount_min >= Config.HIGH_VALUE_THRESHOLD:
                            high_value = True

                        new_opp = Opportunity(
                            source_id=q_opp.source_id,
                            funder_name=q_opp.funder_name,
                            grant_name=q_opp.grant_name,
                            url=q_opp.url,
                            is_tender=q_opp.is_tender,
                            amount_min=q_opp.amount_min,
                            amount_max=q_opp.amount_max,
                            amount_text=q_opp.amount_text,
                            high_value=high_value,
                            deadline=q_opp.deadline,
                            deadline_text=q_opp.deadline_text,
                            open_date=q_opp.open_date,
                            eligibility_summary=q_opp.eligibility_summary,
                            description=q_opp.description,
                            raw_data=json.dumps(q_opp.to_dict()),
                            fit_score=q_opp.score,
                            fit_justification=q_opp.justification,
                            relevance_paragraph=q_opp.relevance_paragraph,
                            score_breakdown=q_opp.score_breakdown,
                            requires_org=q_opp.requires_org,
                            maori_edge=q_opp.maori_edge,
                            school_edge=q_opp.school_edge,
                            requires_registration=q_opp.requires_registration,
                            requires_maori_fluency=q_opp.requires_maori_fluency,
                            status="new",
                        )
                        db.session.add(new_opp)
                        new_count += 1

            db.session.commit()
            logger.info(
                f"[{scraper_id}] {len(scraped)} scraped → {rejected_count} rejected"
                f" → {new_count + updated_count} saved ({new_count} new, {updated_count} updated)"
            )

            run_log.completed_at = datetime.utcnow()
            run_log.status = "completed"
            run_log.opportunities_found = new_count + updated_count
            run_log.new_opportunities = new_count
            db.session.commit()

            summary["scrapers_run"].append({
                "id": scraper_id,
                "scraped": len(scraped),
                "found": new_count + updated_count,
                "new": new_count,
                "updated": updated_count,
                "rejected": rejected_count,
            })
            summary["total_found"] += new_count + updated_count
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
