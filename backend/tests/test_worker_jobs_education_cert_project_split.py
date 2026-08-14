"""Pure-function tests for the new education/certification/project line
parsers in worker_jobs.py (Phase 2 extraction extension). No DB needed.

app.workers.worker_jobs imports docling at module level for its (unrelated)
extraction tasks — stubbed out below, same pattern as
test_worker_jobs_experience_split.py, so this file can import the real
module without installing a multi-GB ML dependency.
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
    _split_degree_field,
    _parse_education_line,
    _parse_certification_line,
    _split_project_title,
    _segment_projects,
)


class TestSplitDegreeField:

    def test_splits_on_in(self):
        degree, field = _split_degree_field("BSc in Computer Science")
        assert degree == "BSc"
        assert field == "Computer Science"

    def test_falls_back_to_degree_keyword(self):
        degree, field = _split_degree_field("BSc Computer Science")
        assert degree == "BSc"
        assert field == "Computer Science"

    def test_no_recognizable_structure_returns_whole_as_degree(self):
        degree, field = _split_degree_field("Some Program")
        assert degree == "Some Program"
        assert field is None


class TestParseEducationLine:

    def test_comma_separated_degree_institution_year(self):
        entry = _parse_education_line("BSc Computer Science, University of Leeds, 2019")
        assert entry["degree"] == "BSc"
        assert entry["field"] == "Computer Science"
        assert entry["institution"] == "University of Leeds"
        assert entry["year"] == 2019

    def test_dash_separated_institution_first(self):
        entry = _parse_education_line("University of Leeds — BSc Computer Science (2019)")
        assert entry["institution"] == "University of Leeds"
        assert entry["degree"] == "BSc"
        assert entry["field"] == "Computer Science"
        assert entry["year"] == 2019

    def test_institution_only_with_year_is_valid_evidence(self):
        entry = _parse_education_line("University of Cambridge, 2015")
        assert entry["institution"] == "University of Cambridge"
        assert entry["degree"] is None
        assert entry["year"] == 2015

    def test_unparseable_line_is_preserved_not_dropped(self):
        """A line with no degree/institution keyword is kept as a
        low-confidence entry rather than silently dropped — a rendered
        low-confidence qualification beats a discarded real one."""
        entry = _parse_education_line("Completed several online courses")
        assert entry is not None
        assert entry["degree"] == "Completed several online courses"
        assert entry["institution"] is None
        assert entry["confidence"] == 0.3

    def test_bare_year_only_returns_none(self):
        assert _parse_education_line("2019") is None

    def test_ambiguous_both_segments_look_like_degrees_is_preserved(self):
        entry = _parse_education_line("BSc Computer Science, MSc Data Science")
        assert entry is not None
        assert entry["degree"] == "BSc Computer Science, MSc Data Science"
        assert entry["institution"] is None
        assert entry["confidence"] == 0.3

    def test_empty_line_returns_none(self):
        assert _parse_education_line("   ") is None

    def test_certificate_with_online_provider_is_recognized(self):
        entry = _parse_education_line("Google's UX Design Certificate — Coursera")
        assert entry is not None
        assert "Certificate" in entry["degree"]
        assert entry["institution"] == "Coursera"

    def test_online_course_with_provider_only_is_recognized(self):
        entry = _parse_education_line("User Experience — FutureLearn")
        assert entry is not None
        assert entry["institution"] == "FutureLearn"
        assert entry["degree"] == "User Experience"


class TestParseCertificationLine:

    def test_full_name_issuer_year(self):
        entry = _parse_certification_line(
            "AWS Certified Solutions Architect – Amazon Web Services (2022)"
        )
        assert entry["name"] == "AWS Certified Solutions Architect"
        assert entry["issuer"] == "Amazon Web Services"
        assert entry["year"] == 2022

    def test_name_only_line(self):
        entry = _parse_certification_line("Certified ScrumMaster")
        assert entry["name"] == "Certified ScrumMaster"
        assert entry["issuer"] is None
        assert entry["year"] is None

    def test_empty_line_returns_none(self):
        assert _parse_certification_line("   ") is None


class TestSplitProjectTitle:

    def test_multi_token_parenthetical_recovered_as_technologies(self):
        name, technologies = _split_project_title(
            "Personal Finance Tracker (React, Node, Postgres)"
        )
        assert name == "Personal Finance Tracker"
        assert technologies == ["React", "Node", "Postgres"]

    def test_single_token_parenthetical_left_alone(self):
        """The asymmetric judgment call: a single-token parenthetical is
        too ambiguous (status label vs. tech) to guess at, so it stays
        part of the display name and technologies is empty."""
        name, technologies = _split_project_title("Portfolio Website (Personal Project)")
        assert name == "Portfolio Website (Personal Project)"
        assert technologies == []

    def test_tech_label_recovered(self):
        name, technologies = _split_project_title(
            "Chat Application — Technologies: Python, WebSockets, Redis"
        )
        assert name == "Chat Application"
        assert technologies == ["Python", "WebSockets", "Redis"]

    def test_no_signal_returns_whole_line_as_name(self):
        name, technologies = _split_project_title("Weather Dashboard")
        assert name == "Weather Dashboard"
        assert technologies == []


class TestSegmentProjects:

    def test_title_with_bullets_and_tech_parenthetical(self):
        lines = [
            "Personal Finance Tracker (React, Node, Postgres)",
            "- Built a full-stack app to track expenses",
            "- Reduced manual entry by 80%",
        ]
        projects = _segment_projects(lines)
        assert len(projects) == 1
        assert projects[0]["name"] == "Personal Finance Tracker"
        assert projects[0]["technologies"] == ["React", "Node", "Postgres"]
        assert projects[0]["bullets"] == [
            "Built a full-stack app to track expenses",
            "Reduced manual entry by 80%",
        ]

    def test_two_consecutive_title_lines_start_two_projects(self):
        projects = _segment_projects(["E-Commerce Platform", "Analytics Dashboard"])
        assert len(projects) == 2
        assert projects[0]["name"] == "E-Commerce Platform"
        assert projects[1]["name"] == "Analytics Dashboard"

    def test_bullet_marked_line_never_misread_as_new_title(self):
        lines = ["Chat Application", "- Implemented real-time messaging using WebSockets"]
        projects = _segment_projects(lines)
        assert len(projects) == 1
        assert projects[0]["bullets"] == ["Implemented real-time messaging using WebSockets"]

    def test_unmarked_prose_line_becomes_description_not_new_title(self):
        lines = [
            "Weather Dashboard",
            "A responsive web application that displays real-time weather data for any city worldwide.",
        ]
        projects = _segment_projects(lines)
        assert len(projects) == 1
        assert projects[0]["description"] == (
            "A responsive web application that displays real-time weather "
            "data for any city worldwide."
        )

    def test_empty_lines_returns_empty_list(self):
        assert _segment_projects([]) == []
