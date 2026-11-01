"""Deterministic identifier factory for SkillPath AI.

Implements pure, zero-padded identifier formatting functions matching
SRS v1.2.0-FINAL-SPEC Sections 3, G, and H.3.
"""

import re
from typing import Any

# Compiled regular expressions for strict parent identifier validation
_LEARNER_ID_REGEX = re.compile(r"^LRN-\d{6}$")
_ATTEMPT_ID_REGEX = re.compile(r"^ATT-LRN-\d{6}-\d{6}$")
_PATH_ID_REGEX = re.compile(r"^PATH-2026-\d{6}$")
_RECOMMENDATION_ID_REGEX = re.compile(r"^REC-\d{4}-\d{6}$")


def _validate_positive_index(idx: Any, name: str) -> int:
    """Validate that an index is strictly an integer >= 1.

    Rejects booleans (despite bool being an int subclass in Python),
    floats, strings, and non-positive integers with ValueError.
    """
    if type(idx) is not int:
        raise ValueError(
            f"{name} must be an integer, got {type(idx).__name__} ({idx!r})"
        )
    if idx < 1:
        raise ValueError(f"{name} must be a positive integer >= 1, got {idx}")
    return idx


def _validate_parent_id(parent_id: Any, regex: re.Pattern, expected_format: str, name: str) -> str:
    """Validate that a parent identifier is a non-empty string matching the required pattern."""
    if type(parent_id) is not str:
        raise ValueError(
            f"{name} must be a string, got {type(parent_id).__name__} ({parent_id!r})"
        )
    if not regex.match(parent_id):
        raise ValueError(
            f"Invalid {name}: {parent_id!r}. Must match pattern {expected_format!r}."
        )
    return parent_id


def format_learner_id(idx: int) -> str:
    """Format a deterministic learner identifier (e.g., 'LRN-000001').

    Args:
        idx: 1-based positive learner sequence index.

    Returns:
        Formatted learner identifier string.

    Raises:
        ValueError: If idx is not an integer or is less than 1.
    """
    valid_idx = _validate_positive_index(idx, "Learner index")
    return f"LRN-{valid_idx:06d}"


def format_course_id(idx: int) -> str:
    """Format a deterministic course identifier (e.g., 'CRS-000001').

    Args:
        idx: 1-based positive course sequence index.

    Returns:
        Formatted course identifier string.

    Raises:
        ValueError: If idx is not an integer or is less than 1.
    """
    valid_idx = _validate_positive_index(idx, "Course index")
    return f"CRS-{valid_idx:06d}"


def format_skill_id(idx: int) -> str:
    """Format a deterministic skill identifier (e.g., 'SKL-000001').

    Args:
        idx: 1-based positive skill sequence index.

    Returns:
        Formatted skill identifier string.

    Raises:
        ValueError: If idx is not an integer or is less than 1.
    """
    valid_idx = _validate_positive_index(idx, "Skill index")
    return f"SKL-{valid_idx:06d}"


def format_content_id(idx: int) -> str:
    """Format a deterministic content item identifier (e.g., 'CNT-000001').

    Args:
        idx: 1-based positive content sequence index.

    Returns:
        Formatted content item identifier string.

    Raises:
        ValueError: If idx is not an integer or is less than 1.
    """
    valid_idx = _validate_positive_index(idx, "Content index")
    return f"CNT-{valid_idx:06d}"


def format_attempt_id(learner_id: str, learner_attempt_idx: int) -> str:
    """Format a deterministic attempt identifier (e.g., 'ATT-LRN-000001-000001').

    Args:
        learner_id: Valid parent learner identifier matching 'LRN-XXXXXX'.
        learner_attempt_idx: 1-based sequential attempt number for this learner.

    Returns:
        Formatted attempt identifier string.

    Raises:
        ValueError: If learner_id is malformed/wrong type or learner_attempt_idx is invalid.
    """
    valid_parent = _validate_parent_id(
        learner_id, _LEARNER_ID_REGEX, "LRN-XXXXXX", "learner_id"
    )
    valid_idx = _validate_positive_index(learner_attempt_idx, "Learner attempt index")
    return f"ATT-{valid_parent}-{valid_idx:06d}"


def format_assessment_result_id(attempt_id: str) -> str:
    """Format a deterministic assessment result identifier (e.g., 'RES-ATT-LRN-000001-000001').

    Args:
        attempt_id: Valid parent attempt identifier matching 'ATT-LRN-XXXXXX-YYYYYY'.

    Returns:
        Formatted assessment result identifier string.

    Raises:
        ValueError: If attempt_id is malformed or wrong type.
    """
    valid_parent = _validate_parent_id(
        attempt_id, _ATTEMPT_ID_REGEX, "ATT-LRN-XXXXXX-YYYYYY", "attempt_id"
    )
    return f"RES-{valid_parent}"


def format_learning_path_id(idx: int) -> str:
    """Format a deterministic learning path identifier (e.g., 'PATH-2026-000001').

    Args:
        idx: 1-based positive learning path sequence index.

    Returns:
        Formatted learning path identifier string.

    Raises:
        ValueError: If idx is not an integer or is less than 1.
    """
    valid_idx = _validate_positive_index(idx, "Learning path index")
    return f"PATH-2026-{valid_idx:06d}"


def format_learning_path_item_id(path_id: str, sequence_order: int) -> str:
    """Format a deterministic learning path item identifier (e.g., 'LPI-PATH-2026-000001-001').

    Length is exactly 26 characters, well within the VARCHAR(32) schema column limit.

    Args:
        path_id: Valid parent learning path identifier matching 'PATH-2026-XXXXXX'.
        sequence_order: 1-based integer sequence position strictly from 1 through 999.

    Returns:
        Formatted learning path item identifier string.

    Raises:
        ValueError: If path_id is malformed/wrong type or sequence_order is not in 1..999.
    """
    valid_parent = _validate_parent_id(
        path_id, _PATH_ID_REGEX, "PATH-2026-XXXXXX", "path_id"
    )
    if type(sequence_order) is not int:
        raise ValueError(
            f"Sequence order must be an integer, got {type(sequence_order).__name__} ({sequence_order!r})"
        )
    if not (1 <= sequence_order <= 999):
        raise ValueError(
            f"Sequence order must be an integer between 1 and 999, got {sequence_order}"
        )
    return f"LPI-{valid_parent}-{sequence_order:03d}"


def format_recommendation_id(idx: int, year: int = 2026) -> str:
    """Format a deterministic recommendation identifier (e.g., 'REC-2026-000001').

    Length is exactly 15 characters, well within the VARCHAR(32) schema column limit.

    Args:
        idx: 1-based positive recommendation sequence index.
        year: 4-digit positive integer year (>= 2026). Default is 2026.

    Returns:
        Formatted recommendation identifier string.

    Raises:
        ValueError: If idx or year is not an integer, idx < 1, or year < 2026.
    """
    valid_idx = _validate_positive_index(idx, "Recommendation index")
    if type(year) is not int:
        raise ValueError(
            f"Year must be an integer, got {type(year).__name__} ({year!r})"
        )
    if not (2026 <= year <= 9999):
        raise ValueError(f"Year must be between 2026 and 9999, got {year}")
    return f"REC-{year:04d}-{valid_idx:06d}"


def format_outcome_id(recommendation_id: str) -> str:
    """Format a deterministic recommendation outcome identifier (e.g., 'OUT-REC-2026-000001').

    Length is exactly 19 characters, well within the VARCHAR(32) schema column limit.

    Args:
        recommendation_id: Valid parent recommendation identifier matching 'REC-YYYY-XXXXXX'.

    Returns:
        Formatted outcome identifier string.

    Raises:
        ValueError: If recommendation_id is malformed or wrong type.
    """
    valid_parent = _validate_parent_id(
        recommendation_id, _RECOMMENDATION_ID_REGEX, "REC-YYYY-XXXXXX", "recommendation_id"
    )
    return f"OUT-{valid_parent}"
