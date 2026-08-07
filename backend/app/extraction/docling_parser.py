"""Docling document parser implementation.

Implements the DocumentParser ABC. Docling is a self-hosted Python library
for structured extraction of digital PDFs and DOCX files.

Per 02-architecture-overview.md §4a: this implementation is fully contained
behind the DocumentParser interface. No Docling-specific types leak past
this boundary.
"""

import io
import time
import asyncio
import concurrent.futures

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption, WordFormatOption
from docling_core.types.io import DocumentStream

from app.core.logging import get_logger
from app.extraction.parser_interface import DocumentParser, ExtractionResult

logger = get_logger(__name__)


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
            result = converter.convert(source)

            # Export to plain text from the converted document
            extracted_text = result.document.export_to_text()

            duration_ms = int((time.monotonic() - start) * 1000)

            char_count = len(extracted_text)
            if char_count == 0:
                raise ValueError("Docling produced zero characters of output.")

            # Rough confidence: below ~50 chars on a real CV is suspicious
            confidence = min(1.0, max(0.1, 50 / char_count)) if char_count > 0 else 0.0

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