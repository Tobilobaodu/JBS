"""Focused tests for Bug #4 — pipeline stage job_type transitions.

Validates that every Celery worker updates `job.job_type` to the next
stage before enqueueing the downstream task. Uses source inspection so
the tests are fast and don't require a running worker.
"""

import inspect
import sys
sys.path.insert(0, "/app")


def test_docling_updates_job_type_before_textract():
    """process_docling_extract → textract_extract"""
    from app.workers.worker_jobs import process_docling_extract
    src = inspect.getsource(process_docling_extract)
    update_pos = src.find('job.job_type = "textract_extract"')
    enqueue_pos = src.find("enqueue_textract_extract(job_id)")
    assert update_pos != -1, "docling: missing job_type = textract_extract update"
    assert enqueue_pos != -1, "docling: missing enqueue_textract_extract call"
    assert update_pos < enqueue_pos, "docling: job_type update must come BEFORE enqueue"


def test_textract_updates_job_type_before_merge():
    """process_textract_extract → merge_parse"""
    from app.workers.worker_jobs import process_textract_extract
    src = inspect.getsource(process_textract_extract)
    update_pos = src.find('job.job_type = "merge_parse"')
    enqueue_pos = src.find("enqueue_merge_parse(job_id)")
    assert update_pos != -1, "textract: missing job_type = merge_parse update"
    assert enqueue_pos != -1, "textract: missing enqueue_merge_parse call"
    assert update_pos < enqueue_pos, "textract: job_type update must come BEFORE enqueue"


def test_merge_updates_job_type_before_cv_parse():
    """process_merge_parse → cv_parse"""
    from app.workers.worker_jobs import process_merge_parse
    src = inspect.getsource(process_merge_parse)
    update_pos = src.find('job.job_type = "cv_parse"')
    enqueue_pos = src.find("enqueue_cv_parse(job_id)")
    assert update_pos != -1, "merge: missing job_type = cv_parse update"
    assert enqueue_pos != -1, "merge: missing enqueue_cv_parse call"
    assert update_pos < enqueue_pos, "merge: job_type update must come BEFORE enqueue"


def test_fetch_updates_job_type_before_parse():
    """process_job_post_fetch → job_post_parse"""
    from app.workers.worker_jobs import process_job_post_fetch
    src = inspect.getsource(process_job_post_fetch)
    update_pos = src.find('job.job_type = "job_post_parse"')
    enqueue_pos = src.find("enqueue_job_post_parse(job_id)")
    assert update_pos != -1, "fetch: missing job_type = job_post_parse update"
    assert enqueue_pos != -1, "fetch: missing enqueue_job_post_parse call"
    assert update_pos < enqueue_pos, "fetch: job_type update must come BEFORE enqueue"


def test_terminal_workers_do_not_update_job_type():
    """process_cv_parse and process_match are terminal — no handoff needed."""
    from app.workers.worker_jobs import process_cv_parse, process_match
    for name, fn in [("process_cv_parse", process_cv_parse),
                      ("process_match", process_match)]:
        src = inspect.getsource(fn)
        assert "job.job_type" not in src, f"{name} terminal: should not update job_type"