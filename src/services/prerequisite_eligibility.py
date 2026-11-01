from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class PrerequisiteFailure:
    """Details about a prerequisite that blocks a recommendation."""

    target_skill_id: str
    target_skill_name: str
    prerequisite_skill_id: str
    prerequisite_skill_name: str
    required_threshold: Decimal
    actual_mastery: Optional[Decimal]
    is_unknown: bool


@dataclass(frozen=True)
class EligibilityResult:
    """Result of checking whether content satisfies prerequisite rules."""

    content_id: str
    is_eligible: bool
    rejection_code: Optional[str] = None
    rejection_reason: Optional[str] = None
    failures: tuple[PrerequisiteFailure, ...] = ()


class PrerequisiteEligibilityHelper:
    """Evaluate prerequisite eligibility without database mutations."""

    @staticmethod
    def check_prerequisites(
        content_id: str,
        mapped_skills: list[tuple[str, str, Decimal]],
        prerequisites_by_skill: dict[
            str, list[tuple[str, str, Decimal, bool]]
        ],
        mastery_map: dict[str, Optional[Decimal]],
    ) -> EligibilityResult:
        """
        Check prerequisite eligibility for a content item.

        mapped_skills:
            (skill_id, skill_name, relevance_weight)

        prerequisites_by_skill:
            target_skill_id -> [
                (prerequisite_skill_id, prerequisite_name,
                 minimum_mastery, is_required)
            ]

        mastery_map:
            skill_id -> mastery level, or None if unknown.
        """

        active_mapped_skills = [
            (skill_id, skill_name, relevance_weight)
            for skill_id, skill_name, relevance_weight in mapped_skills
            if relevance_weight > Decimal("0.00")
        ]

        # Content must address at least one skill.
        if not active_mapped_skills:
            return EligibilityResult(
                content_id=content_id,
                is_eligible=False,
                rejection_code="NO_MAPPED_SKILLS",
                rejection_reason=(
                    "Content has no skills mapped with positive relevance."
                ),
            )

        failures = []

        for target_skill_id, target_skill_name, _ in active_mapped_skills:
            prerequisites = prerequisites_by_skill.get(
                target_skill_id, []
            )

            for (
                prerequisite_skill_id,
                prerequisite_skill_name,
                minimum_mastery,
                is_required,
            ) in prerequisites:

                # Advisory prerequisites do not block eligibility.
                if not is_required:
                    continue

                actual_mastery = mastery_map.get(
                    prerequisite_skill_id
                )

                is_unknown = actual_mastery is None

                # Unknown mastery blocks, even if the threshold is zero.
                # Measured zero remains a valid Decimal value.
                if (
                    is_unknown
                    or actual_mastery < minimum_mastery
                ):
                    failures.append(
                        PrerequisiteFailure(
                            target_skill_id=target_skill_id,
                            target_skill_name=target_skill_name,
                            prerequisite_skill_id=prerequisite_skill_id,
                            prerequisite_skill_name=prerequisite_skill_name,
                            required_threshold=minimum_mastery,
                            actual_mastery=actual_mastery,
                            is_unknown=is_unknown,
                        )
                    )

        if failures:
            has_unknown = any(
                failure.is_unknown for failure in failures
            )

            rejection_code = (
                "PREREQUISITE_UNKNOWN"
                if has_unknown
                else "PREREQUISITES_UNMET"
            )

            first_failure = failures[0]

            if first_failure.is_unknown:
                rejection_reason = (
                    f"Required prerequisite "
                    f"'{first_failure.prerequisite_skill_name}' "
                    f"for '{first_failure.target_skill_name}' "
                    "has unknown mastery."
                )
            else:
                rejection_reason = (
                    f"Mastery of "
                    f"'{first_failure.prerequisite_skill_name}' "
                    f"is below the required threshold "
                    f"{first_failure.required_threshold} for "
                    f"'{first_failure.target_skill_name}'."
                )

            return EligibilityResult(
                content_id=content_id,
                is_eligible=False,
                rejection_code=rejection_code,
                rejection_reason=rejection_reason,
                failures=tuple(failures),
            )

        return EligibilityResult(
            content_id=content_id,
            is_eligible=True,
        )