"""
Flask web application — the UI layer for the Opportunity Intelligence Agent.
"""
import json
import logging
import os
from datetime import datetime
from io import BytesIO

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_file, abort
)
from flask_sqlalchemy import SQLAlchemy

from config import Config
from models import db, Opportunity, Contact, Brief, Application, ScraperRun

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    Config.ensure_dirs()

    app = Flask(__name__, template_folder="templates")
    app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    # Register routes
    _register_routes(app)

    return app


def _register_routes(app: Flask):

    # ------------------------------------------------------------------
    # Context processors
    # ------------------------------------------------------------------
    @app.context_processor
    def inject_globals():
        from models import ScraperRun
        last_run = ScraperRun.query.order_by(ScraperRun.started_at.desc()).first()
        new_count = Opportunity.query.filter_by(status="new").count()
        return {
            "last_run": last_run,
            "new_count": new_count,
            "now": datetime.utcnow(),
        }

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    @app.route("/")
    def dashboard():
        # Upcoming deadlines (next 60 days, score >= 5)
        from sqlalchemy import and_
        upcoming = (
            Opportunity.query
            .filter(
                Opportunity.deadline >= datetime.utcnow(),
                Opportunity.fit_score >= 5,
                Opportunity.status.in_(["new", "interested", "watching"]),
            )
            .order_by(Opportunity.deadline.asc())
            .limit(8)
            .all()
        )

        # High fit (score 8+)
        high_fit = (
            Opportunity.query
            .filter(
                Opportunity.fit_score >= 8,
                Opportunity.status.in_(["new", "interested"]),
            )
            .order_by(Opportunity.fit_score.desc())
            .limit(8)
            .all()
        )

        # Latest brief
        latest_brief = Brief.query.order_by(Brief.created_at.desc()).first()

        # Stats
        stats = {
            "total": Opportunity.query.count(),
            "new": Opportunity.query.filter_by(status="new").count(),
            "interested": Opportunity.query.filter_by(status="interested").count(),
            "applied": Opportunity.query.filter_by(status="applied").count(),
            "high_fit": Opportunity.query.filter(Opportunity.fit_score >= 8).count(),
            "tenders": Opportunity.query.filter_by(is_tender=True).count(),
        }

        return render_template(
            "dashboard.html",
            upcoming=upcoming,
            high_fit=high_fit,
            latest_brief=latest_brief,
            stats=stats,
        )

    # ------------------------------------------------------------------
    # Opportunities
    # ------------------------------------------------------------------
    @app.route("/opportunities")
    def opportunities():
        # Filters
        status_filter = request.args.get("status", "")
        score_min = request.args.get("score_min", "")
        is_tender = request.args.get("is_tender", "")
        source_filter = request.args.get("source", "")
        flag_org = request.args.get("flag_org", "")
        flag_maori = request.args.get("flag_maori", "")
        flag_school = request.args.get("flag_school", "")
        sort = request.args.get("sort", "score_desc")
        search = request.args.get("q", "").strip()

        query = Opportunity.query

        if status_filter:
            query = query.filter(Opportunity.status == status_filter)
        if score_min:
            try:
                query = query.filter(Opportunity.fit_score >= float(score_min))
            except ValueError:
                pass
        if is_tender == "1":
            query = query.filter(Opportunity.is_tender == True)
        elif is_tender == "0":
            query = query.filter(Opportunity.is_tender == False)
        if source_filter:
            query = query.filter(Opportunity.source_id == source_filter)
        if flag_org == "1":
            query = query.filter(Opportunity.requires_org == True)
        if flag_maori == "1":
            query = query.filter(Opportunity.maori_edge == True)
        if flag_school == "1":
            query = query.filter(Opportunity.school_edge == True)
        if search:
            like = f"%{search}%"
            query = query.filter(
                db.or_(
                    Opportunity.grant_name.ilike(like),
                    Opportunity.funder_name.ilike(like),
                    Opportunity.description.ilike(like),
                )
            )

        # Sorting
        sort_options = {
            "score_desc": Opportunity.fit_score.desc(),
            "score_asc": Opportunity.fit_score.asc(),
            "deadline_asc": Opportunity.deadline.asc(),
            "deadline_desc": Opportunity.deadline.desc(),
            "newest": Opportunity.first_seen.desc(),
        }
        order_col = sort_options.get(sort, Opportunity.fit_score.desc())
        query = query.order_by(order_col)

        page = request.args.get("page", 1, type=int)
        per_page = 25
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        opps = pagination.items

        # For filter dropdowns
        sources = db.session.query(Opportunity.source_id).distinct().all()
        sources = [s[0] for s in sources]

        return render_template(
            "opportunities.html",
            opportunities=opps,
            pagination=pagination,
            sources=sources,
            filters={
                "status": status_filter,
                "score_min": score_min,
                "is_tender": is_tender,
                "source": source_filter,
                "flag_org": flag_org,
                "flag_maori": flag_maori,
                "flag_school": flag_school,
                "sort": sort,
                "q": search,
            },
        )

    @app.route("/opportunities/<int:opp_id>")
    def opportunity_detail(opp_id):
        opp = Opportunity.query.get_or_404(opp_id)
        # Find contacts at this funder
        contacts = Contact.query.filter(
            Contact.org_name.ilike(f"%{opp.funder_name.split()[0]}%")
        ).all()
        applications = Application.query.filter_by(opportunity_id=opp_id).order_by(
            Application.version.desc()
        ).all()
        return render_template(
            "opportunity.html",
            opp=opp,
            contacts=contacts,
            applications=applications,
        )

    @app.route("/opportunities/<int:opp_id>/status", methods=["POST"])
    def update_status(opp_id):
        opp = Opportunity.query.get_or_404(opp_id)
        new_status = request.form.get("status")
        valid_statuses = ["new", "interested", "applied", "declined", "not_eligible", "watching"]
        if new_status in valid_statuses:
            opp.status = new_status
            opp.updated_at = datetime.utcnow()
            db.session.commit()
            flash(f"Status updated to '{opp.status_label}'", "success")
        else:
            flash("Invalid status", "danger")
        return redirect(request.referrer or url_for("opportunity_detail", opp_id=opp_id))

    @app.route("/opportunities/<int:opp_id>/notes", methods=["POST"])
    def update_notes(opp_id):
        opp = Opportunity.query.get_or_404(opp_id)
        opp.notes = request.form.get("notes", "")
        opp.updated_at = datetime.utcnow()
        db.session.commit()
        flash("Notes saved", "success")
        return redirect(url_for("opportunity_detail", opp_id=opp_id))

    @app.route("/opportunities/<int:opp_id>/draft", methods=["POST"])
    def draft_application_view(opp_id):
        opp = Opportunity.query.get_or_404(opp_id)
        from intelligence import draft_application
        notes = request.form.get("notes", "")
        draft_md = draft_application(opp, additional_notes=notes if notes else None)

        # Get max existing version for this opportunity
        max_version = db.session.query(
            db.func.max(Application.version)
        ).filter_by(opportunity_id=opp_id).scalar() or 0

        app_draft = Application(
            opportunity_id=opp_id,
            version=max_version + 1,
            content_md=draft_md,
        )
        db.session.add(app_draft)
        db.session.commit()
        flash("Draft application generated", "success")
        return redirect(url_for("opportunity_detail", opp_id=opp_id))

    @app.route("/opportunities/<int:opp_id>/export/markdown")
    def export_opportunity_md(opp_id):
        opp = Opportunity.query.get_or_404(opp_id)
        from exporters import opportunity_to_markdown
        content = opportunity_to_markdown(opp)
        buf = BytesIO(content.encode("utf-8"))
        safe_name = "".join(c for c in opp.grant_name[:40] if c.isalnum() or c in " -").strip().replace(" ", "_")
        return send_file(
            buf,
            as_attachment=True,
            download_name=f"opportunity_{opp_id}_{safe_name}.md",
            mimetype="text/markdown",
        )

    @app.route("/opportunities/<int:opp_id>/export/pdf")
    def export_opportunity_pdf(opp_id):
        opp = Opportunity.query.get_or_404(opp_id)
        from exporters import export_opportunity_pdf
        path = export_opportunity_pdf(opp)
        if path:
            return send_file(path, as_attachment=True)
        flash("PDF export failed — check logs", "danger")
        return redirect(url_for("opportunity_detail", opp_id=opp_id))

    # ------------------------------------------------------------------
    # Briefs
    # ------------------------------------------------------------------
    @app.route("/briefs")
    def briefs():
        all_briefs = Brief.query.order_by(Brief.created_at.desc()).all()
        return render_template("briefs.html", briefs=all_briefs)

    @app.route("/briefs/<int:brief_id>")
    def brief_detail(brief_id):
        brief = Brief.query.get_or_404(brief_id)
        return render_template("brief_detail.html", brief=brief)

    @app.route("/briefs/<int:brief_id>/export/markdown")
    def export_brief_md(brief_id):
        brief = Brief.query.get_or_404(brief_id)
        from exporters import export_brief_markdown
        content = export_brief_markdown(brief)
        buf = BytesIO(content.encode("utf-8"))
        return send_file(
            buf,
            as_attachment=True,
            download_name=f"brief_{brief.period}.md",
            mimetype="text/markdown",
        )

    @app.route("/briefs/<int:brief_id>/export/pdf")
    def export_brief_pdf_view(brief_id):
        brief = Brief.query.get_or_404(brief_id)
        from exporters import export_brief_pdf
        path = export_brief_pdf(brief)
        if path:
            return send_file(path, as_attachment=True)
        flash("PDF export failed", "danger")
        return redirect(url_for("brief_detail", brief_id=brief_id))

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------
    @app.route("/contacts")
    def contacts():
        all_contacts = Contact.query.order_by(Contact.org_name.asc()).all()
        return render_template("contacts.html", contacts=all_contacts)

    @app.route("/contacts/new", methods=["GET", "POST"])
    def new_contact():
        if request.method == "POST":
            c = Contact(
                org_name=request.form["org_name"],
                contact_name=request.form.get("contact_name"),
                email=request.form.get("email"),
                phone=request.form.get("phone"),
                role=request.form.get("role"),
                relationship_notes=request.form.get("relationship_notes"),
                warmth=int(request.form.get("warmth", 0)),
            )
            last_contact = request.form.get("last_contact")
            if last_contact:
                try:
                    c.last_contact = datetime.strptime(last_contact, "%Y-%m-%d").date()
                except ValueError:
                    pass
            db.session.add(c)
            db.session.commit()
            flash(f"Contact added: {c.contact_name or c.org_name}", "success")
            return redirect(url_for("contacts"))
        return render_template("contact_form.html", contact=None, action="new")

    @app.route("/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
    def edit_contact(contact_id):
        c = Contact.query.get_or_404(contact_id)
        if request.method == "POST":
            c.org_name = request.form["org_name"]
            c.contact_name = request.form.get("contact_name")
            c.email = request.form.get("email")
            c.phone = request.form.get("phone")
            c.role = request.form.get("role")
            c.relationship_notes = request.form.get("relationship_notes")
            c.warmth = int(request.form.get("warmth", 0))
            last_contact = request.form.get("last_contact")
            if last_contact:
                try:
                    c.last_contact = datetime.strptime(last_contact, "%Y-%m-%d").date()
                except ValueError:
                    pass
            c.updated_at = datetime.utcnow()
            db.session.commit()
            flash("Contact updated", "success")
            return redirect(url_for("contacts"))
        return render_template("contact_form.html", contact=c, action="edit")

    @app.route("/contacts/<int:contact_id>/delete", methods=["POST"])
    def delete_contact(contact_id):
        c = Contact.query.get_or_404(contact_id)
        db.session.delete(c)
        db.session.commit()
        flash("Contact deleted", "success")
        return redirect(url_for("contacts"))

    # ------------------------------------------------------------------
    # Settings & admin
    # ------------------------------------------------------------------
    @app.route("/settings")
    def settings():
        from config import FUNDER_SOURCES
        profile = Config.load_profile()
        runs = ScraperRun.query.order_by(ScraperRun.started_at.desc()).limit(20).all()
        return render_template(
            "settings.html",
            profile=profile,
            sources=FUNDER_SOURCES,
            runs=runs,
        )

    @app.route("/settings/trigger-scrape", methods=["POST"])
    def trigger_scrape():
        """Manually trigger a scrape run."""
        from scheduler import run_full_scrape
        import threading

        source_ids = request.form.getlist("source_ids") or None
        app_ref = app  # capture reference

        def run():
            with app_ref.app_context():
                run_full_scrape(source_ids=source_ids)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        flash("Scrape job started in background — refresh in a minute", "info")
        return redirect(url_for("settings"))

    @app.route("/settings/generate-brief", methods=["POST"])
    def trigger_brief():
        """Manually regenerate the brief for the current month."""
        from scheduler import _generate_monthly_brief
        try:
            _generate_monthly_brief()
            flash("Intelligence brief regenerated", "success")
        except Exception as e:
            flash(f"Brief generation failed: {e}", "danger")
        return redirect(url_for("briefs"))

    # ------------------------------------------------------------------
    # API endpoints (JSON)
    # ------------------------------------------------------------------
    @app.route("/api/opportunities")
    def api_opportunities():
        opps = Opportunity.query.order_by(Opportunity.fit_score.desc()).limit(100).all()
        return jsonify([o.to_dict() for o in opps])

    @app.route("/api/opportunities/<int:opp_id>")
    def api_opportunity(opp_id):
        opp = Opportunity.query.get_or_404(opp_id)
        return jsonify(opp.to_dict())

    @app.route("/api/status", methods=["POST"])
    def api_set_status():
        data = request.json
        opp = Opportunity.query.get_or_404(data["id"])
        opp.status = data["status"]
        opp.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"ok": True, "status": opp.status})

    @app.route("/api/scrape-status")
    def api_scrape_status():
        run = ScraperRun.query.order_by(ScraperRun.started_at.desc()).first()
        if not run:
            return jsonify({"status": "never_run"})
        return jsonify({
            "status": run.status,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "opportunities_found": run.opportunities_found,
        })

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    @app.template_filter("datetime_fmt")
    def datetime_fmt(value, fmt="%d %b %Y"):
        if value is None:
            return "—"
        if isinstance(value, str):
            return value
        return value.strftime(fmt)

    @app.template_filter("score_stars")
    def score_stars(score):
        if score is None:
            return "—"
        filled = round(score / 2)
        return "★" * filled + "☆" * (5 - filled)

    return app
