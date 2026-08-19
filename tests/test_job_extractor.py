"""Tests for the job extractor."""

from __future__ import annotations

from parser.models import ParsedNotification
from ai.job_extractor import JobExtractor, RuleBasedJobExtractor


def test_rule_based_extractor_extracts_expected_fields() -> None:
    notification = ParsedNotification(
        title="Research Associate",
        url="https://example.org/jobs/1",
    )
    pdf_text = """
    Job Title: Research Associate
    Organization: Indian Institute of Science
    Salary: Rs. 50,000/month
    Qualification: M.Sc in Climate Science
    Experience: 2 years
    Age Limit: 35 years
    Last Date: 20 August 2026
    Application Link: https://example.org/apply
    """

    extractor = RuleBasedJobExtractor()
    result = extractor.extract(notification, pdf_text)

    assert result["job_title"] == "Research Associate"
    assert result["organization"] == "Indian Institute of Science"
    assert result["salary"] == "Rs. 50,000/month"
    assert result["qualification"] == "M.Sc in Climate Science"
    assert result["experience"] == "2 years"
    assert result["age_limit"] == "35 years"
    assert result["last_date"] == "20 August 2026"
    assert result["application_link"] == "https://example.org/apply"


def test_facade_returns_json_string() -> None:
    notification = ParsedNotification(title="Assistant Professor", url="https://example.org/jobs/2")
    pdf_text = "Job Title: Assistant Professor\nOrganization: University of Delhi"

    extractor = JobExtractor()
    payload = extractor.extract_json(notification, pdf_text)

    assert '"job_title": "Assistant Professor"' in payload
    assert '"organization": "University of Delhi"' in payload
