"""Live-DB verification: process_cv_parse actually inserts CvEducationItem/
CvCertificationItem/CvProjectItem rows end-to-end (Phase 2 extraction
extension), and structured_payload's education/certifications/projects
keys are genuinely populated — not the old hardcoded [].

Mirrors test_ats_check_live.py's docling/magic stub pattern. process_cv_parse
uses a synchronous session (_get_sync_session, worker_jobs.py) against the
same real Postgres instance the async test session seeds/verifies against —
same pattern test_trial_session_cleanup.py already established.
"""
import sys
import types
import uuid

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

if "magic" not in sys.modules:
    _magic = types.ModuleType("magic")
    _magic.MagicException = Exception
    _magic.from_buffer = lambda buf, mime=False: (
        "application/pdf" if b"PDF" in (buf or b"") else "application/octet-stream"
    )
    _magic.from_file = lambda path, mime=False: "application/octet-stream"
    sys.modules["magic"] = _magic

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.workers.worker_jobs import process_cv_parse
from app.db.models import (
    CvCertificationItem, CvEducationItem, CvExtractionPass, CvFile,
    CvProfileVersion, CvProjectItem, CvRawText, ProcessingJob, User,
)

_test_engine = create_async_engine(settings.database_url_async, poolclass=NullPool)
_test_session_factory = async_sessionmaker(_test_engine, expire_on_commit=False)


async def _user(session, tag=""):
    u = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}{tag}@test.example",
              password_hash="fake", status="active")
    session.add(u)
    await session.flush()
    return u


async def _seed_cv(session, user, canonical_text):
    cv_file = CvFile(id=str(uuid.uuid4()), user_id=user.id,
                      filename="test.pdf", mime_type="application/pdf",
                      file_size=1, storage_key=str(uuid.uuid4()), status="merged")
    session.add(cv_file)
    await session.flush()

    session.add(CvRawText(id=str(uuid.uuid4()), cv_file_id=cv_file.id,
                           canonical_text=canonical_text, ocr_used=False))
    session.add(CvExtractionPass(id=str(uuid.uuid4()), cv_file_id=cv_file.id,
                                  pass_type="docling", attempt_number=1,
                                  extracted_text=canonical_text))
    await session.flush()

    job = ProcessingJob(id=str(uuid.uuid4()), job_type="cv_parse",
                         source_entity_type="cv_file", source_entity_id=cv_file.id,
                         user_id=user.id, status="queued")
    session.add(job)
    await session.flush()
    return cv_file, job


_FULL_CV_TEXT = """\
jane.doe@example.com +1 555 0100

WORK EXPERIENCE
Software Engineer at Acme Corp, Jan 2020 - Dec 2021
- Built REST APIs using Python and Docker

EDUCATION
BSc Computer Science, University of Leeds, 2019

CERTIFICATIONS
AWS Certified Solutions Architect – Amazon Web Services (2022)

PROJECTS
Personal Finance Tracker (React, Node, Postgres)
- Built a full-stack app to track expenses

SKILLS
Python, SQL, Docker
"""

_NO_NEW_SECTIONS_CV_TEXT = """\
jane.doe@example.com +1 555 0100

WORK EXPERIENCE
Software Engineer at Acme Corp, Jan 2020 - Dec 2021
- Built REST APIs using Python and Docker

SKILLS
Python, SQL, Docker
"""


@pytest.mark.asyncio(loop_scope="function")
async def test_education_certification_project_rows_are_inserted():
    async with _test_session_factory() as s:
        user = await _user(s, "fullsections")
        cv_file, job = await _seed_cv(s, user, _FULL_CV_TEXT)
        await s.commit()
        job_id = job.id
        cv_file_id = cv_file.id

    process_cv_parse(job_id)

    async with _test_session_factory() as verify_s:
        job_row = await verify_s.get(ProcessingJob, job_id)
        assert job_row.status == "completed"

        pv = (await verify_s.execute(
            select(CvProfileVersion).where(CvProfileVersion.cv_file_id == cv_file_id)
        )).scalar_one()

        edu_rows = (await verify_s.execute(
            select(CvEducationItem).where(CvEducationItem.cv_profile_version_id == pv.id)
        )).scalars().all()
        assert len(edu_rows) == 1
        assert edu_rows[0].institution == "University of Leeds"
        assert edu_rows[0].degree == "BSc"
        assert edu_rows[0].year == 2019

        cert_rows = (await verify_s.execute(
            select(CvCertificationItem).where(CvCertificationItem.cv_profile_version_id == pv.id)
        )).scalars().all()
        assert len(cert_rows) == 1
        assert cert_rows[0].name == "AWS Certified Solutions Architect"
        assert cert_rows[0].issuer == "Amazon Web Services"

        proj_rows = (await verify_s.execute(
            select(CvProjectItem).where(CvProjectItem.cv_profile_version_id == pv.id)
        )).scalars().all()
        assert len(proj_rows) == 1
        assert proj_rows[0].name == "Personal Finance Tracker"
        assert proj_rows[0].technologies == ["React", "Node", "Postgres"]

        payload = pv.structured_payload
        assert payload["education"][0]["degree"] == "BSc"
        assert payload["certifications"][0]["name"] == "AWS Certified Solutions Architect"
        assert payload["projects"][0]["name"] == "Personal Finance Tracker"


@pytest.mark.asyncio(loop_scope="function")
async def test_cv_without_new_sections_yields_no_rows_and_empty_lists():
    """Non-fabrication check: a CV with no Education/Certifications/
    Projects sections must not produce any rows or guessed content."""
    async with _test_session_factory() as s:
        user = await _user(s, "nosections")
        cv_file, job = await _seed_cv(s, user, _NO_NEW_SECTIONS_CV_TEXT)
        await s.commit()
        job_id = job.id
        cv_file_id = cv_file.id

    process_cv_parse(job_id)

    async with _test_session_factory() as verify_s:
        pv = (await verify_s.execute(
            select(CvProfileVersion).where(CvProfileVersion.cv_file_id == cv_file_id)
        )).scalar_one()

        edu_rows = (await verify_s.execute(
            select(CvEducationItem).where(CvEducationItem.cv_profile_version_id == pv.id)
        )).scalars().all()
        cert_rows = (await verify_s.execute(
            select(CvCertificationItem).where(CvCertificationItem.cv_profile_version_id == pv.id)
        )).scalars().all()
        proj_rows = (await verify_s.execute(
            select(CvProjectItem).where(CvProjectItem.cv_profile_version_id == pv.id)
        )).scalars().all()

        assert edu_rows == []
        assert cert_rows == []
        assert proj_rows == []
        assert pv.structured_payload["education"] == []
        assert pv.structured_payload["certifications"] == []
        assert pv.structured_payload["projects"] == []
