"""Job-type classification for VALID recruitment notifications.

This runs strictly AFTER `NotificationValidator` has already classified a
candidate VALID — it never sees INVALID or REVIEW candidates, and it has
no way to change a candidate's VALID/INVALID/REVIEW status. Its only job
is to further categorize an already-actionable opening (JRF, SRF,
Postdoctoral, Faculty, ...) so the email digest can group by role type.

Final architecture: rule-based only. No AI backend, no external API, no
network access, no API key, no runtime cost. `RuleBasedJobTypeBackend` is
a deterministic keyword classifier and is the sole production backend.

`JobTypeBackend` is kept as a minimal Protocol so `JobTypeClassifier`
stays backend-agnostic (useful for tests), but no second implementation
ships in production.

Failure safety is the whole point of the `JobTypeClassifier` facade: no
matter what the backend does — raises, returns malformed data, returns an
unrecognized job_type — `classify()` always returns a valid
`{"job_type": ..., "confidence": ...}` dict, defaulting to UNKNOWN. A
classifier failure must never propagate and never block scraping,
persistence, PDF processing, or email.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

JOB_TYPES: tuple[str, ...] = (
    "JRF",
    "SRF",
    "PROJECT_ASSISTANT",
    "PROJECT_ASSOCIATE",
    "RESEARCH_ASSISTANT",
    "RESEARCH_ASSOCIATE",
    "SCIENTIST",
    "FACULTY",
    "POSTDOCTORAL",
    "CONSULTANT",
    "TECHNICAL",
    "ADMINISTRATIVE",
    "APPRENTICE",
    "INTERNSHIP",
    "FELLOWSHIP",
    "OTHER_RESEARCH",
    "GENERAL_RECRUITMENT",
    "UNKNOWN",
)

UNKNOWN_RESULT: dict[str, Any] = {"job_type": "UNKNOWN", "confidence": 0.0}


class JobTypeBackend(Protocol):
    """Provider abstraction — kept minimal so `JobTypeClassifier` doesn't
    hard-code a single implementation. `RuleBasedJobTypeBackend` is the
    only backend used in production."""

    def classify(self, title: str, context: str) -> dict[str, Any]:
        """Return {"job_type": <one of JOB_TYPES>, "confidence": <0..1>}.
        May raise — `JobTypeClassifier` is responsible for catching it."""
        ...


class RuleBasedJobTypeBackend:
    """Deterministic keyword classifier. No network access, no API key,
    no cost — this is the sole production backend.

    Only ever looks at title + context (notification summary/content) —
    never a URL. A URL fragment like "research-admission.example.edu"
    must never drive a classification; the caller (`NotificationService`)
    already only passes `title` and `parsed_notification.summary`, never
    the URL, so this backend has no way to key off it even accidentally.
    """

    # Checked in order; first match wins. Ordered most-specific first so
    # e.g. "Postdoctoral Fellow" resolves to POSTDOCTORAL before the
    # broader FELLOWSHIP pattern gets a chance, and generic/ambiguous
    # text (an award, a scheme, a directory, a conference) never collides
    # with a specific role pattern just because a keyword appears nearby.
    _PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
        ("JRF", re.compile(r"\bjrf\b|junior research fellow", re.IGNORECASE)),
        ("SRF", re.compile(r"\bsrf\b|senior research fellow", re.IGNORECASE)),
        ("PROJECT_ASSOCIATE", re.compile(r"project associate", re.IGNORECASE)),
        ("PROJECT_ASSISTANT", re.compile(r"project assistant", re.IGNORECASE)),
        ("RESEARCH_ASSOCIATE", re.compile(r"research associate", re.IGNORECASE)),
        ("RESEARCH_ASSISTANT", re.compile(r"research assistant", re.IGNORECASE)),
        ("POSTDOCTORAL", re.compile(r"post[- ]?doctoral|\bpostdoc\b", re.IGNORECASE)),
        ("FACULTY", re.compile(
            r"assistant professor|associate professor|\bprofessor\b|temporary faculty"
            r"|\bfaculty\b(?!\s+directory)",
            re.IGNORECASE,
        )),
        ("CONSULTANT", re.compile(r"\bconsultant(s)?\b", re.IGNORECASE)),
        ("APPRENTICE", re.compile(r"\bapprentice(ship)?\b", re.IGNORECASE)),
        ("INTERNSHIP", re.compile(r"\binternship\b|\bintern\b", re.IGNORECASE)),
        ("TECHNICAL", re.compile(r"technical assistant|\btechnician\b", re.IGNORECASE)),
        ("ADMINISTRATIVE", re.compile(r"\badministrative\b", re.IGNORECASE)),
        ("FELLOWSHIP", re.compile(r"\bfellowship\b(?!\s+scheme)|\bresearch fellow\b", re.IGNORECASE)),
        ("SCIENTIST", re.compile(r"\bscientist\b(?!\s+award)", re.IGNORECASE)),
        ("GENERAL_RECRUITMENT", re.compile(
            r"\brecruitment\b|\bvacanc(?:y|ies)\b|walk-in interview|\bvarious posts?\b",
            re.IGNORECASE,
        )),
    )

    def classify(self, title: str, context: str = "") -> dict[str, Any]:
        text = f"{title or ''} {context or ''}"
        for job_type, pattern in self._PATTERNS:
            if pattern.search(text):
                confidence = 0.85 if job_type != "GENERAL_RECRUITMENT" else 0.4
                return {"job_type": job_type, "confidence": confidence}
        return {"job_type": "OTHER_RESEARCH", "confidence": 0.3}


class JobTypeClassifier:
    """Facade with mandatory fail-safe behavior. Always returns a valid
    result dict — never raises, never returns something outside
    `JOB_TYPES`, never returns a confidence outside [0, 1]."""

    def __init__(self, backend: JobTypeBackend | None = None) -> None:
        self.backend = backend or RuleBasedJobTypeBackend()

    def classify(self, title: str, context: str = "") -> dict[str, Any]:
        try:
            result = self.backend.classify(title, context)
        except Exception:
            return dict(UNKNOWN_RESULT)

        if not isinstance(result, dict):
            return dict(UNKNOWN_RESULT)

        job_type = result.get("job_type")
        if job_type not in JOB_TYPES:
            return dict(UNKNOWN_RESULT)

        try:
            confidence = float(result.get("confidence"))
        except (TypeError, ValueError):
            return dict(UNKNOWN_RESULT)
        confidence = max(0.0, min(1.0, confidence))

        return {"job_type": job_type, "confidence": confidence}


def build_default_classifier() -> JobTypeClassifier:
    """Build the production classifier: rule-based only, no configuration
    required, no network access, no external dependency."""
    return JobTypeClassifier(backend=RuleBasedJobTypeBackend())
