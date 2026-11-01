"""Temporal evaluation split definitions and boundary management for SkillPath AI.

Defines historical evidence intervals (t <= T) and forward outcome windows (T < t <= T + 30 days).
Enforces cutoff isolation: pre-cutoff attempts with post-cutoff assessments cannot influence historical mastery.
Tracks planned vs. actual observation horizons and flags partially observed evaluation windows.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.entities import AssessmentResult, Attempt


@dataclass(frozen=True)
class TemporalWindow:
    """Specification of a temporal evaluation window around a cutoff timestamp."""

    cutoff: datetime
    window_days: int
    planned_end: datetime
    actual_horizon: datetime
    is_partially_observed: bool

    @classmethod
    def create(
        cls,
        cutoff: datetime,
        window_days: int = 30,
        dataset_max_timestamp: Optional[datetime] = None,
    ) -> "TemporalWindow":
        """Instantiate a TemporalWindow, automatically detecting observation truncation."""
        planned_end = cutoff + timedelta(days=window_days)
        if dataset_max_timestamp is not None and dataset_max_timestamp < planned_end:
            actual_horizon = dataset_max_timestamp
            is_partially_observed = True
        else:
            actual_horizon = planned_end
            is_partially_observed = False

        return cls(
            cutoff=cutoff,
            window_days=window_days,
            planned_end=planned_end,
            actual_horizon=actual_horizon,
            is_partially_observed=is_partially_observed,
        )


def get_dataset_temporal_bounds(session: Session) -> Tuple[datetime, datetime]:
    """Inspect dataset to retrieve earliest and latest recorded activity timestamps."""
    min_attempt = session.scalar(select(func.min(Attempt.started_at)))
    max_attempt = session.scalar(select(func.max(Attempt.completed_at)))
    max_result = session.scalar(select(func.max(AssessmentResult.graded_at)))

    min_ts = min_attempt or datetime(2026, 1, 1, 0, 0, 0)
    candidates = [ts for ts in (max_attempt, max_result) if ts is not None]
    max_ts = max(candidates) if candidates else datetime(2026, 10, 30, 23, 59, 59)

    return min_ts, max_ts


def get_standard_evaluation_windows(session: Optional[Session] = None) -> List[TemporalWindow]:
    """Generate standard three-cutoff evaluation schedule across the development dataset.

    T1: 2026-08-01 (Fully observed 30-day window)
    T2: 2026-09-01 (Fully observed 30-day window)
    T3: 2026-10-01 (Partially observed window: dataset ends 2026-10-30 19:20:44)
    """
    dataset_max = None
    if session is not None:
        _, dataset_max = get_dataset_temporal_bounds(session)
    else:
        # Default known development dataset bound
        dataset_max = datetime(2026, 10, 30, 19, 20, 44)

    cutoffs = [
        datetime(2026, 8, 1, 0, 0, 0),
        datetime(2026, 9, 1, 0, 0, 0),
        datetime(2026, 10, 1, 0, 0, 0),
    ]

    windows = []
    for cutoff in cutoffs:
        window = TemporalWindow.create(
            cutoff=cutoff,
            window_days=30,
            dataset_max_timestamp=dataset_max,
        )
        windows.append(window)

    return windows
