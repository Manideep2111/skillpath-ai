"""Unit tests for deterministic ID factory formatting, boundaries, and validation."""

import pytest

from src.services.generator.id_factory import (
    format_learner_id,
    format_course_id,
    format_skill_id,
    format_content_id,
    format_attempt_id,
    format_assessment_result_id,
    format_learning_path_id,
    format_learning_path_item_id,
    format_recommendation_id,
    format_outcome_id,
)


def test_required_id_formats_with_representative_examples():
    """1. Verify all eight required ID formats match SRS Sections 3, G, and H.3."""
    assert format_learner_id(1) == "LRN-000001"
    assert format_course_id(1) == "CRS-000001"
    assert format_skill_id(1) == "SKL-000001"
    assert format_content_id(1) == "CNT-000001"
    assert format_attempt_id("LRN-000001", 1) == "ATT-LRN-000001-000001"
    assert (
        format_assessment_result_id("ATT-LRN-000001-000001")
        == "RES-ATT-LRN-000001-000001"
    )
    assert format_learning_path_id(1) == "PATH-2026-000001"
    assert (
        format_learning_path_item_id("PATH-2026-000001", 1)
        == "LPI-PATH-2026-000001-001"
    )


def test_zero_padding_across_magnitude_ranges():
    """2. Verify exact zero-padding for different positive integer magnitudes."""
    assert format_learner_id(42) == "LRN-000042"
    assert format_learner_id(999999) == "LRN-999999"

    assert format_course_id(10) == "CRS-000010"
    assert format_skill_id(50) == "SKL-000050"
    assert format_content_id(100) == "CNT-000100"

    assert format_attempt_id("LRN-000042", 2000) == "ATT-LRN-000042-002000"
    assert format_learning_path_id(80) == "PATH-2026-000080"
    assert (
        format_learning_path_item_id("PATH-2026-000080", 15)
        == "LPI-PATH-2026-000080-015"
    )


def test_rejection_of_zero_and_negative_indices():
    """3. Verify rejection of zero and negative integer indices."""
    invalid_indices = [0, -1, -50]

    for idx in invalid_indices:
        with pytest.raises(ValueError, match="positive integer >= 1"):
            format_learner_id(idx)

        with pytest.raises(ValueError, match="positive integer >= 1"):
            format_course_id(idx)

        with pytest.raises(ValueError, match="positive integer >= 1"):
            format_skill_id(idx)

        with pytest.raises(ValueError, match="positive integer >= 1"):
            format_content_id(idx)

        with pytest.raises(ValueError, match="positive integer >= 1"):
            format_attempt_id("LRN-000001", idx)

        with pytest.raises(ValueError, match="positive integer >= 1"):
            format_learning_path_id(idx)

        with pytest.raises(ValueError, match="between 1 and 999"):
            format_learning_path_item_id("PATH-2026-000001", idx)


def test_rejection_of_invalid_index_types():
    """4. Verify rejection of floats, strings, None, and booleans."""
    # Note: bool is a subclass of int in Python (isinstance(True, int) == True),
    # so explicitly verifying True/False rejection is critical.
    invalid_types = [1.0, 2.5, "1", "10", True, False, None, [1]]

    for val in invalid_types:
        with pytest.raises(ValueError, match="must be an integer"):
            format_learner_id(val)  # type: ignore

        with pytest.raises(ValueError, match="must be an integer"):
            format_course_id(val)  # type: ignore

        with pytest.raises(ValueError, match="must be an integer"):
            format_skill_id(val)  # type: ignore

        with pytest.raises(ValueError, match="must be an integer"):
            format_content_id(val)  # type: ignore

        with pytest.raises(ValueError, match="must be an integer"):
            format_attempt_id("LRN-000001", val)  # type: ignore

        with pytest.raises(ValueError, match="must be an integer"):
            format_learning_path_id(val)  # type: ignore

        with pytest.raises(ValueError, match="must be an integer"):
            format_learning_path_item_id("PATH-2026-000001", val)  # type: ignore


def test_composite_id_valid_and_invalid_parent_identifiers():
    """5. Verify composite IDs with valid and invalid parent identifiers."""
    # Valid parent propagation
    valid_learner = format_learner_id(1)
    valid_attempt = format_attempt_id(valid_learner, 1)
    valid_result = format_assessment_result_id(valid_attempt)
    assert valid_result == "RES-ATT-LRN-000001-000001"

    valid_path = format_learning_path_id(1)
    valid_path_item = format_learning_path_item_id(valid_path, 1)
    assert valid_path_item == "LPI-PATH-2026-000001-001"

    # Invalid parent: wrong type
    for non_str in [123, None, True, False, ["LRN-000001"]]:
        with pytest.raises(ValueError, match="must be a string"):
            format_attempt_id(non_str, 1)  # type: ignore

        with pytest.raises(ValueError, match="must be a string"):
            format_assessment_result_id(non_str)  # type: ignore

        with pytest.raises(ValueError, match="must be a string"):
            format_learning_path_item_id(non_str, 1)  # type: ignore

    # Invalid parent: malformed string patterns
    for bad_learner in ["", "LRN-1", "LRN-00001", "USER-000001", "LRN-0000001"]:
        with pytest.raises(ValueError, match="Invalid learner_id"):
            format_attempt_id(bad_learner, 1)

    for bad_attempt in ["", "ATT-000001", "ATT-LRN-000001", "RES-ATT-LRN-000001-000001"]:
        with pytest.raises(ValueError, match="Invalid attempt_id"):
            format_assessment_result_id(bad_attempt)

    for bad_path in ["", "PATH-000001", "PATH-2025-000001", "PATH-2026-1"]:
        with pytest.raises(ValueError, match="Invalid path_id"):
            format_learning_path_item_id(bad_path, 1)


def test_learning_path_item_sequence_boundaries():
    """6. Verify exact sequence boundaries 1 and 999, and rejection of 0 and 1000."""
    valid_path = "PATH-2026-000001"

    # Inclusive lower and upper boundaries must succeed
    assert (
        format_learning_path_item_id(valid_path, 1)
        == "LPI-PATH-2026-000001-001"
    )
    assert (
        format_learning_path_item_id(valid_path, 999)
        == "LPI-PATH-2026-000001-999"
    )

    # Values outside boundary 1..999 must raise ValueError
    with pytest.raises(ValueError, match="between 1 and 999"):
        format_learning_path_item_id(valid_path, 0)

    with pytest.raises(ValueError, match="between 1 and 999"):
        format_learning_path_item_id(valid_path, 1000)


def test_learning_path_item_id_length_bounded_by_schema():
    """Verify learning-path-item IDs stay within the VARCHAR(32) schema limit."""
    sample_id = format_learning_path_item_id("PATH-2026-000001", 1)
    max_boundary_id = format_learning_path_item_id("PATH-2026-999999", 999)

    # The generated IDs are exactly 24 characters.
    assert len(sample_id) == 24
    assert len(max_boundary_id) == 24

    # Both IDs must satisfy the schema's maximum length.
    assert len(sample_id) <= 32
    assert len(max_boundary_id) <= 32


def test_deterministic_results_across_repeated_calls():
    """8. Verify identical inputs produce identical outputs across repeated calls."""
    for _ in range(5):
        assert format_learner_id(50) == "LRN-000050"
        assert format_attempt_id("LRN-000050", 10) == "ATT-LRN-000050-000010"
        assert (
            format_assessment_result_id("ATT-LRN-000050-000010")
            == "RES-ATT-LRN-000050-000010"
        )
        assert format_learning_path_id(25) == "PATH-2026-000025"
        assert (
            format_learning_path_item_id("PATH-2026-000025", 5)
            == "LPI-PATH-2026-000025-005"
        )


def test_recommendation_and_outcome_id_formatting():
    """Verify recommendation and outcome ID generation, padding, and parent link."""
    assert format_recommendation_id(1) == "REC-2026-000001"
    assert format_recommendation_id(42) == "REC-2026-000042"
    assert format_recommendation_id(999999, year=2026) == "REC-2026-999999"
    assert format_recommendation_id(5, year=2027) == "REC-2027-000005"

    rec_id = format_recommendation_id(1)
    assert format_outcome_id(rec_id) == "OUT-REC-2026-000001"

    # Schema length bound checks (VARCHAR(32))
    assert len(format_recommendation_id(1)) == 15 <= 32
    assert len(format_outcome_id(rec_id)) == 19 <= 32


def test_recommendation_and_outcome_id_rejections():
    """Verify input validation for recommendation and outcome ID generation."""
    # Invalid index
    for bad_idx in [0, -1, -5, 1.5, "1", True, False, None]:
        with pytest.raises(ValueError):
            format_recommendation_id(bad_idx)

    # Invalid year
    for bad_year in [2025, 1999, 10000, "2026", True, None]:
        with pytest.raises(ValueError):
            format_recommendation_id(1, year=bad_year)

    # Invalid recommendation parent ID for outcome
    for bad_parent in [
        "",
        "REC-1",
        "REC-2026-1",
        "OUT-REC-2026-000001",
        123,
        None,
        True,
    ]:
        with pytest.raises(ValueError):
            format_outcome_id(bad_parent)
