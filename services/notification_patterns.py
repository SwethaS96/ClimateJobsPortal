"""Actionability pattern lists for `NotificationValidator`.

The parser's `RecruitmentRelevanceScorer` (see `parser/keywords.py`) answers
"is this link plausibly about recruitment at all?". These patterns answer a
narrower question at the persistence layer: "is this a *specific, open*
opportunity someone could act on right now?" A page titled "Careers" or
"Scientists" is unmistakably recruitment-*related*, but it is not an
actionable notification — there's nothing there to apply to.

Patterns are matched against a candidate's title and URL as plain
case-insensitive substrings (no NLP), so multi-word phrases are used where a
single word would be too blunt (e.g. "faculty directory" rather than just
"faculty" whenever a bare word would swallow legitimate titles).

Two negative tiers exist because they mean different things:

- HARD negatives describe a *concluded* process (results, selections,
  shortlists). There is nothing actionable behind them no matter what else
  the title says, so they always win — a title like "Recruitment Results"
  is rejected even though it also contains "recruitment".
- SOFT negatives describe a *page type* (a directory, a landing page, a
  procurement notice) rather than a concluded process. A real notice can
  legitimately contain one of these words (e.g. "Faculty Recruitment 2026"),
  so a soft negative only rejects a candidate when no positive pattern is
  also present.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PatternReason:
    """A matchable substring paired with the human-readable reason it implies."""

    pattern: str
    reason: str


# Concluded-process signals: always non-actionable, regardless of any
# positive pattern also present in the same title. This is the original,
# pre-Phase-33 set — proven safe scanning both title and URL over many
# validation phases. All Phase 33 additions go in
# DEFAULT_HARD_NEGATIVE_TITLE_ONLY_PATTERNS below instead (see its
# docstring for why).
DEFAULT_HARD_NEGATIVE_PATTERNS: tuple[PatternReason, ...] = (
    PatternReason("results", "Announces a results/outcome rather than an open opportunity."),
    PatternReason("result", "Announces a result/outcome rather than an open opportunity."),
    PatternReason("selected candidates", "Lists selected candidates rather than an open opportunity."),
    PatternReason("selection list", "A selection list, not an open opportunity."),
    PatternReason("shortlisted", "Announces shortlisted candidates rather than an open opportunity."),
    PatternReason("short list", "A shortlist announcement, not an open opportunity."),
    PatternReason("interview result", "Announces an interview result rather than an open opportunity."),
    PatternReason("final result", "Announces a final result rather than an open opportunity."),
)

# Same "always wins" semantics as the hard negatives above, but checked
# against the TITLE only, never the URL.
#
# Phase 33 additions (evidence: Phase 32's production audit of 931 unsent
# notifications) — admission/award/withdrawal/tender/procurement/merit
# list/shortlist are promoted to hard-negative tier specifically because
# they were observed pre-empted by bare "advertisement"/"application"
# positive matches (e.g. "Admission Notice Advertisement...", "Application
# for the Sir C.V. Raman Scientist Award", "Office order regarding
# withdrawal of advertisement..."). A soft negative wouldn't fix these —
# soft negatives are only checked when no positive pattern already
# matched, and "advertisement" always would.
#
# These are TITLE-ONLY (unlike the pre-existing hard negatives above)
# because URL scanning caused two confirmed real regressions during
# Phase 33 itself: Central University of Gujarat files genuine
# recruitment PDFs under a URL containing "recruitment_tender/
# recruitment/..." (a shared tender+recruitment folder), and IIT
# Palakkad hosts a genuine "Postdoctoral Positions" PDF on a domain
# containing "research-admission..." — both rejected a well-described
# genuine opening purely because of an unrelated compound domain/folder
# name. New, still-being-proven patterns default to title-only; only the
# original set above has earned URL-scanning through repeated validation.
DEFAULT_HARD_NEGATIVE_TITLE_ONLY_PATTERNS: tuple[PatternReason, ...] = (
    PatternReason("shortlist", "A shortlist/shortlisting announcement, not an open opportunity."),
    PatternReason("merit list", "A merit list, not an open opportunity."),
    PatternReason("admission", "Student admission notice, not a recruitment opportunity."),
    PatternReason("admissions", "Student admissions notice, not a recruitment opportunity."),
    PatternReason("award", "Award/achievement notice, not an open opportunity."),
    PatternReason("awards", "Awards/achievement notice, not an open opportunity."),
    PatternReason("awarded", "Announces an award already given, not an open opportunity."),
    PatternReason("withdrawal", "Announces a withdrawal, not an open opportunity."),
    PatternReason("cancelled", "Announces a cancellation, not an open opportunity."),
    PatternReason("cancellation", "Announces a cancellation, not an open opportunity."),
    PatternReason("tender", "Tender notice, not a recruitment opportunity."),
    PatternReason("procurement", "Procurement notice, not a recruitment opportunity."),
)

# Page-type/landing-page signals: non-actionable only when no positive
# pattern is also present.
DEFAULT_SOFT_NEGATIVE_PATTERNS: tuple[PatternReason, ...] = (
    PatternReason("retired scientist", "Retired scientist listing, not an open opportunity."),
    PatternReason("scientists", "Scientist directory page, not a specific opportunity."),
    PatternReason("faculty directory", "Faculty directory page, not a specific opportunity."),
    PatternReason("staff directory", "Staff directory page, not a specific opportunity."),
    PatternReason("faculty", "Faculty listing page, not a specific opportunity."),
    PatternReason("directory", "Staff/personnel directory page, not a specific opportunity."),
    PatternReason("careers", "Careers landing page, not a specific opportunity."),
    PatternReason("home", "Generic site navigation page, not a recruitment notice."),
    PatternReason("about", "Generic 'about' page, not a recruitment notice."),
    PatternReason("contact", "Contact page, not a recruitment notice."),
    PatternReason("gallery", "Photo/media gallery page, not a recruitment notice."),
    PatternReason("annual report", "Annual report, not a recruitment notice."),
    PatternReason("login", "Login page, not a recruitment notice."),
    PatternReason("privacy policy", "Privacy policy page, not a recruitment notice."),
    PatternReason("promotion rules", "Recruitment/promotion rules or policy document, not an open opportunity."),
    PatternReason("rules", "Rules/regulations document, not an open opportunity."),
    PatternReason("policy", "Policy document, not an open opportunity."),
    PatternReason("handbook", "Handbook/manual document, not an open opportunity."),
    PatternReason("report", "Report document, not an open opportunity."),
    PatternReason("guideline", "Guidelines document, not an open opportunity."),
    PatternReason("guidelines", "Guidelines document, not an open opportunity."),
    PatternReason("scheme", "Informational scheme/portal page, not a specific opportunity."),
    PatternReason("schemes", "Informational scheme/portal page, not a specific opportunity."),
    PatternReason("scholarship", "Scholarship scheme/portal, not a recruitment opportunity."),
    PatternReason("scholarships", "Scholarship scheme/portal, not a recruitment opportunity."),
    PatternReason("circular", "Administrative circular, not necessarily a recruitment notice."),
    PatternReason("office order", "Internal office order, not necessarily a recruitment notice."),
    PatternReason("office memorandum", "Internal office memorandum, not necessarily a recruitment notice."),
    PatternReason("conference", "Conference notice, not a recruitment opportunity."),
    PatternReason("seminar", "Seminar notice, not a recruitment opportunity."),
    PatternReason("symposium", "Symposium notice, not a recruitment opportunity."),
    PatternReason("webinar", "Webinar notice, not a recruitment opportunity."),
)

# Bare "recruitment" is deliberately NOT in DEFAULT_POSITIVE_PATTERNS below.
# On its own the word only names a process — "Recruitment Assessment and
# Promotion Rules" is a policy document, not a notice — so it is too weak a
# signal to trust unconditionally (real-world evidence: Phase 24's IIGM
# audit). `NotificationValidator` instead treats "recruitment" as
# actionable only when it co-occurs with one of these opportunity/action
# words, or with a 4-digit year (a dated recruitment cycle, e.g.
# "Recruitment 2026"). This keeps the exception narrow and explainable
# rather than growing the negative-pattern blacklist.
RECRUITMENT_CONTEXT_WORDS: tuple[str, ...] = (
    "advertisement",
    "notification",
    "vacancy",
    "vacancies",
    "applications",
    "apply",
    "position",
    "post",
    "project",
    "scientist",
    "assistant",
    "fellow",
    "consultant",
    "apprentice",
)

# Same idea as bare "recruitment" above, applied to bare "fellowship"
# (Phase 33 evidence: "Fellowship Schemes", "Scholarships and Fellowships",
# "AICTE scholarship/fellowship schemes" were all landing/informational
# pages, not openings, yet matched the old unconditional "fellowship"
# positive pattern). Deliberately excludes "fellow" from
# RECRUITMENT_CONTEXT_WORDS above — "fellow" is a substring of
# "fellowship" itself, so reusing that list verbatim would make the
# co-occurrence check trivially always true.
FELLOWSHIP_CONTEXT_WORDS: tuple[str, ...] = tuple(
    word for word in RECRUITMENT_CONTEXT_WORDS if word != "fellow"
)

# Page names that indicate a website's configured page IS a dedicated
# recruitment/careers source rather than a generic homepage that merely
# mentions careers in passing. Used by `is_recruitment_source_page` to
# gate the short-label promotion below — see SHORT_RECRUITMENT_LABELS.
RECRUITMENT_SOURCE_PAGE_KEYWORDS: tuple[str, ...] = (
    "recruitment",
    "careers",
    "jobs",
    "employment",
    "vacancies",
)

# Short, generic anchor text that names a recruitment section rather than
# a specific opening ("Recruitment", "Jobs", "Employment Opportunity").
# Real-world evidence (Phase 26) showed these sitting in REVIEW even when
# they are literally the page's own recruitment-section link — but only
# promoting them when we already know (via `is_recruitment_source_page`)
# that the page itself is a configured recruitment/careers/jobs source, not
# a homepage where the same bare word is just ambiguous navigation.
SHORT_RECRUITMENT_LABELS: tuple[str, ...] = (
    "recruitment",
    "recruitments",
    "jobs",
    "job openings",
    "employment",
    "employment opportunity",
)

# Bare "fellowship" and bare "application" are deliberately NOT in this
# list (Phase 33) — see FELLOWSHIP_CONTEXT_WORDS above for "fellowship";
# "application" was dropped outright since no confirmed genuine notice in
# any real-world validation phase relied on it as its *only* signal (every
# genuine case was already independently covered by "applications
# invited"/"invitation for applications" or a specific position-type
# pattern below), while it was directly implicated in real false positives
# ("Application for the Sir C.V. Raman Scientist Award", DU's "Application
# form for Refund of Fees").
DEFAULT_POSITIVE_PATTERNS: tuple[PatternReason, ...] = (
    PatternReason("vacancy", "Open vacancy advertisement."),
    PatternReason("vacancies", "Open vacancies advertisement."),
    PatternReason("advertisement", "Open recruitment/application advertisement."),
    PatternReason("invitation for applications", "Invites applications for an open opportunity."),
    PatternReason("applications invited", "Invites applications for an open opportunity."),
    PatternReason("apply", "Invites applications for an open opportunity."),
    PatternReason("research associate", "Research Associate opening."),
    PatternReason("research assistant", "Research Assistant opening."),
    PatternReason("research fellow", "Research Fellow opening."),
    PatternReason("project associate", "Project Associate opening."),
    PatternReason("project assistant", "Project Assistant opening."),
    PatternReason("project scientist", "Project Scientist opening."),
    PatternReason("scientist recruitment", "Scientist recruitment opening."),
    PatternReason("jrf", "Junior Research Fellow (JRF) opening."),
    PatternReason("srf", "Senior Research Fellow (SRF) opening."),
    PatternReason("junior research fellow", "Junior Research Fellow opening."),
    PatternReason("senior research fellow", "Senior Research Fellow opening."),
    PatternReason("postdoctoral", "Postdoctoral opening."),
    PatternReason("post-doctoral", "Postdoctoral opening."),
    PatternReason("technical assistant", "Technical Assistant opening."),
    PatternReason("project staff", "Project staff opening."),
    PatternReason("consultant", "Consultant engagement opening."),
    PatternReason("young professional", "Young Professional opening."),
    PatternReason("apprentice", "Apprenticeship opening."),
    PatternReason("walk-in interview", "Walk-in interview for an open opportunity."),
    PatternReason("temporary faculty", "Temporary Faculty opening."),
    PatternReason("faculty recruitment", "Faculty recruitment opening."),
)
