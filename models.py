"""
SQLAlchemy database models for the Opportunity Intelligence Agent.
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Opportunity(db.Model):
    """A funding or contracting opportunity."""
    __tablename__ = "opportunities"

    id = db.Column(db.Integer, primary_key=True)

    # Source metadata
    source_id = db.Column(db.String(50), nullable=False)       # scraper ID
    funder_name = db.Column(db.String(300), nullable=False)
    grant_name = db.Column(db.String(600), nullable=False)
    url = db.Column(db.String(2000), nullable=False)
    is_tender = db.Column(db.Boolean, default=False)           # True = GETS tender

    # Financial
    amount_min = db.Column(db.Float, nullable=True)
    amount_max = db.Column(db.Float, nullable=True)
    amount_text = db.Column(db.String(300), nullable=True)     # raw text
    high_value = db.Column(db.Boolean, default=False)          # >$50k

    # Timing
    deadline = db.Column(db.DateTime, nullable=True)
    deadline_text = db.Column(db.String(300), nullable=True)   # raw text
    open_date = db.Column(db.DateTime, nullable=True)

    # Content
    eligibility_summary = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    relevance_paragraph = db.Column(db.Text, nullable=True)

    # Fit scoring
    fit_score = db.Column(db.Float, nullable=True)
    fit_justification = db.Column(db.Text, nullable=True)
    score_breakdown = db.Column(db.Text, nullable=True)        # JSON

    # Flags
    requires_org = db.Column(db.Boolean, default=False)
    maori_edge = db.Column(db.Boolean, default=False)
    school_edge = db.Column(db.Boolean, default=False)
    requires_registration = db.Column(db.Boolean, default=False)
    requires_maori_fluency = db.Column(db.Boolean, default=False)

    # Status tracking
    status = db.Column(
        db.String(50),
        default="new"
    )
    # Allowed values: new / interested / applied / declined / not_eligible / watching

    # Internal notes
    notes = db.Column(db.Text, nullable=True)

    # Housekeeping
    raw_data = db.Column(db.Text, nullable=True)               # JSON of scraped data
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relationships
    applications = db.relationship(
        "Application", backref="opportunity", lazy=True,
        cascade="all, delete-orphan"
    )

    @property
    def status_label(self):
        labels = {
            "new": "New",
            "interested": "Interested",
            "applied": "Applied",
            "declined": "Declined",
            "not_eligible": "Not Eligible",
            "watching": "Watching",
        }
        return labels.get(self.status, self.status.title())

    @property
    def status_colour(self):
        colours = {
            "new": "secondary",
            "interested": "primary",
            "applied": "success",
            "declined": "danger",
            "not_eligible": "dark",
            "watching": "warning",
        }
        return colours.get(self.status, "secondary")

    @property
    def score_colour(self):
        if self.fit_score is None:
            return "secondary"
        if self.fit_score >= 8:
            return "success"
        if self.fit_score >= 5:
            return "warning"
        return "danger"

    @property
    def days_until_deadline(self):
        if not self.deadline:
            return None
        delta = self.deadline - datetime.utcnow()
        return delta.days

    @property
    def deadline_urgent(self):
        days = self.days_until_deadline
        return days is not None and 0 <= days <= 30

    def to_dict(self):
        return {
            "id": self.id,
            "source_id": self.source_id,
            "funder_name": self.funder_name,
            "grant_name": self.grant_name,
            "url": self.url,
            "is_tender": self.is_tender,
            "amount_text": self.amount_text,
            "amount_min": self.amount_min,
            "amount_max": self.amount_max,
            "high_value": self.high_value,
            "deadline_text": self.deadline_text,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "eligibility_summary": self.eligibility_summary,
            "description": self.description,
            "relevance_paragraph": self.relevance_paragraph,
            "fit_score": self.fit_score,
            "fit_justification": self.fit_justification,
            "requires_org": self.requires_org,
            "maori_edge": self.maori_edge,
            "school_edge": self.school_edge,
            "requires_registration": self.requires_registration,
            "requires_maori_fluency": self.requires_maori_fluency,
            "status": self.status,
            "notes": self.notes,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
        }

    def __repr__(self):
        return f"<Opportunity {self.id}: {self.grant_name[:50]}>"


class Contact(db.Model):
    """A relationship contact at a funder or contracting agency."""
    __tablename__ = "contacts"

    id = db.Column(db.Integer, primary_key=True)
    org_name = db.Column(db.String(300), nullable=False)
    contact_name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    role = db.Column(db.String(300), nullable=True)
    relationship_notes = db.Column(db.Text, nullable=True)
    last_contact = db.Column(db.Date, nullable=True)
    # 0 = no relationship, 1 = cold (aware of), 2 = warm (met/exchanged), 3 = hot (active relationship)
    warmth = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @property
    def warmth_label(self):
        return {0: "None", 1: "Cold", 2: "Warm", 3: "Hot"}.get(self.warmth, "Unknown")

    @property
    def warmth_colour(self):
        return {0: "secondary", 1: "info", 2: "warning", 3: "success"}.get(
            self.warmth, "secondary"
        )

    def __repr__(self):
        return f"<Contact {self.id}: {self.contact_name} @ {self.org_name}>"


class Brief(db.Model):
    """A monthly intelligence brief."""
    __tablename__ = "briefs"

    id = db.Column(db.Integer, primary_key=True)
    period = db.Column(db.String(20), nullable=False, unique=True)  # YYYY-MM
    title = db.Column(db.String(600), nullable=False)
    content_md = db.Column(db.Text, nullable=False)                 # Markdown source
    content_html = db.Column(db.Text, nullable=True)                # Rendered HTML
    opportunities_analysed = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Brief {self.period}>"


class Application(db.Model):
    """A draft or completed application for an opportunity."""
    __tablename__ = "applications"

    id = db.Column(db.Integer, primary_key=True)
    opportunity_id = db.Column(
        db.Integer, db.ForeignKey("opportunities.id"), nullable=False
    )
    version = db.Column(db.Integer, default=1)
    content_md = db.Column(db.Text, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self):
        return f"<Application {self.id} for Opportunity {self.opportunity_id} v{self.version}>"


class ScraperRun(db.Model):
    """Log of each scraper run for auditing and debugging."""
    __tablename__ = "scraper_runs"

    id = db.Column(db.Integer, primary_key=True)
    scraper_id = db.Column(db.String(100), nullable=False)
    started_at = db.Column(db.DateTime, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default="running")  # running/completed/failed
    opportunities_found = db.Column(db.Integer, default=0)
    new_opportunities = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<ScraperRun {self.scraper_id} @ {self.started_at}>"
