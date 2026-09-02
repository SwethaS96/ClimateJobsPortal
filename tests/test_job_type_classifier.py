"""Tests for ai/job_type_classifier.py.

Rule-based only — no AI backend, no network access, no external
dependency in this module.
"""

from __future__ import annotations

import pytest

from ai.job_type_classifier import (
    JOB_TYPES,
    JobTypeClassifier,
    RuleBasedJobTypeBackend,
    build_default_classifier,
)


# ---------------------------------------------------------------------------
# RuleBasedJobTypeBackend — direct classification (Part H items 8-14)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Junior Research Fellow (JRF) opening in Physics Dept", "JRF"),
        ("Advertisement for JRF position", "JRF"),
        ("Senior Research Fellow (SRF) required", "SRF"),
        ("SRF Opening under DST project", "SRF"),
        ("Project Associate-I (PA-I)", "PROJECT_ASSOCIATE"),
        ("Project Assistant", "PROJECT_ASSISTANT"),
        ("Project Scientist required for climate modeling project", "SCIENTIST"),
        ("Research Assistant position available", "RESEARCH_ASSISTANT"),
        ("Research Associate", "RESEARCH_ASSOCIATE"),
        ("Research Fellow position in Geophysics Department", "FELLOWSHIP"),
        ("Postdoctoral Positions", "POSTDOCTORAL"),
        ("Postdoctoral Fellow", "POSTDOCTORAL"),
        ("Post-Doctoral Fellowship in Climate Science", "POSTDOCTORAL"),
        ("Walk-in-interview/Recruitment for Temporary Faculty", "FACULTY"),
        ("Faculty Recruitment 2026", "FACULTY"),
        ("Advertisement for the post of Assistant Professor", "FACULTY"),
        ("Scientist-B", "SCIENTIST"),
        ("Consultant", "CONSULTANT"),
        ("Technical Assistant opening", "TECHNICAL"),
        ("Technical Assistant", "TECHNICAL"),
        ("Apprentice", "APPRENTICE"),
        ("Internship", "INTERNSHIP"),
        ("Field Investigator required for ICSSR project", "OTHER_RESEARCH"),
        ("Scientist recruitment 2026", "SCIENTIST"),
    ],
)
def test_rule_based_backend_classifies_expected_job_type(title: str, expected: str):
    backend = RuleBasedJobTypeBackend()
    result = backend.classify(title, "")
    assert result["job_type"] == expected
    assert 0.0 <= result["confidence"] <= 1.0


def test_rule_based_backend_project_scientist_folds_into_bare_scientist():
    """PROJECT_SCIENTIST isn't its own category in the Phase 40 taxonomy —
    'Project Scientist' resolves to the SCIENTIST bucket."""
    result = RuleBasedJobTypeBackend().classify("Project Scientist required", "")
    assert result["job_type"] == "SCIENTIST"


def test_rule_based_backend_research_fellow_does_not_match_fellowship_scheme():
    """'Research Fellow' (a title) is distinct from 'Fellowship Scheme' (a
    scheme/program noun) — the regex has a negative lookahead for exactly
    this reason."""
    result = RuleBasedJobTypeBackend().classify("Research Fellowship Scheme", "")
    assert result["job_type"] != "FELLOWSHIP"


def test_rule_based_backend_unrecognized_title_is_other_research():
    result = RuleBasedJobTypeBackend().classify("Engagement of manpower on contract basis", "")
    assert result["job_type"] == "OTHER_RESEARCH"
    assert result["confidence"] < 0.5


def test_rule_based_backend_consultant_engagement_is_now_classified():
    """A phrase that would previously have fallen through to the generic
    OTHER_RESEARCH bucket now resolves to the more specific CONSULTANT
    category added in Phase 40."""
    result = RuleBasedJobTypeBackend().classify("Engagement of 03 consultants on contract basis", "")
    assert result["job_type"] == "CONSULTANT"


# ---------------------------------------------------------------------------
# Phase 40 Part C/F — evidence priority and false-classification guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Admission for Research Programme",
        "Research Scheme",
        "Fellowship Scheme",
        "Scholarship Scheme",
        "Research Conference",
        "Scientist Award",
        "Faculty Directory",
        "Tender for Scientific Equipment",
    ],
)
def test_rule_based_backend_does_not_misclassify_non_recruitment_phrases(title: str):
    """These must NOT be classified into a specific job-type category
    merely because they contain words like research, scientist, faculty,
    or fellowship — they should fall through to a generic/low-confidence
    bucket instead."""
    result = RuleBasedJobTypeBackend().classify(title, "")
    misleading_categories = {
        "RESEARCH_ASSISTANT", "RESEARCH_ASSOCIATE", "SCIENTIST", "FACULTY",
        "FELLOWSHIP", "JRF", "SRF", "POSTDOCTORAL",
    }
    assert result["job_type"] not in misleading_categories


def test_rule_based_backend_never_receives_a_url_argument():
    """`classify()` only accepts title + context — there is no url
    parameter, so a URL fragment like 'research-admission.example.edu'
    can never be evidence for a job-type match."""
    import inspect

    signature = inspect.signature(RuleBasedJobTypeBackend.classify)
    assert "url" not in signature.parameters


# ---------------------------------------------------------------------------
# Phase 41 Part D — additional priority/bare-word examples
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Scientist", "SCIENTIST"),
        ("Fellowship", "FELLOWSHIP"),
        ("Research position", "OTHER_RESEARCH"),
        ("Recruitment", "GENERAL_RECRUITMENT"),
        ("Administrative Assistant", "ADMINISTRATIVE"),
    ],
)
def test_rule_based_backend_phase41_priority_examples(title: str, expected: str):
    result = RuleBasedJobTypeBackend().classify(title, "")
    assert result["job_type"] == expected


def test_ambiguous_content_falls_back_to_other_research_not_unknown():
    """Documented behavior difference from the Phase 41 spec's shorthand
    ('Unknown/ambiguous title -> UNKNOWN'): for the RuleBasedJobTypeBackend,
    genuinely ambiguous TEXT (no recognizable keyword) resolves to the
    low-confidence OTHER_RESEARCH bucket by design (see JOB_TYPES docstring
    and Phase 40's `_PATTERNS` fallback) — UNKNOWN is reserved for the
    JobTypeClassifier facade's own failure path (backend raises, returns
    malformed data, or an unrecognized job_type), never for a
    content-based 'I don't know' guess. Both are exercised below."""
    ambiguous_result = RuleBasedJobTypeBackend().classify("xyzzy plugh quux", "")
    assert ambiguous_result["job_type"] == "OTHER_RESEARCH"

    class RaisingBackend:
        def classify(self, title, context):
            raise RuntimeError("boom")

    failure_result = JobTypeClassifier(backend=RaisingBackend()).classify("xyzzy plugh quux")
    assert failure_result["job_type"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# Phase 41 Part E — additional false-classification regression variants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Research Fellowship Scheme",
        "Scientist Award 2026",
        "Research Programme Admission",
        "Scholarship for Research Students",
        "Project Scheme Guidelines",
        "Research Conference 2026",
    ],
)
def test_rule_based_backend_phase41_false_positive_variants(title: str):
    result = RuleBasedJobTypeBackend().classify(title, "")
    misleading_categories = {
        "RESEARCH_ASSISTANT", "RESEARCH_ASSOCIATE", "PROJECT_ASSISTANT", "PROJECT_ASSOCIATE",
        "SCIENTIST", "FACULTY", "FELLOWSHIP", "JRF", "SRF", "POSTDOCTORAL",
    }
    assert result["job_type"] not in misleading_categories


def test_rule_based_backend_uses_context_too():
    result = RuleBasedJobTypeBackend().classify("Opening", "This is a Junior Research Fellow position")
    assert result["job_type"] == "JRF"


# ---------------------------------------------------------------------------
# JobTypeClassifier facade — fail-safe wrapping (Part H items 15-17)
# ---------------------------------------------------------------------------


class RaisingBackend:
    def classify(self, title, context):
        raise RuntimeError("backend exploded")


class TimeoutBackend:
    def classify(self, title, context):
        raise TimeoutError("backend timed out")


class MalformedJsonBackend:
    def classify(self, title, context):
        return "not a dict"


class MissingFieldsBackend:
    def classify(self, title, context):
        return {"unexpected": "shape"}


class UnrecognizedJobTypeBackend:
    def classify(self, title, context):
        return {"job_type": "SOMETHING_MADE_UP", "confidence": 0.9}


class BadConfidenceBackend:
    def classify(self, title, context):
        return {"job_type": "JRF", "confidence": "not-a-number"}


class OutOfRangeConfidenceBackend:
    def classify(self, title, context):
        return {"job_type": "JRF", "confidence": 5.0}


class WorkingBackend:
    def classify(self, title, context):
        return {"job_type": "SRF", "confidence": 0.9}


def test_classifier_backend_failure_returns_unknown():
    classifier = JobTypeClassifier(backend=RaisingBackend())
    result = classifier.classify("Any title")
    assert result == {"job_type": "UNKNOWN", "confidence": 0.0}


def test_classifier_backend_timeout_does_not_crash_and_returns_unknown():
    classifier = JobTypeClassifier(backend=TimeoutBackend())
    result = classifier.classify("Any title")
    assert result == {"job_type": "UNKNOWN", "confidence": 0.0}


def test_classifier_malformed_response_returns_unknown():
    classifier = JobTypeClassifier(backend=MalformedJsonBackend())
    assert classifier.classify("x") == {"job_type": "UNKNOWN", "confidence": 0.0}


def test_classifier_missing_fields_returns_unknown():
    classifier = JobTypeClassifier(backend=MissingFieldsBackend())
    assert classifier.classify("x") == {"job_type": "UNKNOWN", "confidence": 0.0}


def test_classifier_unrecognized_job_type_returns_unknown():
    classifier = JobTypeClassifier(backend=UnrecognizedJobTypeBackend())
    assert classifier.classify("x") == {"job_type": "UNKNOWN", "confidence": 0.0}


def test_classifier_non_numeric_confidence_returns_unknown():
    classifier = JobTypeClassifier(backend=BadConfidenceBackend())
    assert classifier.classify("x") == {"job_type": "UNKNOWN", "confidence": 0.0}


def test_classifier_out_of_range_confidence_is_clamped_not_rejected():
    classifier = JobTypeClassifier(backend=OutOfRangeConfidenceBackend())
    result = classifier.classify("x")
    assert result["job_type"] == "JRF"
    assert result["confidence"] == 1.0


def test_classifier_working_backend_passes_through():
    classifier = JobTypeClassifier(backend=WorkingBackend())
    result = classifier.classify("x")
    assert result == {"job_type": "SRF", "confidence": 0.9}


def test_classifier_default_backend_is_rule_based_and_never_makes_network_calls():
    classifier = JobTypeClassifier()
    assert isinstance(classifier.backend, RuleBasedJobTypeBackend)
    result = classifier.classify("Junior Research Fellow (JRF)")
    assert result["job_type"] == "JRF"


def test_all_job_types_constant_includes_unknown():
    assert "UNKNOWN" in JOB_TYPES
    assert "JRF" in JOB_TYPES
    assert "OTHER_RESEARCH" in JOB_TYPES


# ---------------------------------------------------------------------------
# build_default_classifier — final architecture: rule-based only, no
# environment configuration, no network access, no AI dependency.
# ---------------------------------------------------------------------------


def test_build_default_classifier_is_rule_based_only():
    classifier = build_default_classifier()
    assert isinstance(classifier.backend, RuleBasedJobTypeBackend)


def test_build_default_classifier_requires_no_environment_configuration(monkeypatch):
    """No AI-related env vars exist anymore — build_default_classifier()
    must work identically regardless of what's in the environment."""
    for var in ("JOB_TYPE_AI_API_KEY", "JOB_TYPE_AI_BASE_URL", "JOB_TYPE_AI_MODEL", "JOB_TYPE_AI_TIMEOUT_SECONDS"):
        monkeypatch.delenv(var, raising=False)
    classifier = build_default_classifier()
    assert isinstance(classifier.backend, RuleBasedJobTypeBackend)
    result = classifier.classify("Junior Research Fellow (JRF)")
    assert result["job_type"] == "JRF"


def test_module_has_no_network_dependency():
    """The final architecture makes zero outbound network calls — no
    `requests`, no HTTP client, no AI SDK anywhere in this module."""
    import inspect

    source = inspect.getsource(__import__("ai.job_type_classifier", fromlist=["_"]))
    assert "import requests" not in source
    assert "requests.post" not in source
    assert "openai" not in source.lower()
    assert "api_key" not in source.lower()
