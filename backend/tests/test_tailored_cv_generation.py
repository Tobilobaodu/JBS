"""Tests for tailored_cv_generation.py's orchestrator, against a fake LLM
client — no real API calls anywhere in this file. Covers the
09-test-plan.md §6 checklist directly: evidence traceability, empty-
section omission, fabrication resistance, contradictory/unclear
exclusion, and generation_task/prompt_version/model_id provenance.
"""
import json
from types import SimpleNamespace

from app.services.tailored_cv_generation import (
    generate_draft_sections,
    assemble_content_json,
    render_text_from_sections,
    build_validation_result,
    build_improvement_checklist,
    SECTION_SUMMARY,
    SECTION_EXPERIENCE,
    SECTION_SKILLS,
)


def _exp(id="exp1", title="Software Engineer", company="Acme Corp",
         bullets=None, technologies=None):
    return SimpleNamespace(
        id=id, title=title, company=company,
        bullets=bullets if bullets is not None else
        ["Built REST APIs serving 2M requests/day using Python and Docker"],
        technologies=technologies if technologies is not None else ["Python", "Docker"],
    )


def _skill(id="sk1", skill_name="Python"):
    return SimpleNamespace(id=id, skill_name=skill_name)


def _evidence(support_level, requirement_text, requirement_type="required",
              suggestion=None, warning=None):
    return SimpleNamespace(
        support_level=support_level, requirement_text=requirement_text,
        requirement_type=requirement_type, suggestion=suggestion, warning=warning,
    )


class FakeCompletions:
    """Returns a fixed, faithful response for every call by default;
    tests can override via a response queue for failure-path testing."""

    def __init__(self, content_text="Experienced Python engineer building REST APIs.",
                 evidence_indexes=None, responses=None):
        self.calls = []
        self._default_content_text = content_text
        self._default_evidence_indexes = evidence_indexes if evidence_indexes is not None else [0]
        self._responses = list(responses) if responses is not None else None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._responses is not None:
            item = self._responses.pop(0)
            if isinstance(item, Exception):
                raise item
            content = json.dumps(item)
        else:
            content = json.dumps({
                "contentText": self._default_content_text,
                "evidenceIndexes": self._default_evidence_indexes,
            })
        message = SimpleNamespace(content=content, refusal=None)
        choice = SimpleNamespace(message=message)
        usage = SimpleNamespace(prompt_tokens=50, completion_tokens=20)
        return SimpleNamespace(choices=[choice], usage=usage, model="gpt-4o-mini-2024-07-18")


class FakeClient:
    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(completions=FakeCompletions(**kwargs))


class TestGenerateDraftSections:

    def test_faithful_generation_produces_summary_experience_skills(self):
        exp = _exp()
        skill = _skill()
        evidence_items = [
            _evidence("supported", "Python"),
            _evidence("partially_supported", "REST APIs"),
        ]
        client = FakeClient()

        outcome = generate_draft_sections(
            match_evidence_items=evidence_items,
            experience_items=[exp],
            education_items=[],
            skill_items=[skill],
            job_requirements=["Python", "REST APIs"],
            llm_client_override=client,
        )

        section_types = [s.section_type for s in outcome.sections]
        assert SECTION_SUMMARY in section_types
        assert SECTION_EXPERIENCE in section_types
        assert SECTION_SKILLS in section_types
        assert outcome.issues == []

    def test_every_section_has_generation_task_prompt_version_model_id(self):
        """09-test-plan.md §6: 'Every tailored_cv_sections row ... has
        generation_task, prompt_version, and model_id populated ... from
        Phase 3 onward'."""
        exp = _exp()
        skill = _skill()
        evidence_items = [_evidence("supported", "Python")]
        client = FakeClient()

        outcome = generate_draft_sections(
            match_evidence_items=evidence_items,
            experience_items=[exp],
            education_items=[],
            skill_items=[skill],
            job_requirements=["Python"],
            llm_client_override=client,
        )

        assert len(outcome.sections) > 0
        for section in outcome.sections:
            assert section.generation_task, f"{section.section_type} missing generation_task"
            assert section.model_id, f"{section.section_type} missing model_id"
            # prompt_version is None only for the deterministic skills section
            if section.section_type != SECTION_SKILLS:
                assert section.prompt_version, f"{section.section_type} missing prompt_version"

    def test_section_with_no_evidence_is_omitted_not_placeholder(self):
        """09-test-plan.md §6: 'A section with no evidence available is
        omitted from the draft entirely, not filled with a vague or
        invented placeholder.'"""
        client = FakeClient()
        outcome = generate_draft_sections(
            match_evidence_items=[],  # nothing to bind at all
            experience_items=[_exp()],
            education_items=[],
            skill_items=[_skill()],
            job_requirements=["Python"],
            llm_client_override=client,
        )
        assert outcome.sections == []
        assert len(client.chat.completions.calls) == 0, "must not call the LLM with an empty evidence pool"
        assert any("no evidence available" in issue for issue in outcome.issues)

    def test_fabricated_claim_is_rejected_retried_then_omitted(self):
        """09-test-plan.md §6's 'tempt fabrication' case: every attempt
        returns a claim with a number never present in evidence — must be
        rejected every time and end up omitted, never persisted."""
        exp = _exp(bullets=["Built REST APIs serving 2M requests/day"], technologies=[])
        evidence_items = [_evidence("partially_supported", "REST APIs")]
        client = FakeClient(content_text="Handled 50M requests per day at massive scale.")

        outcome = generate_draft_sections(
            match_evidence_items=evidence_items,
            experience_items=[exp],
            education_items=[],
            skill_items=[],
            job_requirements=["REST APIs"],
            llm_client_override=client,
        )

        experience_sections = [s for s in outcome.sections if s.section_type == SECTION_EXPERIENCE]
        assert experience_sections == []
        assert any("failed verification" in issue for issue in outcome.issues)

    def test_corrective_retry_can_succeed_on_second_attempt(self):
        exp = _exp(bullets=["Built REST APIs serving 2M requests/day"], technologies=[])
        evidence_items = [_evidence("partially_supported", "REST APIs")]
        client = FakeClient(responses=[
            {"contentText": "Handled 50M requests per day.", "evidenceIndexes": [0]},  # rejected
            {"contentText": "Built REST APIs handling 2M requests per day.", "evidenceIndexes": [0]},  # passes
        ])

        outcome = generate_draft_sections(
            match_evidence_items=evidence_items,
            experience_items=[exp],
            education_items=[],
            skill_items=[],
            job_requirements=["REST APIs"],
            llm_client_override=client,
        )

        experience_sections = [s for s in outcome.sections if s.section_type == SECTION_EXPERIENCE]
        assert len(experience_sections) == 1
        assert "2M" in experience_sections[0].content_text

    def test_evidence_indexes_out_of_range_are_ignored_not_crashed(self):
        exp = _exp()
        evidence_items = [_evidence("supported", "Python")]
        client = FakeClient(evidence_indexes=[99])  # invalid index — pool only has 1 candidate

        outcome = generate_draft_sections(
            match_evidence_items=evidence_items,
            experience_items=[exp],
            education_items=[],
            skill_items=[],
            job_requirements=["Python"],
            llm_client_override=client,
        )
        # No valid cited candidates -> correction loop -> exhausted -> omitted
        experience_sections = [s for s in outcome.sections if s.section_type == SECTION_EXPERIENCE]
        assert experience_sections == []

    def test_skills_section_makes_no_llm_call(self):
        client = FakeClient()
        outcome = generate_draft_sections(
            match_evidence_items=[_evidence("supported", "Python")],
            experience_items=[],
            education_items=[],
            skill_items=[_skill()],
            job_requirements=["Python"],
            llm_client_override=client,
        )
        skills_sections = [s for s in outcome.sections if s.section_type == SECTION_SKILLS]
        assert len(skills_sections) == 1
        assert skills_sections[0].model_id == "rules-based"
        assert skills_sections[0].prompt_version is None

    def test_max_experience_items_cap_is_respected(self, monkeypatch):
        from app.core.config import settings
        monkeypatch.setattr(settings, "tailored_cv_max_experience_items", 1)

        exp1 = _exp(id="exp1", bullets=["Built APIs"], technologies=["Python"])
        exp2 = _exp(id="exp2", title="Backend Dev", company="Other Co",
                    bullets=["Wrote services"], technologies=["Python"])
        evidence_items = [_evidence("supported", "Python")]
        client = FakeClient()

        outcome = generate_draft_sections(
            match_evidence_items=evidence_items,
            experience_items=[exp1, exp2],
            education_items=[],
            skill_items=[],
            job_requirements=["Python"],
            llm_client_override=client,
        )
        experience_sections = [s for s in outcome.sections if s.section_type == SECTION_EXPERIENCE]
        assert len(experience_sections) == 1


class TestAssembleAndRender:

    def test_content_json_and_render_text_are_ordered(self):
        from app.services.tailored_cv_generation import SectionResult
        sections = [
            SectionResult(SECTION_SKILLS, "Python", ["sk1"], "tailored_cv_skills", None, "rules-based", "passed", 1),
            SectionResult(SECTION_SUMMARY, "Summary text", ["exp1"], "tailored_cv_summary", "v1", "gpt-4o-mini", "passed", 0),
        ]
        content_json = assemble_content_json(sections)
        assert [s["sectionType"] for s in content_json["sections"]] == [SECTION_SUMMARY, SECTION_SKILLS]

        rendered = render_text_from_sections(sections)
        assert rendered.index("Summary text") < rendered.index("Python")

    def test_validation_result_passed_true_when_any_section_exists(self):
        from app.services.tailored_cv_generation import SectionResult, GenerationOutcome
        outcome = GenerationOutcome(
            sections=[SectionResult(SECTION_SKILLS, "Python", ["sk1"], "tailored_cv_skills", None, "rules-based", "passed", 0)],
            issues=["summary: no evidence available, section omitted"],
        )
        result = build_validation_result(outcome)
        assert result["passed"] is True
        assert result["issues"] == ["summary: no evidence available, section omitted"]

    def test_validation_result_passed_false_when_no_sections(self):
        from app.services.tailored_cv_generation import GenerationOutcome
        outcome = GenerationOutcome(sections=[], issues=["summary: no evidence available, section omitted"])
        assert build_validation_result(outcome)["passed"] is False


class TestImprovementChecklist:

    def test_excludes_supported_items(self):
        items = [_evidence("supported", "Python")]
        assert build_improvement_checklist(items) == []

    def test_contradictory_and_unclear_are_surfaced_here_not_generation(self):
        """This is their only path to visibility — 09-test-plan.md §6's
        'never silently resolved' requirement."""
        items = [
            _evidence("contradictory", "Team Lead", warning="Conflicting titles at AcmeCorp."),
            _evidence("unclear", "Cloud experience"),
        ]
        checklist = build_improvement_checklist(items)
        assert len(checklist) == 2
        support_levels = {c["supportLevel"] for c in checklist}
        assert support_levels == {"contradictory", "unclear"}

    def test_priority_high_for_required_unsupported(self):
        items = [_evidence("unsupported", "Kubernetes", requirement_type="required")]
        checklist = build_improvement_checklist(items)
        assert checklist[0]["priority"] == "high"

    def test_priority_low_for_preferred_partially_supported(self):
        items = [_evidence("partially_supported", "GraphQL", requirement_type="preferred")]
        checklist = build_improvement_checklist(items)
        assert checklist[0]["priority"] == "low"

    def test_uses_existing_suggestion_or_warning_before_template(self):
        items = [_evidence("unsupported", "Kubernetes", suggestion="Custom suggestion text")]
        checklist = build_improvement_checklist(items)
        assert checklist[0]["suggestion"] == "Custom suggestion text"

    def test_falls_back_to_template_when_no_suggestion_or_warning(self):
        items = [_evidence("unsupported", "Kubernetes")]
        checklist = build_improvement_checklist(items)
        assert "Kubernetes" in checklist[0]["suggestion"]
