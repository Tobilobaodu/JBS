"""Guards that do not depend on the model obeying the prompt.

Both were added after the prompt was asked, in words, to do these things
and did not: a product-design CV scored 85/100 "Good match" against an HR
People Experience Lead role, and the tailored CV placed the candidate in
"Dublin, Ireland" (the job's city) and "London, United Kingdom" against a
CV containing no location at all.
"""

import pytest

from app.services import resume_rewrite as rr

CV_NO_LOCATION = """TOBILOBA ODU
PRODUCT DESIGNER, UI/UX and RESEARCH
tobilobaodu.com | oduoluwatobi@gmail.com | +447562695548

PROFILE
Product Designer with seven years of experience across UX research, UI
design, design systems, and conversion focused digital optimisation.
"""

CV_WITH_LOCATION = CV_NO_LOCATION.replace(
    "PRODUCT DESIGNER, UI/UX and RESEARCH",
    "PRODUCT DESIGNER, UI/UX and RESEARCH\nManchester, United Kingdom",
)


class TestStripInventedLocations:
    def test_removes_the_jobs_city_when_the_cv_has_none(self):
        md = "# TOBILOBA ODU\nDublin, Ireland\n\n## Professional Summary\nCopy."
        out, removed = rr._strip_invented_locations(md, CV_NO_LOCATION)
        assert "Dublin" not in out
        assert removed == ["Dublin, Ireland"]

    def test_removes_a_three_part_place(self):
        md = "### UX DESIGN MANAGER - OSB GROUP\nLondon, England, United Kingdom"
        out, removed = rr._strip_invented_locations(md, CV_NO_LOCATION)
        assert "London" not in out
        assert removed == ["London, England, United Kingdom"]

    def test_keeps_a_location_the_cv_actually_states(self):
        md = "# TOBILOBA ODU\nManchester, United Kingdom\n\n## Summary"
        out, removed = rr._strip_invented_locations(md, CV_WITH_LOCATION)
        assert "Manchester, United Kingdom" in out
        assert removed == []

    def test_keeps_a_line_whose_first_part_appears_in_the_cv(self):
        # "Manchester" alone is enough to treat the line as supported —
        # better to keep a slightly-off location than delete a real one.
        md = "# NAME\nManchester, England"
        out, removed = rr._strip_invented_locations(md, CV_WITH_LOCATION)
        assert "Manchester, England" in out
        assert removed == []

    def test_leaves_headings_bullets_and_skills_alone(self):
        md = "\n".join(
            [
                "# TOBILOBA ODU",
                "## Core Skills",
                "- Figma, Sketch, Framer",
                "### LEAD UI/UX DESIGNER - ISIXTY VISUAL DESIGN COMPANY",
                "MARCH 2021 - MARCH 2022",
                "Designed and delivered onboarding flows.",
            ]
        )
        out, removed = rr._strip_invented_locations(md, CV_NO_LOCATION)
        assert removed == []
        assert out == md

    def test_leaves_a_location_inside_a_sentence_alone(self):
        # Only whole lines that are nothing but a place are touched.
        md = "Relocated the design team to Dublin, Ireland during the merger."
        out, removed = rr._strip_invented_locations(md, CV_NO_LOCATION)
        assert removed == []
        assert out == md

    def test_empty_markdown(self):
        out, removed = rr._strip_invented_locations("", CV_NO_LOCATION)
        assert out == "" and removed == []


class TestInventedLocationRemovedFromRewrite:
    """The cross-occupation-cap/score guards moved to resume_analysis.py
    with the rest of the stats (see test_resume_analysis_guards.py) — v4
    (jbs-solution-sheet.md S1) split generation from analysis, and
    generation no longer produces or receives a score. This is what's left
    of the old TestCrossOccupationCap that's still resume_rewrite.py's own
    concern: the location safety net operating on an actual rewrite call."""

    def test_invented_location_is_removed_and_asked_about(self, monkeypatch):
        class _Result:
            data = {
                "tailoredResumeMarkdown": (
                    "# TOBILOBA ODU\nDublin, Ireland\n\n## Summary\nCopy."
                ),
            }
            prompt_tokens = 10
            completion_tokens = 10
            model = "test-model"

        monkeypatch.setattr(rr, "generate_structured", lambda **kwargs: _Result())
        out = rr.rewrite_resume(
            cv_text=CV_NO_LOCATION, job_post_text="People Experience Lead. " * 10
        )
        assert "Dublin" not in out.tailored_resume_markdown
        assert "Where are you based" in out.information_needed[0]
        assert "Dublin, Ireland" in out.information_needed[0]


JOB_POST = """HR Business Partner
Must-Haves:
5+ years of HR Business Partner experience or strong HR Generalist experience
Employee relations experience including investigations, conflict resolution, and performance management
Experience applying GDPR and data privacy standards in HR practices
High level of discretion and confidentiality
Willingness to travel throughout the region (approximately 10%)
Experience with Workday HRIS
"""

HR_CV = """Adeola Odu (Assoc. CIPD)
adeolaodusote@gmail.com

PERSONAL STATEMENT
Value-driven HR professional with extensive experience and knowledge of HR
practices and policies.

EXPERIENCE
Deputy HR Manager - X3M Marketing Ideas Limited
Coordinated employee relations processes including investigations,
disciplinary procedures and grievance hearings, and managed retention
initiatives that reduced turnover by 20%.
Maintained HRIS records and applied GDPR data privacy standards.
"""

TRAVEL_CLAIM = "Willing to travel throughout the region (approximately 10%)."


class TestStripLiftedRequirements:
    """The reported case: a requirement the CV never mentions, copied out of
    the job post and asserted on the candidate's behalf."""

    def test_removes_a_requirement_the_cv_never_mentions(self):
        md = "## Additional Information\n- " + TRAVEL_CLAIM
        out, removed = rr._strip_lifted_requirements(md, HR_CV, JOB_POST)
        assert removed == [TRAVEL_CLAIM]
        assert "travel" not in out

    def test_the_stranded_heading_goes_with_it(self):
        md = (
            "## Professional Summary\nHR professional.\n\n"
            "## Additional Information\n- " + TRAVEL_CLAIM
        )
        out, _ = rr._strip_lifted_requirements(md, HR_CV, JOB_POST)
        assert "Additional Information" not in out
        assert "Professional Summary" in out

    def test_keeps_a_bullet_the_cv_actually_evidences(self):
        # Heavily echoes the job post's wording, but the CV says it too.
        md = (
            "- Coordinated employee relations processes including "
            "investigations, disciplinary procedures and grievance hearings."
        )
        out, removed = rr._strip_lifted_requirements(md, HR_CV, JOB_POST)
        assert removed == []
        assert out == md

    def test_keeps_a_skills_line_drawn_from_both(self):
        md = "- **HR Systems**: Workday HRIS, GDPR data privacy standards"
        _, removed = rr._strip_lifted_requirements(md, HR_CV, JOB_POST)
        assert removed == []

    def test_short_generic_lines_are_left_alone(self):
        # Too few content words to judge either way.
        md = "- Workday HRIS"
        out, removed = rr._strip_lifted_requirements(md, HR_CV, JOB_POST)
        assert removed == []
        assert out == md

    def test_headings_are_never_removed_as_lifted(self):
        md = "## Employee Relations Investigations And Conflict Resolution\nCopy."
        _, removed = rr._strip_lifted_requirements(md, HR_CV, JOB_POST)
        assert removed == []

    def test_no_job_post_means_no_stripping(self):
        md = "- " + TRAVEL_CLAIM
        out, removed = rr._strip_lifted_requirements(md, HR_CV, "")
        assert removed == []
        assert out == md

    def test_stemming_bridges_willingness_and_willing(self):
        # The exact near-miss: without stemming these score 0.75 and the
        # copied claim survives.
        assert rr._stem("willingness") == rr._stem("willing")

    def test_stemmer_does_not_destroy_short_words(self):
        assert rr._stem("region") == "region"
        assert rr._stem("laws") == "laws"


class TestLiftedRequirementsSurfaceAsQuestions:
    def test_removal_becomes_an_information_needed_question(self, monkeypatch):
        class _Result:
            data = {
                "tailoredResumeMarkdown": (
                    "# ADEOLA ODU\n\n## Additional Information\n- " + TRAVEL_CLAIM
                ),
            }
            prompt_tokens = 1
            completion_tokens = 1
            model = "test-model"

        monkeypatch.setattr(rr, "generate_structured", lambda **kw: _Result())
        out = rr.rewrite_resume(cv_text=HR_CV, job_post_text=JOB_POST)

        assert "travel" not in out.tailored_resume_markdown
        assert "Additional Information" not in out.tailored_resume_markdown
        question = out.information_needed[0]
        assert "Can you confirm" in question
        assert "travel" in question

    def test_removes_an_unsupported_paraphrase(self):
        # v3 rephrased the requirement to dodge a verbatim match: 0.75
        # lifted, just under the near-verbatim bar — but 0.00 support. A
        # line sharing no content word with the CV is not from the CV.
        md = "- Willingness to travel as required throughout the region"
        out, removed = rr._strip_lifted_requirements(md, HR_CV, JOB_POST)
        assert removed == ["Willingness to travel as required throughout the region"]
        assert out == ""

    def test_a_paraphrase_with_any_cv_support_survives(self):
        md = "- Applied GDPR and data privacy standards across HRIS records"
        _, removed = rr._strip_lifted_requirements(md, HR_CV, JOB_POST)
        assert removed == []
