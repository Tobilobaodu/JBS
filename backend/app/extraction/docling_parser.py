"""Docling document parser implementation.

Implements the DocumentParser ABC. Docling is a self-hosted Python library
for structured extraction of digital PDFs and DOCX files.

Per 02-architecture-overview.md §4a: this implementation is fully contained
behind the DocumentParser interface. No Docling-specific types leak past
this boundary.
"""

import io
import os
import time
import asyncio
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption, WordFormatOption
from docling_core.types.io import DocumentStream

from app.core.logging import get_logger
from app.extraction.parser_interface import DocumentParser, ExtractionResult

logger = get_logger(__name__)

# Offline mode — when true, Docling/HF will never attempt network access.
# Set via environment variable: HF_HUB_OFFLINE=1 (HuggingFace) + 
# DOCLING_OFFLINE=1 (future Docling-specific, reserved for forward compat).
_HF_HUB_OFFLINE = os.environ.get("HF_HUB_OFFLINE", "").strip().lower() in ("1", "true", "yes")

# Per-second timeout for Docling's convert() call. A pathological PDF or a
# missing-model download-attempt on an air-gapped network will exceed this
# and raise TimeoutError rather than hanging the Celery worker indefinitely.
# Falls through to the Textract second-pass per the extraction pipeline design.
_DOCLING_CONVERT_TIMEOUT_SECONDS = int(os.environ.get("DOCLING_CONVERT_TIMEOUT", "120"))


def _mime_to_input_format(mime_type: str) -> InputFormat | None:
    """Map an upload MIME type to a Docling InputFormat."""
    mapping = {
        "application/pdf": InputFormat.PDF,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": InputFormat.DOCX,
        "application/msword": InputFormat.DOCX,
        "image/png": InputFormat.IMAGE,
        "image/jpeg": InputFormat.IMAGE,
        "image/tiff": InputFormat.IMAGE,
    }
    return mapping.get(mime_type)


def _compute_confidence(conversion_result, extracted_text: str) -> float:
    """Compute a genuine extraction confidence score from structural signals.

    Per 02-architecture-overview.md §4: ``confidence_score`` must reflect 
    genuine parse quality, not a proxy like output length. A length-based 
    heuristic (e.g. 50 / char_count) always returns ~1.0 for normal-length 
    CVs and silently breaks the merge layer's "highest confidence wins" 
    comparison against Textract's real, calibrated confidence.

    This function extracts signals from Docling's document model that
    correlate with extraction quality:
      - **Item density** — number of recognised text items (paragraphs, 
        list items, headings) per page. A well-structured CV produces many 
        items; a garbled or image-heavy document produces few.
      - **Completeness** — ratio of extracted characters to a minimum 
        expected CV length (scaled sigmoid so it saturates quickly after 
        ~1500 chars, penalises very short output without rewarding length 
        alone).
      - **Empty-page fraction** — pages with zero text items drag the 
        score down, since they suggest layout regions Docling couldn't parse.
      - **Per-item text density** — items with well-below-average text per 
        item suggest fragmented or degraded extraction.

    Returns a float in [0.0, 1.0], where 1.0 = high confidence.
    """
    doc = conversion_result.document
    items = getattr(doc, "items", None) or []
    pages = getattr(doc, "pages", None) or {}

    item_count = len(items)
    page_count = max(len(pages), 1)

    # 1. Item density: items per page (normalised against a reasonable ceiling)
    items_per_page = item_count / page_count
    # 15 items/page → density ≈ 0.8; 30+ → 1.0; <5 → <0.3
    density_score = min(1.0, items_per_page / 18.0)

    # 2. Completeness: extracted length vs. minimum expected for a CV
    char_count = len(extracted_text)
    # Sigmoid scaled so 100 chars ≈ 0.1, 1500 chars ≈ 0.85, 3000+ ≈ 0.99
    import math
    completeness = 1.0 / (1.0 + math.exp(-0.003 * (char_count - 800)))

    # 3. Empty-page penalty: pages with no items at all
    empty_pages = 0
    if pages:
        for page in (pages.values() if isinstance(pages, dict) else pages):
            page_items = getattr(page, "items", None) or []
            if len(page_items) == 0:
                empty_pages += 1
    empty_fraction = empty_pages / page_count if page_count > 0 else 0
    empty_penalty = 1.0 - empty_fraction  # scales 0 (all empty) → 1 (none empty)

    # 4. Per-item text quality: items should carry a reasonable amount of text.
    #    Very low average chars/item suggests fragmented/degraded extraction.
    avg_chars_per_item = char_count / max(item_count, 1)
    # 30 chars/item → 0.5; 60+ → 1.0; <10 → penalised
    text_density_score = min(1.0, avg_chars_per_item / 60.0)
    # avg_chars_per_item is only a trustworthy signal when there are enough
    # items to average over — a document with pathologically few items (the
    # exact case density_score already penalises) can otherwise "launder" a
    # high per-item average from a small denominator into a misleadingly
    # high text-density score, canceling out the density penalty instead of
    # reinforcing it. Scaling by density_score keeps text density from
    # contradicting the item-count signal it's meant to complement.
    text_density_score *= density_score

    # Composite: weighted signal blend.
    # Density and completeness are the strongest indicators; empty-page and
    # text-density provide fine-grained degradation signals.
    confidence = (
        density_score * 0.30
        + completeness * 0.30
        + empty_penalty * 0.20
        + text_density_score * 0.20
    )

    # Floor at 0.05 — a document that parsed at all has *some* signal,
    # and a zero confidence is reserved for "parser refused entirely."
    return round(max(0.05, min(1.0, confidence)), 3)


class DoclingParser(DocumentParser):
    """Docling-based document parser for digital PDFs and DOCX.

    This is a CPU-bound, non-networked parser that runs entirely within the
    Docling worker container (deny-all egress at runtime).
    """

    ENGINE_NAME = "docling"

    async def parse(self, file_content: bytes, mime_type: str) -> ExtractionResult:
        """Parse a document using Docling.

        Args:
            file_content: Raw file bytes.
            mime_type: Validated MIME type.

        Returns:
            ExtractionResult with extracted text and metadata.

        Raises:
            ValueError: If Docling cannot parse the file.
        """
        start = time.monotonic()
        logger.info("docling_parse_start", mime_type=mime_type, size=len(file_content))

        try:
            # Map MIME type to Docling InputFormat
            fmt = _mime_to_input_format(mime_type)
            if fmt is None:
                raise ValueError(f"Unsupported MIME type for Docling: {mime_type}")

            # Build pipeline options and converter
            pipeline_opts = PdfPipelineOptions()
            pipeline_opts.do_ocr = False
            pipeline_opts.do_table_structure = True

            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts),
                    InputFormat.DOCX: WordFormatOption(),
                },
            )

            # Wrap bytes in a DocumentStream for Docling
            source = DocumentStream(name="cv", stream=io.BytesIO(file_content))

            # Run convert() in a thread pool with a hard timeout.
            # Without this, a missing-model download on air-gapped containers
            # or a pathological PDF hangs the Celery worker indefinitely.
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(converter.convert, source)
                try:
                    result = future.result(timeout=_DOCLING_CONVERT_TIMEOUT_SECONDS)
                except FuturesTimeoutError:
                    raise TimeoutError(
                        f"Docling conversion timed out after {_DOCLING_CONVERT_TIMEOUT_SECONDS}s. "
                        "This may be a missing-model download (check HF_HUB_OFFLINE env), "
                        "a pathological PDF, or insufficient CPU/memory."
                    )

            # Export to plain text from the converted document
            extracted_text = result.document.export_to_text()

            duration_ms = int((time.monotonic() - start) * 1000)

            char_count = len(extracted_text)
            if char_count == 0:
                raise ValueError("Docling produced zero characters of output.")

            # Compute genuine confidence from structural signals, not output length.
            # Per 02-architecture-overview.md §4: a proxy value (like 50/char_count)
            # silently breaks the merge layer's "highest confidence wins" logic.
            confidence = _compute_confidence(result, extracted_text)

            logger.info(
                "docling_parse_complete",
                characters=char_count,
                duration_ms=duration_ms,
                confidence=round(confidence, 3),
            )

            return ExtractionResult(
                extracted_text=extracted_text,
                raw_output={"pages_estimate": None},
                engine=self.ENGINE_NAME,
                engine_version="2.x",
                confidence_score=confidence,
                characters=char_count,
                pages=None,
                processing_duration_ms=duration_ms,
            )

        except TimeoutError:
            # Preserve the timeout signal — a hung parse timing out is a
            # distinct, actionable outcome (fail fast per §6), not a generic
            # "extraction failed" that the caller can't distinguish. The
            # docling→textract fall-through depends on the caller seeing this.
            raise
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error("docling_parse_failed", error=str(e), duration_ms=duration_ms)
            raise ValueError(f"Docling extraction failed: {e}") from e

    def parse_sync(self, file_content: bytes, mime_type: str) -> ExtractionResult:
        """Synchronous wrapper for Celery worker compatibility.

        Celery tasks are not async, so this provides a blocking call
        that internally runs the async parse() method.
        """
        async def _run():
            return await self.parse(file_content, mime_type)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _run())
                    return future.result()
            return loop.run_until_complete(_run())
        except RuntimeError:
            return asyncio.run(_run())