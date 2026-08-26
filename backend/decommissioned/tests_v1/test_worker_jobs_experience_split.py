"""_split_role_header() parses a CV experience role-start line into its
structured components. _make_experience_entry() has always read
entry.get("company")/.get("title")/.get("start_date")/.get("end_date"),
but nothing upstream ever set those keys — every experience item's
structured fields came out None regardless of heading detection. This
tests the line-splitting logic in isolation (no DB needed).

app.workers.worker_jobs imports docling at module level for its (unrelated)
extraction tasks — stubbed out below, same pattern as
test_trial_session_cleanup.py, so this file can import the real module
without installing a multi-GB ML dependency.
"""

import sys
import types

if "docling" not in sys.modules:
    _base_models = types.ModuleType("docling.datamodel.base_models")
    _base_models.InputFormat = object
    _pipeline_options = types.ModuleType("docling.datamodel.pipeline_options")
    _pipeline_options.PdfPipelineOptions = object
    _document_converter = types.ModuleType("docling.document_converter")
    _document_converter.DocumentConverter = object
    _document_converter.PdfFormatOption = object
    _document_converter.WordFormatOption = object
    _docling_core_io = types.ModuleType("docling_core.types.io")
    _docling_core_io.DocumentStream = object

    sys.modules["docling"] = types.ModuleType("docling")
    sys.modules["docling.datamodel"] = types.ModuleType("docling.datamodel")
    sys.modules["docling.datamodel.base_models"] = _base_models
    sys.modules["docling.datamodel.pipeline_options"] = _pipeline_options
    sys.modules["docling.document_converter"] = _document_converter
    sys.modules["docling_core"] = types.ModuleType("docling_core")
    sys.modules["docling_core.types"] = types.ModuleType("docling_core.types")
    sys.modules["docling_core.types.io"] = _docling_core_io

from app.workers.worker_jobs import (
    _split_role_header,
    _reclaim_title_company,
    _looks_like_role_label,
)


def test_comma_separated_title_company():
    entry = _split_role_header("UX Design Manager, OSB Group | April 2022 - Present")
    assert entry["title"] == "UX Design Manager"
    assert entry["company"] == "OSB Group"
    assert entry["current"] is True
    assert entry["start_date"] == "2022-04-01"
    assert entry["end_date"] is None


def test_dash_separated_company_then_title():
    entry = _split_role_header("OSB Group — UX Design Manager (Apr 2022 - Present)")
    assert entry["title"] == "UX Design Manager"
    assert entry["company"] == "OSB Group"
    assert entry["current"] is True


def test_at_separated_title_company():
    entry = _split_role_header("Software Engineer at Acme Corp, Jan 2020 - Dec 2021")
    assert entry["title"] == "Software Engineer"
    assert "Acme Corp" in entry["company"]
    assert entry["current"] is False
    assert entry["start_date"] == "2020-01-01"
    assert entry["end_date"] == "2021-12-01"


def test_bare_year_range():
    entry = _split_role_header("Product Designer, Do Health — 2020 - 2022")
    assert entry["start_date"] == "2020-01-01"
    assert entry["end_date"] == "2022-01-01"
    assert entry["current"] is False


def test_unsplittable_line_leaves_title_company_none():
    """No recognized separator between title and company — must not guess."""
    entry = _split_role_header("Senior Product Design Role Apr 2022 - Present")
    assert entry["title"] is None
    assert entry["company"] is None
    assert entry["current"] is True


class TestReclaimTitleCompany:
    """Real CVs (confirmed against an actual PDF export) often lay a role
    out as three standalone lines — TITLE, COMPANY, then the date range —
    rather than combining them onto one line. _split_role_header alone
    can't see the two preceding lines; _reclaim_title_company recovers
    them from the tail of whatever line buffer preceded the date match.
    """

    def test_two_trailing_label_lines_reclaimed(self):
        lines = ["Led the redesign of the core product.", "UX DESIGN MANAGER", "OSB GROUP"]
        title, company, remaining = _reclaim_title_company(lines)
        assert title == "UX DESIGN MANAGER"
        assert company == "OSB GROUP"
        assert remaining == ["Led the redesign of the core product."]

    def test_single_trailing_label_line_reclaimed_as_title_only(self):
        lines = ["Delivered the project on time.", "PRODUCT DESIGNER"]
        title, company, remaining = _reclaim_title_company(lines)
        assert title == "PRODUCT DESIGNER"
        assert company is None
        assert remaining == ["Delivered the project on time."]

    def test_prose_tail_is_not_reclaimed(self):
        """Ordinary bullets (long, sentence-terminal punctuation) must
        never be misread as a title/company pair."""
        lines = [
            "Designed interactive prototypes and high-fidelity UI across web and mobile products.",
            "Analysed user feedback and requirements, creating detailed designs for clients.",
        ]
        title, company, remaining = _reclaim_title_company(lines)
        assert title is None
        assert company is None
        assert remaining == lines

    def test_empty_lines_returns_none(self):
        assert _reclaim_title_company([]) == (None, None, [])

    def test_looks_like_role_label_rejects_long_or_punctuated_lines(self):
        assert _looks_like_role_label("OSB GROUP") is True
        assert _looks_like_role_label("Led the redesign of the core product experience.") is False
        assert _looks_like_role_label("A" * 61) is False


def test_full_three_line_layout_end_to_end():
    """The real layout confirmed in a live CV export: TITLE / COMPANY /
    DATE as three consecutive standalone lines, then bullets, repeating
    per role. Exercises _reclaim_title_company + _split_role_header
    together the way process_cv_parse's segmentation loop uses them."""
    title, company, remaining = _reclaim_title_company(["UX DESIGN MANAGER", "OSB GROUP"])
    entry = _split_role_header("APRIL 2022 - PRESENT")
    if title:
        entry["title"] = title
    if company:
        entry["company"] = company

    assert entry["title"] == "UX DESIGN MANAGER"
    assert entry["company"] == "OSB GROUP"
    assert entry["current"] is True
    assert entry["start_date"] == "2022-04-01"
    assert remaining == []
