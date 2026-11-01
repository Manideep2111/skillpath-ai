from decimal import Decimal

from src.services.prerequisite_eligibility import (
    PrerequisiteEligibilityHelper,
)


def test_foundational_skill_passes_without_prerequisites():
    result = PrerequisiteEligibilityHelper.check_prerequisites(
        content_id="CNT-001",
        mapped_skills=[
            ("SKL-001", "Python Basics", Decimal("1.00"))
        ],
        prerequisites_by_skill={},
        mastery_map={},
    )

    assert result.is_eligible is True
    assert result.rejection_code is None


def test_mastery_equal_to_threshold_passes():
    result = PrerequisiteEligibilityHelper.check_prerequisites(
        content_id="CNT-002",
        mapped_skills=[
            ("SKL-002", "Advanced Python", Decimal("1.00"))
        ],
        prerequisites_by_skill={
            "SKL-002": [
                (
                    "SKL-001",
                    "Python Basics",
                    Decimal("0.70"),
                    True,
                )
            ]
        },
        mastery_map={
            "SKL-001": Decimal("0.7000")
        },
    )

    assert result.is_eligible is True


def test_mastery_below_threshold_fails():
    result = PrerequisiteEligibilityHelper.check_prerequisites(
        content_id="CNT-003",
        mapped_skills=[
            ("SKL-002", "Advanced Python", Decimal("1.00"))
        ],
        prerequisites_by_skill={
            "SKL-002": [
                (
                    "SKL-001",
                    "Python Basics",
                    Decimal("0.70"),
                    True,
                )
            ]
        },
        mastery_map={
            "SKL-001": Decimal("0.6999")
        },
    )

    assert result.is_eligible is False
    assert result.rejection_code == "PREREQUISITES_UNMET"
    assert len(result.failures) == 1


def test_unknown_mastery_fails_even_at_zero_threshold():
    result = PrerequisiteEligibilityHelper.check_prerequisites(
        content_id="CNT-004",
        mapped_skills=[
            ("SKL-002", "Advanced Python", Decimal("1.00"))
        ],
        prerequisites_by_skill={
            "SKL-002": [
                (
                    "SKL-001",
                    "Python Basics",
                    Decimal("0.00"),
                    True,
                )
            ]
        },
        mastery_map={
            "SKL-001": None
        },
    )

    assert result.is_eligible is False
    assert result.rejection_code == "PREREQUISITE_UNKNOWN"
    assert result.failures[0].is_unknown is True


def test_measured_zero_passes_zero_threshold():
    result = PrerequisiteEligibilityHelper.check_prerequisites(
        content_id="CNT-005",
        mapped_skills=[
            ("SKL-002", "Advanced Python", Decimal("1.00"))
        ],
        prerequisites_by_skill={
            "SKL-002": [
                (
                    "SKL-001",
                    "Python Basics",
                    Decimal("0.00"),
                    True,
                )
            ]
        },
        mastery_map={
            "SKL-001": Decimal("0.0000")
        },
    )

    assert result.is_eligible is True


def test_optional_prerequisite_does_not_block():
    result = PrerequisiteEligibilityHelper.check_prerequisites(
        content_id="CNT-006",
        mapped_skills=[
            ("SKL-002", "Advanced Python", Decimal("1.00"))
        ],
        prerequisites_by_skill={
            "SKL-002": [
                (
                    "SKL-001",
                    "Optional Python Topic",
                    Decimal("0.70"),
                    False,
                )
            ]
        },
        mastery_map={
            "SKL-001": None
        },
    )

    assert result.is_eligible is True


def test_unmet_prerequisite_on_secondary_skill_blocks_content():
    result = PrerequisiteEligibilityHelper.check_prerequisites(
        content_id="CNT-007",
        mapped_skills=[
            ("SKL-A", "Primary Skill", Decimal("1.00")),
            ("SKL-B", "Secondary Skill", Decimal("0.50")),
        ],
        prerequisites_by_skill={
            "SKL-A": [
                ("SKL-P1", "Parent One", Decimal("0.70"), True)
            ],
            "SKL-B": [
                ("SKL-P2", "Parent Two", Decimal("0.70"), True)
            ],
        },
        mastery_map={
            "SKL-P1": Decimal("0.9000"),
            "SKL-P2": Decimal("0.4000"),
        },
    )

    assert result.is_eligible is False
    assert len(result.failures) == 1
    assert result.failures[0].target_skill_id == "SKL-B"
    assert result.failures[0].prerequisite_skill_id == "SKL-P2"


def test_zero_relevance_skill_is_ignored():
    result = PrerequisiteEligibilityHelper.check_prerequisites(
        content_id="CNT-008",
        mapped_skills=[
            ("SKL-A", "Primary Skill", Decimal("1.00")),
            ("SKL-B", "Zero Relevance Skill", Decimal("0.00")),
        ],
        prerequisites_by_skill={
            "SKL-A": [],
            "SKL-B": [
                ("SKL-P", "Parent Skill", Decimal("0.70"), True)
            ],
        },
        mastery_map={
            "SKL-P": None
        },
    )

    assert result.is_eligible is True


def test_content_without_positive_relevance_skills_is_rejected():
    result = PrerequisiteEligibilityHelper.check_prerequisites(
        content_id="CNT-009",
        mapped_skills=[],
        prerequisites_by_skill={},
        mastery_map={},
    )

    assert result.is_eligible is False
    assert result.rejection_code == "NO_MAPPED_SKILLS"


def test_custom_threshold_is_respected():
    result = PrerequisiteEligibilityHelper.check_prerequisites(
        content_id="CNT-010",
        mapped_skills=[
            ("SKL-ADV", "Advanced Topic", Decimal("1.00"))
        ],
        prerequisites_by_skill={
            "SKL-ADV": [
                ("SKL-P", "Prerequisite", Decimal("0.85"), True)
            ]
        },
        mastery_map={
            "SKL-P": Decimal("0.8000")
        },
    )

    assert result.is_eligible is False
    assert result.failures[0].required_threshold == Decimal("0.85")