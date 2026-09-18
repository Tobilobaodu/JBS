"""task_key dedup must scope to ACTIVE jobs, not to all jobs ever.

Regression test for the live failure where the dashboard sat on
"Scoring…" forever: POST /cvs/{id}/analysis 500'd with
UniqueViolationError on idx_processing_jobs_task_key_unique, because
migration 013's index made the deterministic task_key unique across every
row — so the CV's first analysis permanently consumed the key and no
re-run could ever be created. Migration 022 narrows the index; these
tests pin both halves of the intended behaviour.

Live-DB pattern, calling the route function directly — see
test_auth_endpoints.py for the canonical example.
"""
import sys
import types
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Stub magic before importing the CVs router: it reaches
# app.services.file_validation -> `import magic`, and the native libmagic
# binding is only present inside the Docker image — on a Windows host venv
# the import hangs/crashes. Same block as test_ats_check_live.py. Nothing
# here validates a file, so the stub is never actually called.
if "magic" not in sys.modules:
    _magic = types.ModuleType("magic")
    _magic.MagicException = Exception
    _magic.from_buffer = lambda buf, mime=False: "application/octet-stream"
    _magic.from_file = lambda path, mime=False: "application/octet-stream"
    sys.modules["magic"] = _magic

from app.api.v1.cvs import run_cv_analysis  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.models import CvFile, CvRawText, ProcessingJob, User  # noqa: E402

_engine = create_async_engine(settings.database_url_async, poolclass=NullPool)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


def _request(client_host="203.0.113.77"):
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=client_host))


async def _user_with_cv(session):
    user = User(
        id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}-rerun@test.example",
        password_hash=hash_password("RealPassword123!"), status="active",
    )
    session.add(user)
    await session.flush()
    cv = CvFile(
        id=str(uuid.uuid4()), user_id=user.id, filename="cv.pdf",
        storage_key=f"k/{uuid.uuid4()}", mime_type="application/pdf",
        file_size=1024, status="completed",
    )
    session.add(cv)
    await session.flush()
    session.add(CvRawText(cv_file_id=cv.id, canonical_text="Jane Doe\nAnalyst\nSQL"))
    await session.commit()
    return user, cv


@pytest.mark.asyncio(loop_scope="function")
async def test_analysis_can_be_rerun_after_the_first_job_completes():
    async with _session_factory() as s:
        user, cv = await _user_with_cv(s)

        first = await run_cv_analysis(
            request=_request(), cv_id=cv.id, current_user=user, session=s
        )
        await s.execute(
            update(ProcessingJob).where(ProcessingJob.id == first.job_id).values(status="completed")
        )
        await s.commit()

        second = await run_cv_analysis(
            request=_request(), cv_id=cv.id, current_user=user, session=s
        )
        assert second.job_id != first.job_id


@pytest.mark.asyncio(loop_scope="function")
async def test_analysis_can_be_rerun_after_the_first_job_fails():
    async with _session_factory() as s:
        user, cv = await _user_with_cv(s)

        first = await run_cv_analysis(
            request=_request(), cv_id=cv.id, current_user=user, session=s
        )
        await s.execute(
            update(ProcessingJob).where(ProcessingJob.id == first.job_id).values(status="failed")
        )
        await s.commit()

        second = await run_cv_analysis(
            request=_request(), cv_id=cv.id, current_user=user, session=s
        )
        assert second.job_id != first.job_id


@pytest.mark.asyncio(loop_scope="function")
async def test_a_second_request_while_the_job_is_still_queued_is_deduped():
    """The half migration 022 must NOT break: two live jobs for the same
    CV would mean two paid LLM calls for one user action."""
    async with _session_factory() as s:
        user, cv = await _user_with_cv(s)

        first = await run_cv_analysis(
            request=_request(), cv_id=cv.id, current_user=user, session=s
        )
        again = await run_cv_analysis(
            request=_request(), cv_id=cv.id, current_user=user, session=s
        )
        assert again.job_id == first.job_id
