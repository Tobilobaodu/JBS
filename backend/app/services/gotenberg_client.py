"""Thin HTTP client wrapper for Gotenberg's docx-to-pdf conversion route.

Deliberately pulled out of worker_jobs.py into its own small module: that
file transitively imports docling (app.extraction.docling_parser), which
isn't installed outside the Docker image the workers run in, so nothing
importable only via worker_jobs.py is testable from the host venv. This
module has no such dependency, so httpx.MockTransport can exercise the
real request/response handling directly, without a live Gotenberg
container or the full worker module.
"""

from __future__ import annotations

import httpx

from app.core.config import settings

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def convert_docx_to_pdf(docx_bytes: bytes, *, client: httpx.Client | None = None) -> bytes:
    """Converts docx bytes to pdf bytes via Gotenberg's LibreOffice
    conversion route. Raises httpx.HTTPStatusError on a non-2xx response
    — the caller (worker_jobs.py::process_export_pdf) is responsible for
    catching/retrying, same as any other infra call in this codebase.

    A caller-supplied client (e.g. one built with an httpx.MockTransport)
    is used as-is and never closed here — only a client this function
    creates itself gets closed.
    """
    owns_client = client is None
    http_client = client or httpx.Client(timeout=settings.gotenberg_request_timeout_seconds)
    try:
        response = http_client.post(
            f"{settings.gotenberg_url}/forms/libreoffice/convert",
            files={"files": ("source.docx", docx_bytes, _DOCX_CONTENT_TYPE)},
        )
        response.raise_for_status()
        return response.content
    finally:
        if owns_client:
            http_client.close()
