import json
import re
from datetime import datetime
from models import db, Pair, Dataset


def extract_citation_authors(record):
    """
    Extract authors from citation_fields.
    Handles both patterns: first{i}/last{i} and author{i}.
    Returns "Last, First; Last2, First2; ..." format.
    """
    citation_fields = record.get("citation_fields", {})
    authors = []

    # Try first{i}/last{i} pattern first
    i = 1
    while True:
        first_key = f"first{i}"
        last_key = f"last{i}"
        if first_key not in citation_fields or last_key not in citation_fields:
            break
        first = citation_fields[first_key]
        last = citation_fields[last_key]
        authors.append(f"{last}, {first}")
        i += 1

    # If no authors found, try author{i} pattern
    if not authors:
        i = 1
        while f"author{i}" in citation_fields:
            author = citation_fields[f"author{i}"]
            if author:  # Only add non-empty authors
                authors.append(author)
            i += 1

    return "; ".join(authors) if authors else ""


def extract_citation_year(record):
    """
    Extract year from citation_fields.date using regex.
    Matches 4-digit years between 1800 and 2100.
    """
    citation_fields = record.get("citation_fields", {})
    date_str = citation_fields.get("date", "")
    if date_str:
        match = re.search(r"\b(1[89]\d{2}|20\d{2})\b", date_str)
        if match:
            return match.group(1)
    return None


def parse_jsonl_file(file_path, dataset, citation_type="JOURNAL"):
    """
    Stream-parse a JSONL file and create Pair records in the given dataset.
    Handles both nested citation_fields schema and flat citation_* fields.

    Args:
        file_path: Path to JSONL file
        dataset: Dataset object to add pairs to
        citation_type: "JOURNAL" or "WEB" (default: JOURNAL)

    Returns: {loaded: int, skipped_duplicates: int, errors: list}
    """
    loaded = 0
    skipped_duplicates = 0
    errors = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    errors.append(f"Line {line_no}: JSON parse error: {str(e)}")
                    continue

                # Extract/map fields from real schema
                pair_id = record.get("pair_id")
                if not pair_id:
                    errors.append(f"Line {line_no}: missing pair_id")
                    continue

                # Check for duplicate within this dataset
                existing = Pair.query.filter_by(
                    pair_id=pair_id, dataset_id=dataset.id
                ).first()
                if existing:
                    skipped_duplicates += 1
                    continue

                # Extract citation metadata (handle both schemas)
                # Try nested citation_fields first
                citation_fields = record.get("citation_fields", {})
                citation_title = citation_fields.get("title") or record.get("citation_title", "")
                citation_journal = citation_fields.get("journal") or record.get("citation_journal", "")
                citation_doi = citation_fields.get("doi") or record.get("citation_doi", "")
                citation_year = extract_citation_year(record) or record.get("citation_year")
                citation_authors = extract_citation_authors(record) or record.get("citation_authors", "")

                # Extract research domains (join array with |)
                domains_list = record.get("research_domains", [])
                research_domains = "|".join(domains_list) if isinstance(domains_list, list) else ""

                # Create Pair record
                pair = Pair(
                    pair_id=pair_id,
                    dataset_id=dataset.id,
                    citation_type=citation_type,
                    article_title=record.get("article_title", ""),
                    research_domains=research_domains,
                    passage_text=record.get("passage_text", ""),
                    passage_word_count=record.get("passage_word_count"),
                    passage_sentence_count=record.get("passage_sentence_count"),
                    passage_context=record.get("passage_context"),  # nullable
                    citation_title=citation_title,
                    citation_journal=citation_journal,
                    citation_doi=citation_doi,
                    citation_year=citation_year,
                    citation_authors=citation_authors,
                    citation_raw_text=record.get("citation_raw_text", ""),
                    citation_source_url=record.get("citation_source_url", ""),
                    citation_raw_word_count=record.get("citation_raw_word_count"),
                    is_test_sample=False,
                    correct_label=None,
                    annotation_count=0,
                )
                db.session.add(pair)
                loaded += 1

        db.session.commit()
        dataset.citation_type = citation_type
        dataset.sample_count = loaded
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        errors.append(f"Unexpected error: {str(e)}")

    return {"loaded": loaded, "skipped_duplicates": skipped_duplicates, "errors": errors}


def seed_default_config():
    """Seed the config table with default values."""
    from models import Config

    defaults = {
        "MAX_ANNOTATIONS_PER_USER": None,
        "ANNOTATORS_PER_SAMPLE": "3",
        "MIN_SAMPLES_FOR_TARGET": "300",
        "DOMAIN_DISTRIBUTION": json.dumps(
            {"medicine": 50, "history": 30, "animals": 15, "artists": 5}
        ),
        "QUALIFICATION_THRESHOLD": "80",
        "ANNOTATOR_CAP_ENABLED": "true",
        "SESSION_TIMEOUT_MINUTES": "10080",
    }

    for key, default_value in defaults.items():
        existing = Config.query.filter_by(key=key).first()
        if existing is None:
            config = Config(key=key, value=default_value)
            db.session.add(config)

    db.session.commit()
