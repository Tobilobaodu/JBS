"""Phase 5 regression test: full auth → upload → parse → match → cover-letter chain.

Runs inside the Docker container:
  docker compose exec -T api python -m pytest tests/test_regression_full_chain.py -q -s
"""

import sys
sys.path.insert(0, "/app")

import time
import requests

API = "http://localhost:8000/api/v1"
EMAIL = f"regression-{int(time.time())}@test.com"
PASSWORD = "RegressionTest123!"


def _register_and_login():
    """Register a new user and return (headers, email)."""
    r = requests.post(f"{API}/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code in (200, 201), f"Register failed: {r.status_code} {r.text}"

    r = requests.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    body = r.json()

    # Bug #6 — camelCase
    token = body.get("accessToken")
    assert token, f"No accessToken in login response: {list(body.keys())}"
    headers = {"Authorization": f"Bearer {token}"}
    return headers, EMAIL


def test_01_rate_limiting():
    """Auth endpoints should be rate-limited after 5 rapid requests."""
    email = f"ratelimit-{int(time.time())}@test.com"
    # 5 rapid login attempts should succeed individually (returns 401), then 6th is 429
    for i in range(6):
        r = requests.post(f"{API}/auth/login",
                         json={"email": email, "password": "wrong"})
        if i < 5:
            assert r.status_code in (401, 409), \
                f"Attempt {i+1}: expected 401/409, got {r.status_code}"
        else:
            assert r.status_code == 429, \
                f"Attempt {i+1}: expected 429 (rate limited), got {r.status_code}"
    print("  Rate limiting: blocks 6th attempt ✓")
    # register and login share one "auth" rate-limit bucket per client IP
    # (not separate per-endpoint buckets) — confirmed live: test_02's very
    # next /auth/register call inherited this test's deliberately-triggered
    # block and got a 429 itself, every single run, not occasionally.
    #
    # The wait needed is NOT settings.rate_limit_auth_window (60s) — that's
    # only the sliding-window size used to detect a violation. Tripping the
    # limit (as this test deliberately does) escalates to a separate
    # 300-second (5-minute) violation block in app/core/rate_limit.py::
    # check_rate_limit() (`_blocked[key] = now + 300`, a literal, not a
    # settings field — confirmed by reading the source, not guessed; a
    # first attempt at this fix used the 60s window and still failed
    # every time). Slow, but this is already a Docker-only integration
    # test, never part of the fast host suite, and correctness here
    # matters more than shaving four minutes off a test nobody runs often.
    time.sleep(301)


def test_02_full_chain():
    """Full chain: register → login → upload CV → poll → match → cover letter workflow."""
    headers, email = _register_and_login()

    # ── Upload CV ──────────────────────────────────────────────────
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
    )
    r = requests.post(f"{API}/cvs", headers=headers,
                     files={"file": ("test_cv.pdf", pdf, "application/pdf")})
    assert r.status_code == 202, f"Upload failed: {r.status_code} {r.text}"
    cv_data = r.json()
    cv_id = cv_data.get("cvId")
    job_id = cv_data.get("processingJobId")
    assert cv_id and job_id, f"Missing IDs: {cv_data}"
    print(f"  Upload: cvId={cv_id[:8]}, jobId={job_id[:8]} ✓")

    # ── Poll until CV is parsed ────────────────────────────────────
    timeout = 120
    start = time.monotonic()
    cv_parsed = False
    while time.monotonic() - start < timeout:
        r = requests.get(f"{API}/cvs/{cv_id}", headers=headers)
        if r.status_code == 200:
            status = r.json().get("processingStatus", "pending")
            if status == "parsed":
                cv_parsed = True
                break
        time.sleep(2)
    assert cv_parsed, "CV not parsed within 120s"
    print(f"  CV parsed after {time.monotonic() - start:.0f}s ✓")

    # ── Get parsed profile ─────────────────────────────────────────
    r = requests.get(f"{API}/cvs/{cv_id}/parsed-profile", headers=headers)
    assert r.status_code == 200, f"Parsed profile failed: {r.status_code}"
    profile = r.json()
    cv_profile_version_id = profile.get("profileVersionId")
    assert cv_profile_version_id, f"No profileVersionId: {profile}"
    print(f"  Profile version: {cv_profile_version_id[:8]} ✓")

    # ── Submit job post text ───────────────────────────────────────
    job_text = (
        "Senior Software Engineer\n\n"
        "Requirements:\n- Python\n- Docker\n- Kubernetes\n"
        "Preferred:\n- AWS\n- Terraform"
    )
    r = requests.post(f"{API}/job-posts/text", headers=headers,
                     json={"text": job_text})
    assert r.status_code == 202, f"Job post failed: {r.status_code}"
    jp_data = r.json()
    jp_id = jp_data.get("jobPostId")
    assert jp_id, "No jobPostId"
    print(f"  Job post: {jp_id[:8]} ✓")

    # Wait for job post parse
    time.sleep(2)

    # ── Create match ───────────────────────────────────────────────
    r = requests.post(f"{API}/matches", headers=headers, json={
        "cvProfileVersionId": cv_profile_version_id,
        "jobPostId": jp_id,
    })
    assert r.status_code == 202, f"Match failed: {r.status_code} {r.text}"
    match_data = r.json()
    match_id = match_data.get("matchId")
    match_job_id = match_data.get("processingJobId")
    assert match_id and match_job_id, f"Missing match IDs: {match_data}"
    print(f"  Match created: {match_id[:8]} ✓")

    # Poll for match completion
    time.sleep(2)
    r = requests.get(f"{API}/matches/{match_id}", headers=headers)
    if r.status_code == 200:
        match = r.json()
        print(f"  Match score: {match.get('score', 'N/A')}")

    # ── Start cover letter workflow ────────────────────────────────
    r = requests.post(f"{API}/cover-letters/start", headers=headers, json={
        "cvId": cv_id,
        "jobPostId": jp_id,
    })
    assert r.status_code == 201, f"Workflow start failed: {r.status_code} {r.text}"
    wf = r.json()
    workflow_id = wf.get("id")
    assert workflow_id, f"No workflow ID: {wf}"
    assert wf.get("currentStep") == 1
    assert wf.get("status") == "awaiting_answers"
    print(f"  Workflow started: {workflow_id[:8]} ✓")

    # ── Get questions ──────────────────────────────────────────────
    r = requests.get(f"{API}/cover-letters/{workflow_id}/questions", headers=headers)
    assert r.status_code == 200, f"Questions failed: {r.status_code}"
    questions = r.json()
    assert len(questions) >= 2
    print(f"  Questions: {len(questions)} for step 1 ✓")

    # ── Submit answers for step 1 ──────────────────────────────────
    answers = [{"questionId": q["id"], "answerText": f"Test answer for {q['questionId'][:8]}"}
               for q in questions]
    r = requests.post(f"{API}/cover-letters/{workflow_id}/answers", headers=headers,
                     json={"answers": answers})
    assert r.status_code == 202, f"Answers failed: {r.status_code}"
    wf2 = r.json()
    assert wf2.get("currentStep") == 2
    print(f"  Step 1 answered → step 2 ✓")

    # ── Submit answers for step 2 ──────────────────────────────────
    r = requests.get(f"{API}/cover-letters/{workflow_id}/questions", headers=headers)
    step2_qs = r.json()
    answers2 = [{"questionId": q["id"], "answerText": f"Step 2 answer for {q['questionId'][:8]}"}
                for q in step2_qs]
    r = requests.post(f"{API}/cover-letters/{workflow_id}/answers", headers=headers,
                     json={"answers": answers2})
    assert r.status_code in (201, 202), f"Step 2 answers failed: {r.status_code}"
    wf3 = r.json()

    # ── Submit answers for step 3 ──────────────────────────────────
    if wf3.get("currentStep") != 3 and wf3.get("status") == "awaiting_answers":
        r = requests.get(f"{API}/cover-letters/{workflow_id}/questions", headers=headers)
        step3_qs = r.json()
        answers3 = [{"questionId": q["id"], "answerText": f"Step 3 answer for {q['questionId'][:8]}"}
                    for q in step3_qs]
        r = requests.post(f"{API}/cover-letters/{workflow_id}/answers", headers=headers,
                         json={"answers": answers3})
        assert r.status_code in (201, 202), f"Step 3 answers failed: {r.status_code}"

    # ── Get draft ──────────────────────────────────────────────────
    # Draft generation is async (Sprint 4: real LLM generation via
    # Celery, not synchronous template assembly) — a fixed 1s sleep is a
    # guaranteed flake once this can involve a real multi-second OpenAI
    # call (or its fallback), so poll with a realistic timeout instead.
    r = None
    for _ in range(30):
        r = requests.get(f"{API}/cover-letters/{workflow_id}/draft", headers=headers)
        if r.status_code == 200:
            break
        time.sleep(1)
    assert r.status_code == 200, f"Draft failed: {r.status_code} {r.text}"
    draft = r.json()
    assert draft.get("bodyText")
    assert len(draft.get("bodyText", "")) > 100
    print(f"  Draft generated ({len(draft['bodyText'])} chars) ✓")

    # ── Approve ────────────────────────────────────────────────────
    r = requests.post(f"{API}/cover-letters/{workflow_id}/approve", headers=headers)
    assert r.status_code == 200, f"Approve failed: {r.status_code} {r.text}"
    approved = r.json()
    assert approved.get("status") == "approved"
    print(f"  Draft approved ✓")

    print(f"\n  Full chain regression test passed.")