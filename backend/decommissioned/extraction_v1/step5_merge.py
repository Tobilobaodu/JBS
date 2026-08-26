"""Extraction merge layer.

Compares Docling and Textract outputs, produces a canonical extraction
result with structural validation checks. The downstream pipeline never
sees two competing document views — only the merged result.

Per 02-architecture-overview.md §4: merge is a deliberate step, not a
fallback. Both passes run on every document.
"""

from app.extraction.parser_interface import ExtractionResult
from app.core.logging import get_logger

logger = get_logger(__name__)


def merge_extractions(
    docling_result: ExtractionResult,
    textract_result: ExtractionResult,
) -> tuple[str, str, dict]:
    """Merge two extraction passes into one canonical text and validation result.

    Returns:
        (canonical_text, merge_strategy, structural_validation_result)
        canonical_text: the highest-confidence text blocks merged
        merge_strategy: 'highest_confidence_docling' or 'highest_confidence_textract'
        structural_validation_result: dict with section_count_match,
            heading_alignment_score, reading_order_consistent,
            date_range_consistent, bullet_preservation_score,
            anomaly_detected, anomaly_detail
    """
    docling_text = docling_result.extracted_text
    textract_text = textract_result.extracted_text

    # Basic line-level comparison
    docling_lines = [ln.strip() for ln in docling_text.split("\n") if ln.strip()]
    textract_lines = [ln.strip() for ln in textract_text.split("\n") if ln.strip()]

    docling_line_count = len(docling_lines)
    textract_line_count = len(textract_lines)

    # Section count match — approximate by counting lines that look like headings
    # (short, capitalized, or ending in known heading patterns)
    docling_headings = sum(
        1 for ln in docling_lines
        if len(ln) < 60 and (ln.isupper() or ln[0].isupper())
    )
    textract_headings = sum(
        1 for ln in textract_lines
        if len(ln) < 60 and (ln.isupper() or ln[0].isupper())
    )
    section_count_match = abs(docling_headings - textract_headings) <= 2

    # Heading alignment — simple overlap ratio
    heading_alignment_score = 1.0
    if max(docling_headings, textract_headings) > 0:
        heading_alignment_score = min(docling_headings, textract_headings) / max(
            docling_headings, textract_headings
        )

    # Reading order consistency — compare line count ratio
    reading_order_consistent = abs(docling_line_count - textract_line_count) <= max(
        docling_line_count, textract_line_count
    ) * 0.3

    # Date range consistency — crude check for year-like patterns
    import re
    date_pattern = re.compile(r"\b(19|20)\d{2}\b")
    docling_dates = set(date_pattern.findall(docling_text))
    textract_dates = set(date_pattern.findall(textract_text))
    date_range_consistent = len(docling_dates.symmetric_difference(textract_dates)) <= 5

    # Bullet preservation — count bullet-like markers
    bullet_pattern = re.compile(r"^\s*[-•*✦■➤►]\s")
    docling_bullets = sum(1 for ln in docling_lines if bullet_pattern.match(ln))
    textract_bullets = sum(1 for ln in textract_lines if bullet_pattern.match(ln))
    bullet_preservation_score = 1.0
    if max(docling_bullets, textract_bullets) > 0:
        bullet_preservation_score = min(docling_bullets, textract_bullets) / max(
            docling_bullets, textract_bullets
        )

    # Anomaly detection — flag if confidence gap is very large
    anomaly_detected = False
    anomaly_detail = None

    docling_conf = docling_result.confidence_score or 0.5
    textract_conf = textract_result.confidence_score or 0.5

    if abs(docling_conf - textract_conf) > 0.5:
        anomaly_detected = True
        anomaly_detail = (
            f"Large confidence gap: Docling={docling_conf:.2f}, "
            f"Textract={textract_conf:.2f}"
        )

    # Also flag if line counts differ dramatically
    line_ratio = (
        min(docling_line_count, textract_line_count)
        / max(docling_line_count, textract_line_count)
        if max(docling_line_count, textract_line_count) > 0
        else 0
    )
    if line_ratio < 0.5:
        anomaly_detected = True
        existing = anomaly_detail or ""
        anomaly_detail = (
            f"{existing + '; ' if existing else ''}"
            f"Large line-count gap: Docling={docling_line_count}, "
            f"Textract={textract_line_count}"
        )

    # Use the higher-confidence pass as the canonical text
    if docling_conf >= textract_conf:
        canonical_text = docling_text
        merge_strategy = "highest_confidence_docling"
    else:
        canonical_text = textract_text
        merge_strategy = "highest_confidence_textract"

    structural_validation = {
        "section_count_match": section_count_match,
        "heading_alignment_score": round(heading_alignment_score, 3),
        "reading_order_consistent": reading_order_consistent,
        "date_range_consistent": date_range_consistent,
        "bullet_preservation_score": round(bullet_preservation_score, 3),
        "anomaly_detected": anomaly_detected,
        "anomaly_detail": anomaly_detail,
    }

    logger.info(
        "merge_complete",
        merge_strategy=merge_strategy,
        docling_lines=docling_line_count,
        textract_lines=textract_line_count,
        docling_conf=docling_conf,
        textract_conf=textract_conf,
        anomaly=anomaly_detected,
    )

    return canonical_text, merge_strategy, structural_validation