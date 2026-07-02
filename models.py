from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import json

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    wiki_username = db.Column(db.String(255))  # Wikipedia username (optional metadata)
    is_admin = db.Column(db.Boolean, default=False)

    # Qualification test tracking
    qualification_passed = db.Column(db.Boolean, default=False)
    qualification_score = db.Column(db.Integer)  # # correct out of total test samples
    qualification_date = db.Column(db.DateTime)

    # Test submission workflow (new)
    test_submitted = db.Column(db.Boolean, default=False)  # has user submitted test (pending admin review)
    test_submission_date = db.Column(db.DateTime)  # when test was submitted
    test_approved_by_admin = db.Column(db.Boolean, default=False)  # admin approved this user
    test_approval_date = db.Column(db.DateTime)  # when admin approved

    # Per-user annotation cap
    max_annotations_cap = db.Column(db.Integer)  # NULL = no cap
    annotations_count = db.Column(db.Integer, default=0)

    # Per-user annotation target (self-set goal)
    annotation_target = db.Column(db.Integer)  # NULL = no self-set target

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    wiki_username_provided = db.Column(db.Boolean, default=False)  # Flag: has user provided wiki username

    # Relationships
    annotations = db.relationship("Annotation", backref="annotator", lazy=True)
    claims = db.relationship("Claim", backref="user", lazy=True)
    skips = db.relationship("Skip", backref="user", lazy=True)


class Dataset(db.Model):
    __tablename__ = "datasets"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    citation_type = db.Column(db.String(20), nullable=False, default="JOURNAL")  # JOURNAL or WEB
    is_active = db.Column(db.Boolean, default=True)
    sample_count = db.Column(db.Integer, default=0)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    pairs = db.relationship("Pair", backref="dataset", lazy=True, cascade="all, delete-orphan")


class Pair(db.Model):
    __tablename__ = "pairs"

    id = db.Column(db.Integer, primary_key=True)
    pair_id = db.Column(db.String(255), nullable=False, index=True)
    dataset_id = db.Column(db.Integer, db.ForeignKey("datasets.id"), nullable=False)
    citation_type = db.Column(db.String(20), nullable=False, default="JOURNAL")  # JOURNAL or WEB

    # Article metadata
    article_title = db.Column(db.String(500))
    research_domains = db.Column(db.String(500))  # pipe-separated: "medicine|history"

    # Passage metadata
    passage_text = db.Column(db.Text)
    passage_word_count = db.Column(db.Integer)
    passage_sentence_count = db.Column(db.Integer)
    passage_context = db.Column(db.Text)  # nullable if not present

    # Citation metadata
    citation_title = db.Column(db.String(500))
    citation_journal = db.Column(db.String(255))
    citation_doi = db.Column(db.String(255))
    citation_year = db.Column(db.String(10))
    citation_authors = db.Column(db.String(1000))
    citation_raw_text = db.Column(db.Text)
    citation_source_url = db.Column(db.Text)
    citation_raw_word_count = db.Column(db.Integer)

    # Test/qualification
    is_test_sample = db.Column(db.Boolean, default=False)
    correct_label = db.Column(db.String(50))  # only populated if is_test_sample=TRUE

    # Annotation tracking
    annotation_count = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Constraint: unique pair_id within each dataset
    __table_args__ = (db.UniqueConstraint("pair_id", "dataset_id", name="uq_pair_id_dataset_id"),)

    # Relationships
    annotations = db.relationship("Annotation", backref="pair", lazy=True, cascade="all, delete-orphan")
    claims = db.relationship("Claim", backref="pair", lazy=True, cascade="all, delete-orphan")


class Annotation(db.Model):
    __tablename__ = "annotations"

    id = db.Column(db.Integer, primary_key=True)
    pair_id = db.Column(db.Integer, db.ForeignKey("pairs.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # New fact-checking labels: TRUE, FALSE, MIXED, NO_SUFFICIENT_INFO, UNVERIFIABLE
    label = db.Column(db.String(50), nullable=False)
    quote = db.Column(db.Text)  # exact verbatim from citation
    explanation = db.Column(db.Text)  # annotator's reasoning

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Constraint: one annotation per user per pair
    __table_args__ = (db.UniqueConstraint("pair_id", "user_id", name="uq_annotation_pair_user"),)


class Claim(db.Model):
    __tablename__ = "claims"

    id = db.Column(db.Integer, primary_key=True)
    pair_id = db.Column(db.Integer, db.ForeignKey("pairs.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    claimed_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Constraint: unique (pair_id, user_id)
    __table_args__ = (db.UniqueConstraint("pair_id", "user_id", name="uq_claim_pair_user"),)

    def is_expired(self, timeout_minutes=30):
        return datetime.utcnow() > self.claimed_at + timedelta(minutes=timeout_minutes)


class Skip(db.Model):
    __tablename__ = "skips"

    id = db.Column(db.Integer, primary_key=True)
    pair_id = db.Column(db.Integer, db.ForeignKey("pairs.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Constraint: unique (pair_id, user_id) — one skip per user per pair
    __table_args__ = (db.UniqueConstraint("pair_id", "user_id", name="uq_skip_pair_user"),)


class TestSubmission(db.Model):
    __tablename__ = "test_submissions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    pair_id = db.Column(db.Integer, db.ForeignKey("pairs.id"), nullable=False)
    label = db.Column(db.String(50))  # their answer (TRUE, FALSE, MIXED, etc.)
    quote = db.Column(db.Text)  # exact verbatim from citation
    explanation = db.Column(db.Text)  # annotator's reasoning
    is_submitted = db.Column(db.Boolean, default=False)  # True = part of a finalized submission
    submission_batch_id = db.Column(db.String(255))  # groups answers from same test attempt
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Constraint: only one answer per user per pair per attempt
    __table_args__ = (db.UniqueConstraint("user_id", "pair_id", "submission_batch_id", name="uq_test_submission"),)

    # Relationships
    user = db.relationship("User", backref="test_submissions", lazy=True)
    pair = db.relationship("Pair", foreign_keys=[pair_id], backref="test_submissions", lazy=True)


class Config(db.Model):
    __tablename__ = "config"

    key = db.Column(db.String(255), primary_key=True)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        config = Config.query.filter_by(key=key).first()
        if config is None:
            return default
        # Try to parse as JSON if it looks like JSON
        if config.value and config.value.strip().startswith('{'):
            try:
                return json.loads(config.value)
            except json.JSONDecodeError:
                return config.value
        try:
            return int(config.value)
        except (ValueError, TypeError):
            return config.value

    @staticmethod
    def set(key, value):
        config = Config.query.filter_by(key=key).first()
        if config is None:
            config = Config(key=key)
            db.session.add(config)
        if isinstance(value, (dict, list)):
            config.value = json.dumps(value)
        else:
            config.value = str(value)
        config.updated_at = datetime.utcnow()
        db.session.commit()
