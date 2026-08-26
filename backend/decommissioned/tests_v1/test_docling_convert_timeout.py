"""DECOMMISSIONED — moved from tests/test_file_upload_security.py.
Covers step 3's Docling convert() timeout guard. Not collected: the
module it exercises now lives in decommissioned/extraction_v1/.
"""

@pytest.mark.asyncio(loop_scope="function")
async def test_docling_conversion_timeout_kills_hung_parse(monkeypatch):
    """A hung Docling convert() is killed at the configured bound, not left to
    hang the worker. Self-contained: monkeypatches every docling-derived name
    docling_parser uses, so it doesn't depend on whichever module-level stub an
    earlier test file happened to install.
    """
    from types import SimpleNamespace

    class _HangingConverter:
        def __init__(self, format_options=None):
            pass

        def convert(self, source):
            time.sleep(3)
            raise AssertionError("converter should have been timed out")

    class _PdfFormatOption:
        def __init__(self, pipeline_options=None):
            pass

    class _WordFormatOption:
        def __init__(self):
            pass

    class _DocumentStream:
        def __init__(self, *args, **kwargs):
            pass

    class _PdfPipelineOptions:
        do_ocr = False
        do_table_structure = True

    monkeypatch.setattr(docling_parser, "InputFormat", SimpleNamespace(PDF="pdf", DOCX="docx", IMAGE="image"))
    monkeypatch.setattr(docling_parser, "PdfPipelineOptions", _PdfPipelineOptions)
    monkeypatch.setattr(docling_parser, "PdfFormatOption", _PdfFormatOption)
    monkeypatch.setattr(docling_parser, "WordFormatOption", _WordFormatOption)
    monkeypatch.setattr(docling_parser, "DocumentStream", _DocumentStream)
    monkeypatch.setattr(docling_parser, "DocumentConverter", _HangingConverter)
    monkeypatch.setattr(docling_parser, "_DOCLING_CONVERT_TIMEOUT_SECONDS", 1)

    parser = DoclingParser()
    with pytest.raises(TimeoutError):
        await parser.parse(PDF_BYTES, "application/pdf")

