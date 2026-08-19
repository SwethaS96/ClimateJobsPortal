"""Tests for services.notification_validator.NotificationValidator."""

from __future__ import annotations

import pytest

from parser.models import ParsedNotification
from services.notification_validator import Classification, NotificationValidator


def classify(title: str, url: str = "https://example.org/notice"):
    validator = NotificationValidator()
    return validator.classify(ParsedNotification(title=title, url=url))


@pytest.mark.parametrize(
    "title",
    [
        "Careers",
        "Retired Scientist",
        "Scientist Directory",
        "Recruitment Results",
        "Selected Candidates",
        "Interview Results",
    ],
)
def test_known_non_actionable_titles_are_invalid(title: str) -> None:
    result = classify(title)
    assert result.status == Classification.INVALID
    assert result.reason


@pytest.mark.parametrize(
    "title",
    [
        "RA Advertisement",
        "Invitation for Applications",
        "JRF Recruitment",
        "Project Associate Vacancy",
        "Research Assistant",
    ],
)
def test_known_actionable_titles_are_valid(title: str) -> None:
    result = classify(title)
    assert result.status == Classification.VALID
    assert result.reason


def test_empty_title_is_invalid() -> None:
    result = classify("")
    assert result.status == Classification.INVALID


def test_whitespace_only_title_is_invalid() -> None:
    result = classify("   ")
    assert result.status == Classification.INVALID


def test_no_signal_title_is_review_not_invalid_or_valid() -> None:
    result = classify("Departmental Update")
    assert result.status == Classification.REVIEW
    assert result.reason


def test_hard_negative_overrides_positive_keyword_in_same_title() -> None:
    """'Recruitment Results' contains 'recruitment' (positive) but also a
    concluded-process signal ('results') — the result must win: nothing is
    actually open to apply for."""
    result = classify("Recruitment Results")
    assert result.status == Classification.INVALID
    assert "result" in result.reason.lower()


def test_result_substring_does_not_reject_unrelated_recruitment_titles() -> None:
    """Guard against over-matching: a genuine advertisement title with no
    outcome-related wording must stay VALID."""
    result = classify("Advertisement for Research Associate Position")
    assert result.status == Classification.VALID


def test_soft_negative_is_overridden_by_a_genuine_positive_signal() -> None:
    """Unlike 'results', a page-type word like 'faculty' can appear in a
    genuine notice ('Faculty Recruitment 2026') — a real positive signal
    should still win, otherwise real openings would be silently dropped."""
    result = classify("Faculty Recruitment 2026")
    assert result.status == Classification.VALID


def test_soft_negative_alone_without_positive_signal_is_invalid() -> None:
    result = classify("Faculty")
    assert result.status == Classification.INVALID


def test_negative_pattern_matched_via_url_is_still_rejected() -> None:
    result = classify("Learn More", url="https://example.org/staff-directory")
    assert result.status == Classification.INVALID


def test_is_valid_matches_classify_status() -> None:
    validator = NotificationValidator()

    valid = ParsedNotification(title="RA Advertisement", url="https://example.org/1")
    invalid = ParsedNotification(title="Careers", url="https://example.org/careers")
    review = ParsedNotification(title="Departmental Update", url="https://example.org/2")

    assert validator.is_valid(valid) is True
    assert validator.is_valid(invalid) is False
    assert validator.is_valid(review) is False


@pytest.mark.parametrize(
    "title",
    ["Home", "About Us", "Contact", "Gallery", "Annual Report 2026", "Tenders", "Login", "Privacy Policy"],
)
def test_legacy_navigation_titles_remain_invalid(title: str) -> None:
    assert classify(title).status == Classification.INVALID


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/List%20of%20Selected%20Candidates-JRF%202026_0.pdf",
        "https://example.org/list%20of%20selected%20candidates-jrf%202026_0.pdf",
        "https://example.org/List%20Of%20SELECTED%20candidates.pdf",
        "https://example.org/List  of  Selected   Candidates.pdf",
        "https://example.org/List-of-Selected_Candidates.pdf",
    ],
)
def test_url_encoded_selected_candidates_is_hard_negative_regardless_of_jrf(url: str) -> None:
    """Regression for Phase 24: '%20' between 'Selected' and 'Candidates'
    previously defeated the 'selected candidates' hard-negative pattern, so
    a results PDF slipped through as VALID just because 'jrf' also matched.
    A concluded-process signal must win no matter how it's encoded."""
    result = classify("Click here for details", url=url)
    assert result.status == Classification.INVALID
    assert "selected candidates" in result.reason.lower() or "result" in result.reason.lower()


def test_url_decoded_selected_candidates_title_is_hard_negative() -> None:
    result = classify("Selected Candidates-JRF 2026")
    assert result.status == Classification.INVALID


@pytest.mark.parametrize(
    "title",
    [
        "Selected Candidates-JRF 2026.pdf",
        "SELECTED CANDIDATES - SRF 2026",
        "Selected   Candidates   (Vacancy   Advertisement)",
    ],
)
def test_selected_candidates_beats_jrf_srf_vacancy_advertisement_fellowship(title: str) -> None:
    """A strong concluded-process signal must not become VALID merely
    because it also contains JRF/SRF/recruitment/vacancy/advertisement/
    fellowship — the hard negative always wins."""
    result = classify(title)
    assert result.status == Classification.INVALID


@pytest.mark.parametrize(
    "title",
    ["Recruitment Advertisement", "Recruitment 2026", "Recruitment Notification", "Recruitment — Project Scientist"],
)
def test_recruitment_with_action_or_year_signal_is_valid(title: str) -> None:
    result = classify(title)
    assert result.status == Classification.VALID


def test_recruitment_policy_document_is_invalid() -> None:
    """Regression for Phase 24's IIGM false positive: bare 'recruitment'
    matched an HR policy/rules document, not an open opportunity."""
    result = classify("Recruitment Assessment and Promotion Rules")
    assert result.status == Classification.INVALID


def test_bare_recruitment_alone_is_not_automatically_valid() -> None:
    result = classify("Recruitment")
    assert result.status != Classification.VALID


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/recruitment%20advertisement",
        "https://example.org/recruitment-notification-2026",
    ],
)
def test_url_encoded_recruitment_context_words_are_recognized(url: str) -> None:
    result = classify("Details", url=url)
    assert result.status == Classification.VALID


def test_bare_careers_landing_page_remains_invalid() -> None:
    result = classify("Careers")
    assert result.status == Classification.INVALID


@pytest.mark.parametrize(
    "title",
    ["Careers — Research Associate Recruitment", "Careers — Project Scientist Vacancy"],
)
def test_careers_with_genuine_opportunity_signal_remains_valid(title: str) -> None:
    result = classify(title)
    assert result.status == Classification.VALID


# ---------------------------------------------------------------------------
# normalize_for_matching
# ---------------------------------------------------------------------------


def test_normalize_for_matching_url_decodes_percent_encoding() -> None:
    from services.notification_validator import normalize_for_matching

    assert normalize_for_matching("Selected%20Candidates") == "selected candidates"


def test_normalize_for_matching_lowercases() -> None:
    from services.notification_validator import normalize_for_matching

    assert normalize_for_matching("SELECTED CANDIDATES") == "selected candidates"


def test_normalize_for_matching_collapses_repeated_whitespace() -> None:
    from services.notification_validator import normalize_for_matching

    assert normalize_for_matching("Selected    Candidates") == "selected candidates"


def test_normalize_for_matching_collapses_separators() -> None:
    from services.notification_validator import normalize_for_matching

    assert normalize_for_matching("Selected-Candidates") == "selected candidates"
    assert normalize_for_matching("Selected_Candidates") == "selected candidates"


def test_normalize_for_matching_handles_none_and_empty() -> None:
    from services.notification_validator import normalize_for_matching

    assert normalize_for_matching(None) == ""
    assert normalize_for_matching("") == ""


def test_normalize_for_matching_does_not_mutate_original_url() -> None:
    """The classifier must only normalize its own matching representation
    — the ParsedNotification's stored url must stay untouched."""
    original_url = "https://example.org/List%20of%20Selected%20Candidates.pdf"
    notification = ParsedNotification(title="Click here", url=original_url)
    NotificationValidator().classify(notification)
    assert notification.url == original_url


# ---------------------------------------------------------------------------
# Phase 27 Part A — recruitment + year requires adjacency, not just presence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Recruitment 2026",
        "Recruitment Advertisement 2026",
        "Recruitment Notification 2026",
        "Recruitment Project Scientist 2026",
        "Recruitment Vacancy 2026",
    ],
)
def test_recruitment_with_year_and_or_action_word_remains_valid(title: str) -> None:
    assert classify(title).status == Classification.VALID


@pytest.mark.parametrize(
    "title",
    [
        "Recruitment Handbook 2025",
        "Recruitment Policy 2026",
        "Recruitment Rules 2026",
        "Recruitment Assessment and Promotion Rules",
        "Annual Recruitment Report 2026",
    ],
)
def test_recruitment_with_year_but_policy_document_wording_is_invalid(title: str) -> None:
    """Regression for Phase 27: a year anywhere in the text previously made
    'recruitment' actionable regardless of what else was said. A year only
    counts when directly adjacent to 'recruitment' — a policy/handbook/
    rules/report noun in between must not be treated as actionable."""
    result = classify(title)
    assert result.status == Classification.INVALID


# ---------------------------------------------------------------------------
# Phase 27 Part B — URL filename tokens can't independently create VALID
# ---------------------------------------------------------------------------


def test_unrelated_title_with_positive_word_only_in_pdf_filename_is_not_valid() -> None:
    """Regression for Phase 27: a PDF filename like
    'advertisement_scst_cell.pdf' previously made an unrelated anchor VALID
    purely because 'advertisement' appeared inside the filename. The
    visible title has nothing to do with recruitment, so this must not be
    VALID — INVALID or REVIEW are both acceptable outcomes."""
    result = classify("Citizen Charter", url="https://example.org/pdf/advertisement_scst_cell.pdf")
    assert result.status != Classification.VALID


def test_positive_word_buried_in_longer_filename_segment_is_not_valid_alone() -> None:
    result = classify("Policy Update", url="https://example.org/files/some_consultant_policy_doc.pdf")
    assert result.status != Classification.VALID


def test_url_path_segment_exactly_matching_positive_pattern_is_valid() -> None:
    """A clean path segment ('/vacancies/45') is meaningful context, unlike
    a filename token — the title has no signal here, only the URL does."""
    result = classify("Notice", url="https://example.org/vacancies/45")
    assert result.status == Classification.VALID


def test_url_path_segment_matching_consultant_is_valid() -> None:
    result = classify("Notice", url="https://example.org/consultant/engagement-2026")
    assert result.status == Classification.VALID


def test_url_evidence_supports_an_already_positive_title() -> None:
    """URL context may reinforce an already-positive title — this must
    keep working exactly as before."""
    result = classify("Advertisement for Research Associate Position", url="https://example.org/recruitment/1")
    assert result.status == Classification.VALID


# ---------------------------------------------------------------------------
# Phase 27 Part C — short recruitment labels, gated by page source
# ---------------------------------------------------------------------------


def test_short_recruitment_label_on_recruitment_page_is_valid() -> None:
    result = NotificationValidator().classify(
        ParsedNotification(title="Recruitment", url="https://example.org/recruitment"),
        page_is_recruitment_source=True,
    )
    assert result.status == Classification.VALID


def test_short_recruitment_label_on_homepage_is_not_promoted() -> None:
    """Without page_is_recruitment_source, behavior is unchanged — a bare
    'Recruitment' label still has no basis for a positive decision."""
    result = classify("Recruitment")
    assert result.status != Classification.VALID


def test_employment_opportunity_label_on_recruitment_page_is_valid() -> None:
    result = NotificationValidator().classify(
        ParsedNotification(title="Employment Opportunity", url="https://example.org/careers/1"),
        page_is_recruitment_source=True,
    )
    assert result.status == Classification.VALID


def test_jobs_label_on_recruitment_page_is_valid() -> None:
    result = NotificationValidator().classify(
        ParsedNotification(title="Jobs", url="https://example.org/jobs"),
        page_is_recruitment_source=True,
    )
    assert result.status == Classification.VALID


def test_page_is_recruitment_source_does_not_override_hard_negatives() -> None:
    """A concluded-process signal still wins even on a recruitment page —
    the short-label promotion must not bypass hard negatives."""
    result = NotificationValidator().classify(
        ParsedNotification(title="Recruitment Results", url="https://example.org/recruitment"),
        page_is_recruitment_source=True,
    )
    assert result.status == Classification.INVALID


def test_page_is_recruitment_source_does_not_promote_longer_titles() -> None:
    """Only the short, bare label is promoted — a longer, unrelated title
    on the same page must not be swept in."""
    result = NotificationValidator().classify(
        ParsedNotification(title="Departmental Update", url="https://example.org/recruitment"),
        page_is_recruitment_source=True,
    )
    assert result.status == Classification.REVIEW


# ---------------------------------------------------------------------------
# is_recruitment_source_page
# ---------------------------------------------------------------------------


def test_is_recruitment_source_page_true_for_dedicated_pages() -> None:
    from services.notification_validator import is_recruitment_source_page

    assert is_recruitment_source_page("Recruitment") is True
    assert is_recruitment_source_page("Careers") is True
    assert is_recruitment_source_page("Jobs") is True


def test_is_recruitment_source_page_false_for_homepage_even_if_it_mentions_careers() -> None:
    from services.notification_validator import is_recruitment_source_page

    page_name = "Announcements / Careers (homepage — no dedicated page confirmed)"
    assert is_recruitment_source_page(page_name) is False


def test_is_recruitment_source_page_false_for_none_and_empty() -> None:
    from services.notification_validator import is_recruitment_source_page

    assert is_recruitment_source_page(None) is False
    assert is_recruitment_source_page("") is False


# ---------------------------------------------------------------------------
# Phase 33 — evidence-based filtering from Phase 32's production audit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "New Circular and Application form regarding State Awards to universities teachers for the year 2026",
        "Application for the Sir C.V. Raman Scientist Award 2026",
        "Dr. Sarvepalli Radhakrishnan Award for 'Best Academician of the Year - 2026' - Applications from eligible teachers",
        "Fellowship Schemes",
        "Scholarships and Fellowships",
        "AICTE scholarship/fellowship schemes",
        "Non-NET Fellowship Guidelines",
        "Admission Notice Advertisement for Admissions to Online Learning (OL) Programmes",
        "Admission Advertisement for Online Learning (OL) PG Programmes",
        "Office order regarding withdrawal of advertisement for various Non-Teaching positions",
        "Merit list of JRF in INMAS DRDO project",
        "Shortlist and Interview call letter for JRF in EE Dept.",
        "Tender for supply of laboratory equipment",
        "Expression of Interest (EOI) for catering services",
    ],
)
def test_phase32_confirmed_false_positives_are_no_longer_valid(title: str) -> None:
    """Regression for Phase 33: these exact titles (or close variants) were
    found VALID in Phase 32's production audit of 931 unsent notifications
    and confirmed as false positives. None may be VALID now."""
    result = classify(title)
    assert result.status != Classification.VALID


def test_tender_matched_by_title_is_rejected() -> None:
    result = classify("Tender for supply of laboratory equipment")
    assert result.status == Classification.INVALID


def test_tender_folder_in_url_alone_does_not_reject_a_well_described_recruitment_title() -> None:
    """Phase 33 finding: promoting bare 'tender' to a URL-scanned hard
    negative (to catch NIT Nagaland's tender PDFs mislabeled
    'Advertisement') caused a real regression — Central University of
    Gujarat files genuine recruitment PDFs under a URL literally
    containing 'recruitment_tender/recruitment/...' (one shared folder for
    both). 'tender'/'procurement' are title-only hard negatives now: a
    URL folder name can no longer reject a title that clearly describes a
    real opening. This is a deliberate, evidence-based trade-off — a
    tender PDF with a blank/generic title and no title-level tender
    signal is a narrower, rarer miss than rejecting genuine recruitment
    ads by folder-name coincidence."""
    result = classify(
        "Advertisement for the Engagement of the Project Staff (1 Research Assistant "
        "and 2 Field Investigators)",
        url="https://example.org/flipbook/index.php?pdf=recruitment_tender/recruitment/"
        "Advertisement_for_the_Engagement_of_the_PROJECT_STAFF_final.pdf",
    )
    assert result.status == Classification.VALID


@pytest.mark.parametrize(
    "title",
    [
        "Advertisement for the position of Field Investigator in the Minor Research Project",
        "RA Advertisement - Invitation for Applications",
        "Walk-in-interview/Recruitment for Temporary Faculty",
        "Faculty Recruitment 2026",
        "Advertisement for the post of Junior Research Fellow (JRF) in Physics Department",
        "Senior Research Fellow (SRF)",
        "Project Associate-I (PA-I)",
        "Young Professional-1 (YP-1) and Semi-skilled Worker",
        "Advt. No. IITD/Apprentice (1) / 2025 for engagement of Apprentice",
        "Consultant engagement for various posts",
        "Vacancy for the post of Technical Assistant",
        "Post Doctoral Fellowship",
        "Postdoctoral Fellow position in Climate Science",
    ],
)
def test_genuine_recruitment_examples_remain_valid(title: str) -> None:
    """Regression for Phase 33: none of the new hard/soft negatives or the
    fellowship/application changes may reject genuine recruitment titles
    drawn from real validation-phase evidence."""
    result = classify(title)
    assert result.status == Classification.VALID


@pytest.mark.parametrize(
    "title",
    ["Fellowship 2026", "Fellowship Advertisement", "Fellowship Notification 2026", "Research Fellowship — Applications Invited"],
)
def test_fellowship_with_year_or_action_word_remains_valid(title: str) -> None:
    result = classify(title)
    assert result.status == Classification.VALID


def test_bare_fellowship_alone_is_not_automatically_valid() -> None:
    result = classify("Fellowship")
    assert result.status != Classification.VALID


def test_research_fellow_is_a_positive_pattern() -> None:
    result = classify("Research Fellow position available in the Geophysics Department")
    assert result.status == Classification.VALID


def test_temporary_faculty_is_a_positive_pattern() -> None:
    result = classify("Notification for Temporary Faculty positions")
    assert result.status == Classification.VALID


def test_bare_application_alone_is_not_automatically_valid() -> None:
    """Bare 'application' was removed as an unconditional positive
    (Phase 33) — genuine cases are covered by 'applications invited',
    'invitation for applications', or a specific position-type pattern."""
    result = classify("Application form for Refund of Fees")
    assert result.status != Classification.VALID


def test_applications_invited_phrase_still_works_without_bare_application() -> None:
    result = classify("Applications invited for the post of Junior Research Fellow")
    assert result.status == Classification.VALID


def test_circular_about_internal_promotion_scheme_is_not_valid() -> None:
    result = classify(
        "Circular regarding inviting applications from eligible teachers for promotion "
        "under Career Advancement Scheme"
    )
    assert result.status != Classification.VALID


@pytest.mark.parametrize("title", ["Award of Best Employee 2026", "Awards Ceremony 2026", "Faculty Member Awarded National Honour"])
def test_award_variants_are_hard_negative(title: str) -> None:
    result = classify(title)
    assert result.status == Classification.INVALID


def test_admission_is_hard_negative_even_with_advertisement() -> None:
    result = classify("Admission Advertisement for PhD Programme 2026")
    assert result.status == Classification.INVALID


def test_admission_substring_in_url_domain_does_not_reject_genuine_posting() -> None:
    """Regression for Phase 33: IIT Palakkad hosts a genuine 'Postdoctoral
    Positions' PDF on a domain containing 'research-admission...' — the
    word 'admission' appearing inside an unrelated compound domain name
    must not reject a well-described genuine opening. 'admission' is a
    title-only hard negative for exactly this reason."""
    result = classify(
        "Postdoctoral Positions",
        url="https://resap.iitpkd.ac.in/sites/research-admission.iitp-portal.local/files/notice.pdf",
    )
    assert result.status == Classification.VALID


def test_conference_seminar_soft_negatives_do_not_override_genuine_recruitment() -> None:
    """A soft negative like 'conference' must still be overridden by a
    genuine positive signal in the same title."""
    result = classify("Walk-in-interview for Research Associate — travel support for conference attendance included")
    assert result.status == Classification.VALID


def test_custom_pattern_lists_override_defaults() -> None:
    from services.notification_patterns import PatternReason

    validator = NotificationValidator(
        hard_negative_patterns=(),
        soft_negative_patterns=(PatternReason("archive", "Archived page."),),
        positive_patterns=(PatternReason("opening", "Custom opening pattern."),),
    )

    assert validator.classify(ParsedNotification(title="New Opening", url="https://example.org/1")).status == (
        Classification.VALID
    )
    assert validator.classify(ParsedNotification(title="Archive", url="https://example.org/2")).status == (
        Classification.INVALID
    )
    # "recruitment" is not in the custom positive list and has no negative match either.
    assert validator.classify(ParsedNotification(title="Recruitment", url="https://example.org/3")).status == (
        Classification.REVIEW
    )
