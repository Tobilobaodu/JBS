"""Unit tests for evidence_binder.py — pure functions, no DB, no LLM.

The module this tests is the direct implementation of
10-security-plan.md's evidence-reference content-verification
requirement, so these tests are the primary proof that requirement is
actually satisfied, not just documented.
"""
from types import SimpleNamespace

from app.extraction.evidence_binder import (
    EvidenceCandidate,
    EXPERIENCE,
    EDUCATION,
    SKILL,
    build_candidate_pool,
    bind_evidence_pool,
    count_experience_relevance,
    verify_claim_against_evidence,
)


_UNSET = object()


def _exp(id="exp1", title="Software Engineer", company="Acme Corp",
         bullets=_UNSET, technologies=_UNSET):
    # `is _UNSET`, not `or` — an explicitly-passed empty list must stay
    # empty, not silently fall back to the default fixture content (a
    # real bug caught during test authoring: `technologies or [...]`
    # treats `[]` as falsy and replaces it with the default).
    if bullets is _UNSET:
        bullets = ["Built REST APIs serving 2M requests/day using Python and Docker"]
    if technologies is _UNSET:
        technologies = ["Python", "Docker"]
    return SimpleNamespace(id=id, title=title, company=company, bullets=bullets, technologies=technologies)


def _skill(id="sk1", skill_name="Python"):
    return SimpleNamespace(id=id, skill_name=skill_name)


def _edu(id="ed1", institution="MIT", degree="BSc", field="Computer Science"):
    return SimpleNamespace(id=id, institution=institution, degree=degree, field=field)


def _evidence(support_level, requirement_text, requirement_type="required",
              suggestion=None, warning=None):
    return SimpleNamespace(
        support_level=support_level, requirement_text=requirement_text,
        requirement_type=requirement_type, suggestion=suggestion, warning=warning,
    )


class TestBuildCandidatePool:

    def test_builds_one_candidate_per_row(self):
        pool = build_candidate_pool([_exp()], [_edu()], [_skill()])
        assert len(pool) == 3
        types = {c.row_type for c in pool}
        assert types == {EXPERIENCE, EDUCATION, SKILL}

    def test_experience_searchable_text_includes_bullets_and_technologies(self):
        pool = build_candidate_pool(
            [_exp(bullets=["Led migration to Kubernetes"], technologies=["Kubernetes"])],
            [], [],
        )
        assert "Kubernetes" in pool[0].searchable_text
        assert "Led migration" in pool[0].searchable_text

    def test_skill_searchable_text_is_just_the_name(self):
        pool = build_candidate_pool([], [], [_skill(skill_name="Docker")])
        assert pool[0].searchable_text == "Docker"

    def test_none_fields_do_not_crash(self):
        exp = SimpleNamespace(id="e1", title=None, company=None, bullets=None, technologies=None)
        pool = build_candidate_pool([exp], [], [])
        assert pool[0].searchable_text == ""


class TestBindEvidencePool:

    def test_supported_skill_binds_to_real_skill_row(self):
        pool = build_candidate_pool([], [], [_skill(id="sk1", skill_name="Python")])
        items = [_evidence("supported", "Python")]
        bound = bind_evidence_pool(items, pool)
        assert [c.row_id for c in bound] == ["sk1"]

    def test_partially_supported_binds_via_substring_in_experience(self):
        pool = build_candidate_pool(
            [_exp(id="exp1", bullets=["Built REST APIs at scale"])], [], [],
        )
        items = [_evidence("partially_supported", "REST APIs")]
        bound = bind_evidence_pool(items, pool)
        assert [c.row_id for c in bound] == ["exp1"]

    def test_unsupported_never_binds(self):
        pool = build_candidate_pool([], [], [_skill(skill_name="Kubernetes")])
        items = [_evidence("unsupported", "Kubernetes")]
        assert bind_evidence_pool(items, pool) == []

    def test_contradictory_never_binds(self):
        """The most security-relevant case: contradictory evidence must
        never enter the generation pool, full stop — this is what
        structurally guarantees 09-test-plan.md §6's "never silently
        resolved" requirement, not a convention generation code has to
        remember to respect."""
        pool = build_candidate_pool([_exp(id="exp1")], [], [])
        items = [_evidence("contradictory", "Software Engineer")]
        assert bind_evidence_pool(items, pool) == []

    def test_unclear_never_binds(self):
        pool = build_candidate_pool([_exp(id="exp1")], [], [])
        items = [_evidence("unclear", "Software Engineer")]
        assert bind_evidence_pool(items, pool) == []

    def test_no_matching_row_yields_no_candidate_not_an_error(self):
        pool = build_candidate_pool([], [], [_skill(skill_name="Python")])
        items = [_evidence("supported", "Rust")]
        assert bind_evidence_pool(items, pool) == []

    def test_dedup_across_multiple_evidence_items(self):
        pool = build_candidate_pool(
            [_exp(id="exp1", bullets=["Built REST APIs using Python and Docker"],
                  technologies=["Python", "Docker"])],
            [], [],
        )
        items = [
            _evidence("supported", "Python"),
            _evidence("partially_supported", "Docker"),
        ]
        bound = bind_evidence_pool(items, pool)
        # Same experience row matches both requirements — must appear once.
        assert [c.row_id for c in bound] == ["exp1"]

    def test_empty_requirement_text_is_skipped(self):
        pool = build_candidate_pool([], [], [_skill(skill_name="Python")])
        items = [_evidence("supported", "")]
        assert bind_evidence_pool(items, pool) == []


class TestCountExperienceRelevance:

    def test_ranks_more_referenced_item_higher(self):
        exp1 = _exp(id="exp1", bullets=["Built APIs"], technologies=["Python", "Docker"])
        exp2 = _exp(id="exp2", title="Intern", company="Startup", bullets=["Helped with QA"], technologies=[])
        pool = build_candidate_pool([exp1, exp2], [], [])
        items = [
            _evidence("supported", "Python"),
            _evidence("partially_supported", "Docker"),
            _evidence("partially_supported", "APIs"),
        ]
        counts = count_experience_relevance(items, pool)
        assert counts == {"exp1": 3}
        assert "exp2" not in counts

    def test_ignores_ineligible_support_levels(self):
        pool = build_candidate_pool([_exp(id="exp1")], [], [])
        items = [_evidence("unsupported", "Software Engineer")]
        assert count_experience_relevance(items, pool) == {}


class TestVerifyClaimAgainstEvidence:

    _evidence_texts = [
        "Software Engineer Acme Corp Built REST APIs serving 2M requests/day using Python and Docker",
        "Python",
    ]

    def test_faithful_claim_passes(self):
        result = verify_claim_against_evidence(
            "Built REST APIs handling 2M requests per day with Python and Docker.",
            self._evidence_texts, overlap_threshold=0.35,
        )
        assert result.passed

    def test_faithful_reword_passes(self):
        result = verify_claim_against_evidence(
            "Engineered high-throughput REST APIs (2M req/day) in Python, containerized with Docker.",
            self._evidence_texts, overlap_threshold=0.35,
        )
        assert result.passed

    def test_fabricated_number_fails(self):
        """The exact regression case this module was built to catch: a
        single invented statistic dropped into an otherwise-grounded
        claim. Caught a real bug in the first draft of this check during
        implementation — the number regex missed magnitude-suffixed
        numbers (50M) entirely due to a \\b/letter boundary issue."""
        result = verify_claim_against_evidence(
            "Built REST APIs handling 50M requests per day with Python and Docker.",
            self._evidence_texts, overlap_threshold=0.35,
        )
        assert not result.passed
        assert "50M" in result.unsupported_facts

    def test_fabricated_named_entity_fails(self):
        result = verify_claim_against_evidence(
            "Built REST APIs at Google Cloud Platform using Python and Docker.",
            self._evidence_texts, overlap_threshold=0.35,
        )
        assert not result.passed
        assert result.unsupported_facts

    def test_wholesale_invention_fails_on_overlap(self):
        result = verify_claim_against_evidence(
            "Led a team of 12 engineers at a Fortune 500 company managing cloud infrastructure.",
            self._evidence_texts, overlap_threshold=0.35,
        )
        assert not result.passed
        assert "overlap" in result.reason

    def test_empty_claim_fails(self):
        result = verify_claim_against_evidence("", self._evidence_texts, overlap_threshold=0.35)
        assert not result.passed

    def test_empty_evidence_fails(self):
        result = verify_claim_against_evidence("Built REST APIs.", [], overlap_threshold=0.35)
        assert not result.passed

    def test_number_regex_catches_magnitude_suffixed_numbers(self):
        """Direct regression test for the boundary bug found during
        implementation: \\b\\d[\\d,]*\\.?\\d*%?\\b matches nothing at all
        on '50M' because there's no word boundary between a digit and an
        immediately-following letter."""
        result = verify_claim_against_evidence(
            "Managed a $50K budget.", ["Managed a $2K budget for the team offsite."],
            overlap_threshold=0.1,
        )
        assert not result.passed
        assert "$50K" in result.unsupported_facts
