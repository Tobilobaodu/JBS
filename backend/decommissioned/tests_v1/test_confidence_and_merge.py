"""Merge-outcome sanity tests — per 12-project-status-and-roadmap.md item 2.

Verifies that the Docling confidence score genuinely tracks extraction quality
(not output length alone) and that the merge layer correctly prefers the
higher-confidence pass.

These tests exist because a length-based proxy heuristic (50 / char_count)
shipped once during this project's implementation and silently broke the
merge layer's "highest confidence wins" logic without any visible error.
See 02-architecture-overview.md §4 for the full account.
"""

import pytest
from unittest.mock import MagicMock

from app.extraction.parser_interface import ExtractionResult
from app.extraction.docling_parser import _compute_confidence


# ──────────────────────────────────────────────────────────────────────
# Test 1: _compute_confidence tracks quality, not length
# ──────────────────────────────────────────────────────────────────────


class TestComputeConfidence:
    """Confirm _compute_confidence responds to structural signals,
    not output length alone."""

    @staticmethod
    def _make_docling_result(
        *,
        char_count: int = 3000,
        item_count: int = 30,
        page_count: int = 2,
        empty_pages: int = 0,
    ) -> MagicMock:
        """Build a synthetic Docling conversion result with controlled structure.

        The conversion result is a MagicMock whose .document attribute has
        .items (list of text items) and .pages (dict of page objects, each
        with their own .items list).
        """
        doc = MagicMock()
        doc.items = [MagicMock() for _ in range(item_count)]

        pages = {}
        for i in range(page_count):
            page = MagicMock()
            # Empty pages have no items; populated pages get a share
            if i < (page_count - empty_pages):
                per_page = max(1, item_count // max(page_count - empty_pages, 1))
                page.items = [MagicMock() for _ in range(per_page)]
            else:
                page.items = []
            pages[i] = page
        doc.pages = pages

        result = MagicMock()
        result.document = doc
        return result

    def test_well_structured_document_scores_high(self):
        """A document with many items across populated pages scores >0.7."""
        mock = self._make_docling_result(
            char_count=3000, item_count=40, page_count=2, empty_pages=0
        )
        score = _compute_confidence(mock, "A" * 3000)
        assert score > 0.7, f"Expected >0.7 for well-structured doc, got {score}"

    def test_garbled_low_density_scores_low(self):
        """Few items across many pages with empty pages scores meaningfully lower."""
        mock_garbled = self._make_docling_result(
            char_count=3000, item_count=5, page_count=3, empty_pages=2
        )
        score_garbled = _compute_confidence(mock_garbled, "A" * 3000)
        assert score_garbled < 0.5, (
            f"Expected <0.5 for garbled doc, got {score_garbled}"
        )

    def test_clean_vs_garbled_gap_is_significant(self):
        """Clean doc scores meaningfully higher (>0.15 gap) than garbled."""
        mock_clean = self._make_docling_result(
            char_count=2500, item_count=35, page_count=2, empty_pages=0
        )
        mock_garbled = self._make_docling_result(
            char_count=2500, item_count=6, page_count=3, empty_pages=2
        )

        score_clean = _compute_confidence(mock_clean, "A" * 2500)
        score_garbled = _compute_confidence(mock_garbled, "A" * 2500)

        gap = score_clean - score_garbled
        assert gap > 0.15, (
            f"Expected >0.15 gap, got {gap:.3f} "
            f"(clean={score_clean:.3f}, garbled={score_garbled:.3f})"
        )

    def test_length_alone_does_not_inflate_score(self):
        """A long-but-sparse document should NOT score higher than a
        shorter-but-well-structured one. This directly tests that the old
        length-proxy heuristic has been replaced."""
        mock_long_sparse = self._make_docling_result(
            char_count=8000,  # long text
            item_count=8,     # but very few recognised items
            page_count=4,
            empty_pages=2,
        )
        mock_short_dense = self._make_docling_result(
            char_count=1200,  # shorter text
            item_count=30,    # but well-structured with many items
            page_count=2,
            empty_pages=0,
        )

        score_long = _compute_confidence(mock_long_sparse, "A" * 8000)
        score_short = _compute_confidence(mock_short_dense, "A" * 1200)

        assert score_short > score_long, (
            f"Expected short-dense ({score_short:.3f}) to outscore "
            f"long-sparse ({score_long:.3f}) — length proxy detected"
        )


# ──────────────────────────────────────────────────────────────────────
# Test 2: Merge prefers the better pass
# ──────────────────────────────────────────────────────────────────────


class TestMergePrefersHigherConfidence:
    """Confirm the merge layer uses confidence to select the canonical text."""

    def test_merge_selects_higher_confidence_docling(self):
        """When Docling has higher confidence, its text becomes canonical."""
        from app.extraction.merge import merge_extractions

        docling = ExtractionResult(
            extracted_text="Clean parsed CV text from Docling",
            confidence_score=0.92,
            characters=35,
            pages=2,
            processing_duration_ms=1200,
        )
        textract = ExtractionResult(
            extracted_text="garbled txract otuput wtih msispelligns",
            confidence_score=0.31,
            characters=42,
            pages=2,
            processing_duration_ms=8000,
        )

        canonical, strategy, validation = merge_extractions(docling, textract)

        assert canonical == docling.extracted_text
        assert strategy == "highest_confidence_docling"

    def test_merge_selects_higher_confidence_textract(self):
        """When Textract has higher confidence, its text becomes canonical."""
        from app.extraction.merge import merge_extractions

        docling = ExtractionResult(
            extracted_text="Docling missed columns, partial extraction here",
            confidence_score=0.28,
            characters=51,
            pages=1,
            processing_duration_ms=900,
        )
        textract = ExtractionResult(
            extracted_text="Textract recovered full two-column layout text",
            confidence_score=0.88,
            characters=48,
            pages=2,
            processing_duration_ms=9500,
        )

        canonical, strategy, validation = merge_extractions(docling, textract)

        assert canonical == textract.extracted_text
        assert strategy == "highest_confidence_textract"

    def test_anomaly_detected_when_confidence_gap_large(self):
        """A large confidence gap (>0.5) triggers anomaly_detected."""
        from app.extraction.merge import merge_extractions

        docling = ExtractionResult(
            extracted_text="Full clean CV extraction",
            confidence_score=0.95,
            characters=100,
            pages=2,
            processing_duration_ms=1000,
        )
        textract = ExtractionResult(
            extracted_text="Almost empty textract output",
            confidence_score=0.12,
            characters=30,
            pages=1,
            processing_duration_ms=5000,
        )

        canonical, strategy, validation = merge_extractions(docling, textract)

        assert validation["anomaly_detected"] is True
        assert validation["anomaly_detail"] is not None
        assert "confidence gap" in validation["anomaly_detail"].lower()

    def test_no_spurious_anomaly_when_scores_are_reasonable(self):
        """Both scores in a normal range should NOT trigger anomaly."""
        from app.extraction.merge import merge_extractions

        docling = ExtractionResult(
            extracted_text="Good extraction from Docling",
            confidence_score=0.78,
            characters=100,
            pages=2,
            processing_duration_ms=1200,
        )
        textract = ExtractionResult(
            extracted_text="Good extraction from Textract as well",
            confidence_score=0.72,
            characters=100,
            pages=2,
            processing_duration_ms=8000,
        )

        canonical, strategy, validation = merge_extractions(docling, textract)

        # Both are reasonable scores — anomaly should NOT fire from
        # the confidence-gap check alone (line-count gap may fire separately,
        # but for equal line counts it shouldn't).
        assert not validation["anomaly_detected"], (
            f"Unexpected anomaly: {validation.get('anomaly_detail')}"
        )