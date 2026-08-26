"""Pure-function tests for the CV header/contact block parser added to
worker_jobs.py (recovers the candidate's name, email, phone, portfolio
URL and location from the preamble above the first section heading).

app.workers.worker_jobs imports docling at module level for its (unrelated)
extraction tasks — stubbed out below, same pattern as
test_worker_jobs_education_cert_project_split.py, so this file can import
the real module without installing a multi-GB ML dependency.
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

from app.workers.worker_jobs import _parse_header_block, _looks_like_name


class TestLooksLikeName:

    def test_all_caps_name(self):
        assert _looks_like_name("TOBILOBA ODU")

    def test_title_case_name(self):
        assert _looks_like_name("Tobiloba Odu")

    def test_contact_line_is_not_a_name(self):
        assert not _looks_like_name("tobilobaodu.com | odu@gmail.com | +447562695548")

    def test_title_with_slash_and_comma_is_not_a_name(self):
        assert not _looks_like_name("PRODUCT DESIGNER, UI/UX and RESEARCH")

    def test_digits_are_not_a_name(self):
        assert not _looks_like_name("2024 Graduate")


class TestParseHeaderBlock:

    def test_full_header_block(self):
        header = _parse_header_block([
            "TOBILOBA ODU",
            "PRODUCT DESIGNER, UI/UX and RESEARCH",
            "tobilobaodu.com | oduoluwatobi@gmail.com | +447562695548",
        ])
        assert header["name"] == "TOBILOBA ODU"
        assert header["email"] == "oduoluwatobi@gmail.com"
        assert header["phone"] == "+447562695548"
        assert header["urls"] == ["tobilobaodu.com"]
        assert header["location"] is None

    def test_name_and_contact_only(self):
        header = _parse_header_block([
            "Jane Doe",
            "jane@example.com | +44 20 7946 0958",
        ])
        assert header["name"] == "Jane Doe"
        assert header["email"] == "jane@example.com"
        assert header["phone"] is not None

    def test_location_line_recovered(self):
        header = _parse_header_block([
            "Jane Doe",
            "London, UK",
            "jane@example.com",
        ])
        assert header["name"] == "Jane Doe"
        assert header["location"] == "London, UK"

    def test_empty_preamble_yields_all_none(self):
        header = _parse_header_block([])
        assert header["name"] is None
        assert header["email"] is None
        assert header["phone"] is None
        assert header["location"] is None
        assert header["urls"] == []
