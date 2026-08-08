from app.extraction.job_post_parser import RulesBasedJobPostParser


def test_mixed_bullet_formats_are_extracted():
    text = """Requirements:
- 5+ years Python
1. AWS experience
• Docker
"""

    result = RulesBasedJobPostParser().parse(text)

    print("qualifications:", result.qualifications)
    print("responsibilities:", result.responsibilities)

    assert result.qualifications, "qualifications should be non-empty"

    qualifications = " ".join(result.qualifications).lower()
    assert "python" in qualifications
    assert "aws" in qualifications
    assert "docker" in qualifications