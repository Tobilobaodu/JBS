"""DECOMMISSIONED — moved verbatim from app/workers/worker_jobs.py.
Not imported by the running pipeline. Kept for reference and restore.
See decommissioned/README.md.
"""

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="app.workers.worker_jobs.process_cv_parse",
    queue="cv_parse",
)
def process_cv_parse(self, job_id: str) -> None:
    """Build a structured candidate profile from the canonical merged text.

    1. Load cv_raw_text for the CV file
    2. Segment sections using heading canonicalization
    3. Extract experience, education, skills, certifications, projects
    4. Pperating cv_profile_versions + child tables
    5. Update cv_profiles pointer
    6. Mark CV file status as 'parsed'
    """
    structlog.contextvars.bind_contextvars(job_id=job_id)
    t_start = time.monotonic()
    session = _get_sync_session()
    try:
        from app.db.models import (
            CvProfile, CvProfileVersion,
            CvExperienceItem, CvEducationItem, CvSkillItem,
            CvCertificationItem, CvProjectItem,
        )
        from app.extraction.heading_canonicalizer import (
            canonicalize_heading,
            WORK_EXPERIENCE, EDUCATION, SKILLS, CERTIFICATIONS, PROJECTS, SUMMARY,
            UNKNOWN,
        )
        import hashlib

        job = session.get(ProcessingJob, job_id)
        if job is None:
            logger.error("job_not_found", job_id=job_id)
            return

        job.status = "processing"
        session.commit()

        cv_file = session.get(CvFile, job.source_entity_id)
        if cv_file is None:
            raise ValueError(f"CV file {job.source_entity_id} not found")

        # Load canonical text
        raw_text_row = session.execute(
            select(CvRawText).where(CvRawText.cv_file_id == cv_file.id)
        ).scalar_one_or_none()

        if raw_text_row is None:
            raise ValueError(f"No canonical text for CV file {cv_file.id} — cannot parse.")

        canonical_text = raw_text_row.canonical_text

        # ── Section segmentation ────────────────────────────────────
        lines = canonical_text.split("\n")
        sections: dict[str, list[str]] = {}
        current_section = "preamble"

        # Simple heuristic: a line that is short, possibly uppercase,
        # and matches a known heading pattern starts a new section.
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Check if this line looks like a section heading
            if len(stripped) < 80 and (
                stripped.isupper() or
                stripped[0].isupper() and not stripped.startswith(("http", "www"))
            ):
                section_type, confidence = canonicalize_heading(stripped)
                if section_type != UNKNOWN and confidence >= 0.5:
                    current_section = section_type
                    continue

            sections.setdefault(current_section, []).append(stripped)

        # ── Extract experience items ────────────────────────────────
        # Many real CVs (confirmed directly against a real PDF export)
        # lay a role out as three standalone lines — TITLE, then COMPANY,
        # then the date range — followed by the bullets. _split_role_header
        # only ever sees the date-bearing line itself, so on that layout
        # title/company always come out None even though the loop below
        # walks right past them: they get silently swept up as ordinary
        # trailing bullets of whichever role is "current" at the time (or
        # dropped entirely, for the very first role, before any role is
        # current yet). _reclaim_title_company() looks at the 1-2 lines
        # immediately preceding a role boundary and reclaims them when
        # they plausibly look like a title/company pair rather than prose.
        experience_items: list[dict] = []
        exp_lines = sections.get(WORK_EXPERIENCE, [])
        current_role: dict | None = None
        preamble_lines: list[str] = []  # lines seen before the first role starts

        for line in exp_lines:
            # Detect company/title lines (often have date ranges or look like "Title at Company")
            date_match = _MONTH_DATE_RANGE_RE.search(line) or _BARE_YEAR_RANGE_RE.search(line)
            if date_match and current_role is None:
                # Start the first role — reclaim title/company from
                # whatever preceded it (nowhere else for those lines to
                # have gone until now).
                current_role = _split_role_header(line)
                current_role["line"] = line
                title, company, leftover = _reclaim_title_company(preamble_lines)
                if title and current_role.get("title") is None:
                    current_role["title"] = title
                if company and current_role.get("company") is None:
                    current_role["company"] = company
                for extra in leftover:
                    current_role.setdefault("bullets", []).append(extra)
                continue

            if date_match and current_role is not None:
                # Start a new role — first, try to reclaim a title/company
                # pair from the tail of the PREVIOUS role's bullets, since
                # that's where they'll have landed on the three-line layout.
                bullets = current_role.get("bullets") or []
                title, company, remaining_bullets = _reclaim_title_company(bullets)
                current_role["bullets"] = remaining_bullets
                experience_items.append(current_role)

                current_role = _split_role_header(line)
                current_role["line"] = line
                if title and current_role.get("title") is None:
                    current_role["title"] = title
                if company and current_role.get("company") is None:
                    current_role["company"] = company
                continue

            if current_role is not None:
                current_role.setdefault("bullets", []).append(line.strip())
            else:
                preamble_lines.append(line.strip())

        if current_role is not None:
            experience_items.append(current_role)

        # ── Extract education / certifications / projects ────────────
        education_items = [
            p for line in sections.get(EDUCATION, [])
            if (p := _parse_education_line(line)) is not None
        ][:15]
        certification_items = [
            p for line in sections.get(CERTIFICATIONS, [])
            if (p := _parse_certification_line(line)) is not None
        ][:20]
        project_items = _segment_projects(sections.get(PROJECTS, []))[:15]

        # ── Build cv_profile_versions ───────────────────────────────
        header = _parse_header_block(sections.get("preamble", []))
        profile_payload = {
            "basics": {
                "name": header["name"],
                "email": header["email"],
                "phone": header["phone"],
                "location": header["location"],
                "urls": header["urls"],
                "summary": "\n".join(sections.get(SUMMARY, [])) or None,
            },
            "workExperience": [
                _make_experience_entry(e) for e in experience_items[:20]
            ],
            "education": [_make_education_entry(e) for e in education_items],
            "skills": {
                "technical": _extract_skills_from_lines(sections.get(SKILLS, [])),
                "soft": [],
            },
            "certifications": [_make_certification_entry(c) for c in certification_items],
            "projects": [_make_project_entry(p) for p in project_items],
        }

        # Compute profile hash
        payload_str = json.dumps(profile_payload, sort_keys=True, default=str)
        profile_hash = hashlib.sha256(payload_str.encode()).hexdigest()

        # Get next version number
        max_ver = session.execute(
            select(sa.func.max(CvProfileVersion.version_number)).where(
                CvProfileVersion.cv_file_id == cv_file.id
            )
        ).scalar() or 0
        version_number = max_ver + 1

        # Get source pass IDs
        passes = session.execute(
            select(CvExtractionPass.id).where(
                CvExtractionPass.cv_file_id == cv_file.id
            )
        ).scalars().all()

        # Insert profile version
        pv = CvProfileVersion(
            cv_file_id=cv_file.id,
            user_id=cv_file.user_id,
            trial_session_id=cv_file.trial_session_id,
            version_number=version_number,
            profile_hash=profile_hash,
            schema_version="1.0",
            source_pass_ids=passes if passes else None,
            structured_payload=profile_payload,
            confidence_summary={"overall": 0.75},
            validation_status="partial",
        )
        session.add(pv)
        session.flush()

        # ── Insert child rows ───────────────────────────────────────
        # start_date/end_date are stored as ISO date strings ("YYYY-MM-DD")
        # in the profile payload (JSON-safe, for the JSONB structured_payload
        # column) and only converted to real datetime objects here, at the
        # CvExperienceItem insertion point, whose columns are DateTime typed.
        for entry in experience_items[:20]:
            start_date = entry.get("start_date")
            end_date = entry.get("end_date")
            session.add(CvExperienceItem(
                cv_profile_version_id=pv.id,
                company=entry.get("company"),
                title=entry.get("title"),
                start_date=datetime.fromisoformat(start_date) if start_date else None,
                end_date=datetime.fromisoformat(end_date) if end_date else None,
                current=entry.get("current", False),
                bullets=entry.get("bullets"),
                technologies=entry.get("technologies"),
                confidence=entry.get("confidence", 0.6),
                source_reference=entry.get("source_reference"),
            ))

        for skill_name in (profile_payload.get("skills", {}).get("technical") or []):
            session.add(CvSkillItem(
                cv_profile_version_id=pv.id,
                skill_name=skill_name,
                category="technical",
                confidence=0.7,
            ))

        for entry in education_items:
            session.add(CvEducationItem(
                cv_profile_version_id=pv.id,
                institution=entry.get("institution"),
                degree=entry.get("degree"),
                field=entry.get("field"),
                year=entry.get("year"),
                confidence=entry.get("confidence", 0.6),
                source_reference=entry.get("source_reference"),
            ))

        for entry in certification_items:
            session.add(CvCertificationItem(
                cv_profile_version_id=pv.id,
                name=entry.get("name"),
                issuer=entry.get("issuer"),
                year=entry.get("year"),
                confidence=entry.get("confidence", 0.6),
                source_reference=entry.get("source_reference"),
            ))

        for entry in project_items:
            session.add(CvProjectItem(
                cv_profile_version_id=pv.id,
                name=entry.get("name"),
                description=entry.get("description"),
                technologies=entry.get("technologies"),
                bullets=entry.get("bullets"),
                confidence=entry.get("confidence", 0.6),
                source_reference=entry.get("source_reference"),
            ))

        # ── Update cv_profiles pointer ──────────────────────────────
        existing_profile = session.execute(
            select(CvProfile).where(CvProfile.cv_file_id == cv_file.id)
        ).scalar_one_or_none()

        if existing_profile:
            existing_profile.current_version_id = pv.id
            existing_profile.updated_at = datetime.now(timezone.utc)
        else:
            session.add(CvProfile(
                cv_file_id=cv_file.id,
                current_version_id=pv.id,
            ))

        cv_file.status = "parsed"
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()

        duration_s = time.monotonic() - t_start
        logger.info(
            "cv_parse_complete",
            job_id=job_id,
            cv_id=cv_file.id,
            version=version_number,
            experience_count=len(experience_items),
            education_count=len(education_items),
            certification_count=len(certification_items),
            project_count=len(project_items),
            duration_ms=int(duration_s * 1000),
        )

    except Exception as e:
        duration_s = time.monotonic() - t_start
        logger.error("cv_parse_failed", job_id=job_id, error=str(e))
        try:
            job.status = "failed"
            job.last_error = str(e)
            job.failed_at = datetime.now(timezone.utc)
            cv_file = session.get(CvFile, job.source_entity_id)
            if cv_file:
                cv_file.status = "failed"
                cv_file.error_message = str(e)
            session.commit()
        except Exception:
            session.rollback()
        raise
    finally:
        session.close()
        structlog.contextvars.unbind_contextvars("job_id")


# ── cv_parse helpers ─────────────────────────────────────────────────

# Role-start date range detection. The month-name path is tried first and
# is unchanged from the original regex (zero behavior change for CVs that
# already worked). The bare-year fallback is tried only when the month
# path doesn't match, and only against lines already being evaluated as
# role-start candidates — so it can't misfire on an ordinary bullet that
# happens to mention two years in passing.
_MONTH_DATE_RANGE_RE = re.compile(
    r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b.*?(?:-|–|to).*?(?:\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|\bPresent\b|\bCurrent\b))",
    re.I,
)
_BARE_YEAR_RANGE_RE = re.compile(
    r"\b((?:19|20)\d{2})\b\s*(?:-|–|—|to)\s*(\b(?:19|20)\d{2}\b|Present|Current)\b",
    re.I,
)
_RANGE_SEPARATOR_RE = re.compile(r"\s*(?:-|–|—|to)\s*", re.I)
_MONTH_TOKEN_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{4})\b", re.I
)
_YEAR_TOKEN_RE = re.compile(r"\b(19|20)\d{2}\b")
_MONTH_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
# Common role-title words, used to disambiguate which side of a
# dash-separated "X - Y" role header is the title vs. the company —
# e.g. "OSB Group - UX Design Manager" vs. "UX Design Manager - OSB Group".
_ROLE_KEYWORD_RE = re.compile(
    r"\b(Manager|Engineer|Director|Designer|Analyst|Lead|Specialist|"
    r"Coordinator|Consultant|Officer|Executive|Architect|Developer|Head|"
    r"VP|President)\b",
    re.I,
)


def _parse_role_date_token(token: str) -> str | None:
    """Parse a single date-range endpoint into an ISO 'YYYY-MM-DD' string.

    Returns None for open-ended endpoints ('Present'/'Current') and for
    anything unparseable — never guesses a date.
    """
    token = token.strip()
    if re.match(r"^(present|current)$", token, re.I):
        return None
    m = _MONTH_TOKEN_RE.search(token)
    if m:
        month = _MONTH_NUM.get(m.group(1).lower()[:3])
        if month:
            return f"{int(m.group(2)):04d}-{month:02d}-01"
    m = _YEAR_TOKEN_RE.search(token)
    if m:
        return f"{m.group(0)}-01-01"
    return None


def _split_date_range(range_text: str) -> tuple[str | None, str | None, bool]:
    """Split a matched date-range string into (start_iso, end_iso, is_current)."""
    parts = _RANGE_SEPARATOR_RE.split(range_text.strip(), maxsplit=1)
    if len(parts) != 2:
        return None, None, False
    start_raw, end_raw = parts[0].strip(), parts[1].strip()
    is_current = bool(re.match(r"^(present|current)$", end_raw, re.I))
    start_date = _parse_role_date_token(start_raw)
    end_date = None if is_current else _parse_role_date_token(end_raw)
    return start_date, end_date, is_current


def _split_title_company(header: str) -> tuple[str | None, str | None]:
    """Split a role-header line (with the date range already stripped) into
    (title, company). Never guesses — returns (None, None) when the
    structure isn't confidently recognized, per the codebase's
    nullable-over-invented principle.
    """
    header = header.strip(" -–—|,()").strip()
    if not header:
        return None, None

    if header.count(",") == 1:
        left, right = (p.strip() for p in header.split(",", 1))
        if left and right:
            return left, right

    m = re.search(r"\s+(?:at|@)\s+", header, re.I)
    if m:
        left, right = header[:m.start()].strip(), header[m.end():].strip()
        if left and right:
            return left, right

    m = re.search(r"\s*(?:–|—|-)\s*", header)
    if m:
        left, right = header[:m.start()].strip(), header[m.end():].strip()
        if left and right:
            left_is_role = bool(_ROLE_KEYWORD_RE.search(left))
            right_is_role = bool(_ROLE_KEYWORD_RE.search(right))
            if left_is_role and not right_is_role:
                return left, right
            if right_is_role and not left_is_role:
                return right, left

    return None, None


def _split_role_header(line: str) -> dict:
    """Parse a role-start line into its structured components: strips the
    date range, records start/end/current, and splits the remaining text
    into title/company (or leaves both None if it can't be split with
    confidence).
    """
    date_match = _MONTH_DATE_RANGE_RE.search(line) or _BARE_YEAR_RANGE_RE.search(line)
    entry: dict = {"start_date": None, "end_date": None, "current": False}
    if date_match:
        start_date, end_date, is_current = _split_date_range(date_match.group(0))
        entry["start_date"] = start_date
        entry["end_date"] = end_date
        entry["current"] = is_current
        header = line[:date_match.start()] + " " + line[date_match.end():]
    else:
        header = line
    title, company = _split_title_company(header)
    entry["title"] = title
    entry["company"] = company
    return entry


# Title/company label lines are short standalone lines ("UX DESIGN
# MANAGER", "OSB GROUP") — confirmed against a real CV export that these
# run well under this cap (longest observed: 32 chars), while ordinary
# bullet prose in the same document runs 80+ chars and typically ends in
# sentence-terminal punctuation.
_ROLE_LABEL_MAX_CHARS = 60
_ROLE_LABEL_SENTENCE_END_RE = re.compile(r"[.,:;!?…]\s*$")


def _looks_like_role_label(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > _ROLE_LABEL_MAX_CHARS:
        return False
    return not _ROLE_LABEL_SENTENCE_END_RE.search(stripped)


def _reclaim_title_company(lines: list[str]) -> tuple[str | None, str | None, list[str]]:
    """Some real CVs lay a role out as three standalone lines — TITLE,
    then COMPANY, then the date range — rather than combining them on
    one line the way _split_role_header expects. On that layout, the
    title/company end up as the last 1-2 lines immediately preceding the
    date-bearing line, misattributed as trailing bullets of whichever
    role was current at the time (or dropped, for the very first role).
    This looks at the trailing entries of *lines* and reclaims them only
    when they plausibly look like label lines, not prose — never guesses
    at just one of the two out of an otherwise clearly-prose tail.
    """
    if len(lines) >= 2 and _looks_like_role_label(lines[-1]) and _looks_like_role_label(lines[-2]):
        return lines[-2].strip(), lines[-1].strip(), lines[:-2]
    if len(lines) >= 1 and _looks_like_role_label(lines[-1]):
        return lines[-1].strip(), None, lines[:-1]
    return None, None, lines


def _make_experience_entry(entry: dict) -> dict:
    return {
        "id": None,
        "company": entry.get("company"),
        "title": entry.get("title"),
        "startDate": entry.get("start_date"),
        "endDate": entry.get("end_date"),
        "current": entry.get("current", False),
        "bullets": entry.get("bullets") or [],
        "technologies": entry.get("technologies") or [],
    }


def _extract_skills_from_lines(lines: list[str]) -> list[str]:
    """Extract comma-separated or bullet-separated skills from a block of lines."""
    skills = []
    for line in lines:
        # Split on commas, bullets, or common separators
        parts = re.split(r"[,;•✦➤►|/]", line)
        for part in parts:
            cleaned = part.strip().strip("•-*").strip()
            if cleaned and len(cleaned) > 1 and len(cleaned) < 60:
                skills.append(cleaned)
    # Deduplicate while preserving order
    seen = set()
    result = []
    for s in skills:
        lower = s.lower()
        if lower not in seen:
            seen.add(lower)
            result.append(s)
    return result[:50]  # cap at 50 skills


# ── header / contact block parsing ───────────────────────────────────
# The 1-5 non-empty lines above the first recognised section heading are,
# on essentially every CV, the name + contact block. worker_jobs.py
# previously hardcoded basics.name/email/phone/location to None and
# exported a CV with no candidate name on it. These helpers recover the
# header conservatively — a field is only extracted on a clear positive
# signal, never guessed from nothing (same non-fabrication discipline as
# the rest of the pipeline).

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")
_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s|,;]+"
    r"|\b[A-Za-z0-9-]+\.(?:com|co\.uk|io|net|org|me|dev|design|co)\b(?:/[^\s|,;]*)?",
    re.I,
)
_NAME_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'’-]*$")
_UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")


def _looks_like_name(line: str) -> bool:
    """True when a line plausibly is a person's name: no digits, no
    email/url/phone, 2-4 clean word tokens, title-case or all-caps."""
    if not line or any(ch.isdigit() for ch in line):
        return False
    if _EMAIL_RE.search(line) or _URL_RE.search(line) or _PHONE_RE.search(line):
        return False
    words = line.split()
    if not 2 <= len(words) <= 4:
        return False
    if not all(_NAME_WORD_RE.match(w) for w in words):
        return False
    return line.isupper() or line.istitle()


def _parse_header_block(preamble_lines: list[str]) -> dict:
    """Extract {name, email, phone, location, urls} from the CV preamble.
    All fields None/[] when nothing is recoverable.
    """
    name = None
    email = None
    phone = None
    location = None
    urls: list[str] = []

    for raw in preamble_lines:
        line = raw.strip()
        if not line:
            continue

        if email is None:
            m = _EMAIL_RE.search(line)
            if m:
                email = m.group(0).rstrip(".,;")

        if phone is None:
            m = _PHONE_RE.search(line)
            if m:
                phone = m.group(0).strip()

        url_line = line
        if email:
            url_line = url_line.replace(email, " ")
        for m in _URL_RE.finditer(url_line):
            u = m.group(0).strip(" .|,")
            if u and u.lower() not in [x.lower() for x in urls]:
                urls.append(u)

        if name is None and _looks_like_name(line):
            name = line
            continue

        # Location: only a clearly location-shaped leftover. Excludes
        # all-caps or title-case multi-word lines (more likely a name or
        # job title) and anything containing "/" (e.g. "UI/UX").
        if location is None and not _looks_like_name(line):
            tokens = line.split()
            if (
                len(line) <= 40
                and len(tokens) <= 3
                and "/" not in line
                and not any(ch.isdigit() for ch in line)
                and not _EMAIL_RE.search(line)
                and not _URL_RE.search(line)
                and not _PHONE_RE.search(line)
                and not line.isupper()
                and ("," in line or _UK_POSTCODE_RE.search(line) or len(tokens) == 1)
            ):
                location = line

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "location": location,
        "urls": urls,
    }


# ── education / certification / project parsing ─────────────────────
# Comma / en-dash / em-dash / pipe only — deliberately excludes a bare
# hyphen, since institution/field/project names can legitimately contain
# one (e.g. "Machine-Learning Engineering"). Shared by education and
# certification line splitting.
_LABEL_SEPARATOR_RE = re.compile(r"\s*(?:,|–|—|\|)\s*")

_EDU_DEGREE_KEYWORD_RE = re.compile(
    r"\b(Bachelor'?s?|Master'?s?|Doctorate|Ph\.?D\.?|BSc|B\.Sc\.?|BA|B\.A\.?|"
    r"BEng|B\.Eng\.?|BS|B\.S\.?|MSc|M\.Sc\.?|MA|M\.A\.?|MEng|M\.Eng\.?|MS|"
    r"M\.S\.?|MBA|Diploma|Associate|HND|BTech|B\.Tech\.?|MTech|M\.Tech\.?|"
    r"Certificate|Certification|Nanodegree|Bootcamp|Course|Specialization)\b",
    re.I,
)
_EDU_INSTITUTION_KEYWORD_RE = re.compile(
    r"\b(University|College|Institute|Polytechnic|School of|Academy|"
    r"Coursera|Udacity|edX|FutureLearn|LinkedIn Learning|Product School|"
    r"General Assembly|Google|Meta|AWS|Microsoft)\b",
    re.I,
)


def _split_degree_field(segment: str) -> tuple[str | None, str | None]:
    """Split a degree-side segment ('BSc in Computer Science') into
    (degree, field). The caller has already determined this segment IS
    the degree side — this only decides how far to split it, never which
    field an ambiguous fragment belongs to.
    """
    segment = segment.strip()
    if not segment:
        return None, None
    m = re.search(r"\s+in\s+", segment, re.I)
    if m:
        degree = segment[:m.start()].strip()
        field = segment[m.end():].strip()
        return (degree or None), (field or None)
    m = _EDU_DEGREE_KEYWORD_RE.search(segment)
    if m:
        degree = m.group(0)
        remainder = (segment[:m.start()] + " " + segment[m.end():]).strip(" ,-–—").strip()
        return degree, (remainder or None)
    return segment, None


def _parse_education_line(line: str) -> dict | None:
    """Parse one education-section line into {institution, degree, field,
    year, confidence, source_reference}.

    Recognises both traditional academic credentials and modern online
    credentials (Coursera, Udacity, edX, FutureLearn, Product School,
    General Assembly, certificates, bootcamps, specializations...).

    When a line can't be split into a confident degree/institution pair,
    it is preserved as a low-confidence entry (degree=<full line>,
    institution=None, confidence=0.3) rather than dropped — a rendered
    low-confidence qualification beats a silently-discarded real one.
    Only genuinely empty input or a bare year returns None.
    """
    stripped = line.strip()
    if not stripped:
        return None

    year = None
    remainder = stripped
    m = _YEAR_TOKEN_RE.search(stripped)
    if m:
        year = int(m.group(0))
        remainder = (stripped[:m.start()] + " " + stripped[m.end():]).strip(" ()-–—,").strip()

    if not remainder:
        return None  # a bare year alone isn't education evidence

    parts = [p.strip() for p in _LABEL_SEPARATOR_RE.split(remainder, maxsplit=1) if p.strip()]
    if not parts:
        return None

    def _preserve() -> dict:
        return {
            "institution": None,
            "degree": remainder,
            "field": None,
            "year": year,
            "confidence": 0.3,
            "source_reference": stripped,
        }

    institution: str | None = None
    degree: str | None = None
    field: str | None = None

    if len(parts) == 2:
        seg_a, seg_b = parts
        a_is_inst = bool(_EDU_INSTITUTION_KEYWORD_RE.search(seg_a))
        b_is_inst = bool(_EDU_INSTITUTION_KEYWORD_RE.search(seg_b))
        if a_is_inst and not b_is_inst:
            institution, degree_field_seg = seg_a, seg_b
        elif b_is_inst and not a_is_inst:
            institution, degree_field_seg = seg_b, seg_a
        else:
            a_is_deg = bool(_EDU_DEGREE_KEYWORD_RE.search(seg_a))
            b_is_deg = bool(_EDU_DEGREE_KEYWORD_RE.search(seg_b))
            if a_is_deg and not b_is_deg:
                degree_field_seg, institution = seg_a, seg_b
            elif b_is_deg and not a_is_deg:
                degree_field_seg, institution = seg_b, seg_a
            else:
                return _preserve()  # ambiguous — preserve, don't discard
        degree, field = _split_degree_field(degree_field_seg)
    else:  # len(parts) == 1
        seg = parts[0]
        if _EDU_INSTITUTION_KEYWORD_RE.search(seg):
            institution = seg
        elif _EDU_DEGREE_KEYWORD_RE.search(seg):
            degree, field = _split_degree_field(seg)
        else:
            return _preserve()

    if degree is None and institution is None:
        return _preserve()

    return {
        "institution": institution,
        "degree": degree,
        "field": field,
        "year": year,
        "confidence": 0.6,
        "source_reference": stripped,
    }


def _parse_certification_line(line: str) -> dict | None:
    """Parse one certifications-section line into {name, issuer, year,
    confidence, source_reference}. By convention the first segment is
    always the credential name — real certification lines overwhelmingly
    follow 'Cert Name – Issuer (Year)' order, and unlike education there's
    no keyword signal available to disambiguate order.
    """
    stripped = line.strip()
    if not stripped:
        return None

    year = None
    remainder = stripped
    m = _YEAR_TOKEN_RE.search(stripped)
    if m:
        year = int(m.group(0))
        remainder = (stripped[:m.start()] + " " + stripped[m.end():]).strip(" ()-–—,").strip()

    if not remainder:
        return None

    parts = [p.strip() for p in _LABEL_SEPARATOR_RE.split(remainder, maxsplit=1) if p.strip()]
    if not parts or not parts[0]:
        return None

    return {
        "name": parts[0],
        "issuer": parts[1] if len(parts) > 1 else None,
        "year": year,
        "confidence": 0.6,
        "source_reference": stripped,
    }


_PROJECT_TECH_LABEL_RE = re.compile(
    r"(?:Technologies|Tech\s*stack|Built\s*with|Stack)\s*:\s*", re.I
)
_PROJECT_PARENTHETICAL_RE = re.compile(r"\(([^()]+)\)\s*$")
_BULLET_MARKER_RE = re.compile(r"^\s*[•\-\*➤✦►]\s*")


def _split_project_title(line: str) -> tuple[str, list[str]]:
    """Split a project title line into (name, technologies). A trailing
    parenthetical with 2+ comma-separated tokens is a confident tech-
    stack signal and gets stripped out; a single-token parenthetical
    (e.g. '(Personal Project)', '(2022)') is left alone — too ambiguous
    to confidently classify as a tech list vs. a status/date label, so it
    stays part of the display name rather than being guessed at.
    """
    stripped = line.strip()

    m = _PROJECT_PARENTHETICAL_RE.search(stripped)
    if m:
        tokens = [t.strip() for t in m.group(1).split(",") if t.strip()]
        if len(tokens) >= 2:
            name = stripped[:m.start()].strip(" -–—")
            return (name or stripped), tokens

    m = _PROJECT_TECH_LABEL_RE.search(stripped)
    if m:
        name = stripped[:m.start()].strip(" -–—")
        tokens = [t.strip() for t in stripped[m.end():].split(",") if t.strip()]
        return (name or stripped), tokens

    return stripped, []


def _segment_projects(lines: list[str]) -> list[dict]:
    """Stateful segmentation of the PROJECTS section into project blocks.
    Projects have no reliable date anchor (unlike experience roles), so
    the boundary signal is bullet-marker vs. label-shaped-line instead: a
    bullet-marked line is always a continuation of the current project;
    an unmarked line starts a new project if it's the first line in the
    section or looks label-shaped (reuses _looks_like_role_label, the
    same heuristic already proven against a real CV export for
    experience title/company lines); any other unmarked line while a
    project is open is a continuation description line, not a new title.
    """
    def _close(proj: dict) -> dict:
        name, technologies = _split_project_title(proj["title_line"])
        return {
            "name": name,
            "description": proj.get("description"),
            "technologies": technologies,
            "bullets": proj.get("bullets", []),
            "confidence": 0.6,
            "source_reference": proj["title_line"],
        }

    projects: list[dict] = []
    current: dict | None = None

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue

        bullet_match = _BULLET_MARKER_RE.match(stripped)
        if bullet_match:
            content = stripped[bullet_match.end():].strip()
            if current is not None and content:
                current.setdefault("bullets", []).append(content)
            continue

        if current is None or _looks_like_role_label(stripped):
            if current is not None:
                projects.append(_close(current))
            current = {"title_line": stripped, "bullets": []}
            continue

        if current.get("description"):
            current["description"] = current["description"] + " " + stripped
        else:
            current["description"] = stripped

    if current is not None:
        projects.append(_close(current))

    return projects


def _make_education_entry(entry: dict) -> dict:
    return {
        "institution": entry.get("institution"),
        "degree": entry.get("degree"),
        "field": entry.get("field"),
        "year": entry.get("year"),
    }


def _make_certification_entry(entry: dict) -> dict:
    return {
        "name": entry.get("name"),
        "issuer": entry.get("issuer"),
        "year": entry.get("year"),
    }


def _make_project_entry(entry: dict) -> dict:
    return {
        "name": entry.get("name"),
        "description": entry.get("description"),
        "technologies": entry.get("technologies") or [],
        "bullets": entry.get("bullets") or [],
    }


