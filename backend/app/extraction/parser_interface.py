"""Swappable document parser interface.

Defines the abstract base class that every parser (Docling, Textract, future
replacements) must implement. The boundary is Pydantic-typed: parsers return
a structured model, never a bare dict, and never leak their internal types.

Per 02-architecture-overview.md §4a: this interface must be defined BEFORE
the Docling implementation, not retrofitted afterward.
"""

from abc import ABC, abstractmethod
from pydantic import BaseModel


class ExtractionResult(BaseModel):
    """Standardised output from any document parser.

    Matches the cv_extraction_passes column shape in 03-data-model.md §3.
    """
    extracted_text: str
    raw_output: dict | None = None
    engine: str | None = None
    engine_version: str | None = None
    confidence_score: float | None = None
    characters: int | None = None
    pages: int | None = None
    processing_duration_ms: int | None = None


class DocumentParser(ABC):
    """Abstract base for all document parsers.

    Implementations translate provider-specific output into the common
    ExtractionResult shape. No caller should depend on Docling/Textract
    types — only on ExtractionResult.
    """

    @abstractmethod
    async def parse(self, file_content: bytes, mime_type: str) -> ExtractionResult:
        """Parse a document and return a standardised extraction result.

        Args:
            file_content: Raw bytes of the uploaded file.
            mime_type: The validated MIME type (e.g. application/pdf).

        Returns:
            ExtractionResult with extracted_text, confidence, metadata.

        Raises:
            ValueError: If the file cannot be parsed (bad format, corruption).
            TimeoutError: If parsing exceeds the configured timeout.
        """
        ...