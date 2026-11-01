"""Deterministic synthetic data generator for SkillPath AI.

Implements dependency-ordered, reproducible data generation across configurable
profiles matching SRS v1.2.0-FINAL-SPEC Sections 3, 5, 6, 7, and H.
"""
from decimal import Decimal
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import random
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple
import numpy as np
import os
from pathlib import Path
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from src.models.entities import (
    Learner,
    Course,
    Skill,
    SkillPrerequisite,
    ContentItem,
    ContentSkill,
    Attempt,
    AssessmentResult,
    LearningPath,
    LearningPathItem,
    MasterySnapshot,
    Recommendation,
    RecommendationOutcome,
    AuditEvent,
    DataIssue,
)
from src.services.generator.id_factory import (
    format_learner_id,
    format_course_id,
    format_skill_id,
    format_content_id,
    format_attempt_id,
    format_assessment_result_id,
    format_learning_path_id,
    format_learning_path_item_id,
)

SKILL_DOMAINS = ["Data Science", "Web Development", "DevOps", "Cyber Security"]
EXPECTED_CONTENT_TYPES = {"VIDEO", "READING", "QUIZ", "LAB", "PROJECT"}
EXPERIENCE_LEVELS = ["BEGINNER", "INTERMEDIATE", "ADVANCED"]

# Timing constants derived from content taxonomy
MAX_ATTEMPT_DURATION_SECONDS = 7200  # 120 minutes maximum content duration
MAX_GRADING_DELAY_SECONDS = 60       # 60 seconds maximum grading turnaround
MIN_REQUIRED_WINDOW_SECONDS = MAX_ATTEMPT_DURATION_SECONDS + MAX_GRADING_DELAY_SECONDS  # 7260 seconds


@dataclass(frozen=True)
class GeneratorConfig:
    """Configuration parameters for synthetic data generation profiles."""

    profile_name: str
    seed: int
    num_learners: int
    num_courses: int
    num_skills: int
    num_content_items: int
    num_attempts: int
    num_learning_paths: int
    num_cold_start_learners: int
    start_date: datetime = datetime(2026, 1, 1, 0, 0, 0)
    end_date: datetime = datetime(2026, 10, 30, 23, 59, 59)
    content_type_proportions: Mapping[str, float] = field(
        default_factory=lambda: {
            "VIDEO": 0.35,
            "READING": 0.25,
            "QUIZ": 0.20,
            "LAB": 0.15,
            "PROJECT": 0.05,
        }
    )

    def __post_init__(self) -> None:
        """Validate configuration parameters strictly to reject invalid counts, types, and windows."""
        if type(self.profile_name) is not str or not self.profile_name.strip():
            raise ValueError(f"profile_name must be a non-empty string, got {self.profile_name!r}")

        # Strict integer validation: reject bool (subclass of int in Python), float, str, None
        int_fields = [
            ("seed", self.seed),
            ("num_learners", self.num_learners),
            ("num_courses", self.num_courses),
            ("num_skills", self.num_skills),
            ("num_content_items", self.num_content_items),
            ("num_attempts", self.num_attempts),
            ("num_learning_paths", self.num_learning_paths),
            ("num_cold_start_learners", self.num_cold_start_learners),
        ]
        for name, val in int_fields:
            if type(val) is not int or type(val) is bool:
                raise ValueError(
                    f"GeneratorConfig parameter '{name}' must be an int, got {type(val).__name__} ({val!r})"
                )

        if self.seed < 0:
            raise ValueError(f"seed must be a non-negative integer, got {self.seed}")

        if not isinstance(self.start_date, datetime) or not isinstance(self.end_date, datetime):
            raise ValueError("start_date and end_date must be datetime instances")

        # Timezone compatibility validation
        if (self.start_date.tzinfo is None) != (self.end_date.tzinfo is None):
            raise ValueError("start_date and end_date must either both be timezone-aware or both be timezone-naive")

        if self.end_date <= self.start_date:
            raise ValueError(
                f"end_date ({self.end_date.isoformat()}) must be strictly after start_date ({self.start_date.isoformat()})"
            )

        total_seconds = int((self.end_date - self.start_date).total_seconds())
        if total_seconds < MIN_REQUIRED_WINDOW_SECONDS:
            raise ValueError(
                f"Configured date range ({total_seconds}s) must span at least {MIN_REQUIRED_WINDOW_SECONDS}s "
                f"({MIN_REQUIRED_WINDOW_SECONDS // 60}m {MIN_REQUIRED_WINDOW_SECONDS % 60}s) "
                "to guarantee attempt durations and grading fit within [start_date, end_date]."
            )

        if self.num_learners < 3:
            raise ValueError(f"num_learners must be >= 3 to satisfy experience tiers, got {self.num_learners}")
        if self.num_courses < 1:
            raise ValueError(f"num_courses must be >= 1, got {self.num_courses}")
        if self.num_skills < 4:
            raise ValueError(f"num_skills must be >= 4 to cover all 4 domains, got {self.num_skills}")
        if self.num_content_items < 5:
            raise ValueError(f"num_content_items must be >= 5 to cover all content types, got {self.num_content_items}")
        if self.num_content_items < self.num_courses:
            raise ValueError(
                f"num_content_items ({self.num_content_items}) cannot be less than num_courses ({self.num_courses})"
            )
        if self.num_cold_start_learners < 0:
            raise ValueError(f"num_cold_start_learners cannot be negative, got {self.num_cold_start_learners}")
        if self.num_cold_start_learners >= self.num_learners:
            raise ValueError(
                f"num_cold_start_learners ({self.num_cold_start_learners}) must be strictly less than num_learners ({self.num_learners})"
            )

        active_learners = self.num_learners - self.num_cold_start_learners
        if self.num_attempts < active_learners:
            raise ValueError(
                f"num_attempts ({self.num_attempts}) must be >= active learners ({active_learners}) "
                "because each non-cold learner must have at least 1 attempt."
            )
        if self.num_learning_paths < 0:
            raise ValueError(f"num_learning_paths cannot be negative, got {self.num_learning_paths}")
        if self.num_learning_paths > self.num_learners:
            raise ValueError(
                f"num_learning_paths ({self.num_learning_paths}) cannot exceed num_learners ({self.num_learners})"
            )

        # Strict content-type proportions validation
        if not isinstance(self.content_type_proportions, (dict, Mapping)):
            raise ValueError("content_type_proportions must be a dictionary or mapping")
        prop_keys = set(self.content_type_proportions.keys())
        missing_keys = EXPECTED_CONTENT_TYPES - prop_keys
        extra_keys = prop_keys - EXPECTED_CONTENT_TYPES
        if missing_keys:
            raise ValueError(f"Missing required content types in proportions: {sorted(missing_keys)}")
        if extra_keys:
            raise ValueError(f"Unexpected extra content types in proportions: {sorted(extra_keys)}")

        for ct, p in self.content_type_proportions.items():
            if type(p) not in (float, int) or type(p) is bool or not math.isfinite(p) or p < 0:
                raise ValueError(f"Proportion for '{ct}' must be a non-negative finite number, got {p!r}")
        prop_sum = sum(self.content_type_proportions.values())
        if abs(prop_sum - 1.0) > 1e-4:
            raise ValueError(f"content_type_proportions must sum to 1.0 (within 1e-4), got {prop_sum:.6f}")

        # Enforce defensive immutability via MappingProxyType
        object.__setattr__(
            self,
            "content_type_proportions",
            MappingProxyType(dict(self.content_type_proportions))
        )


DEVELOPMENT_CONFIG = GeneratorConfig(
    profile_name="development",
    seed=20261022,
    num_learners=100,
    num_courses=10,
    num_skills=50,
    num_content_items=100,
    num_attempts=2000,
    num_learning_paths=80,
    num_cold_start_learners=10,
)

FULL_CONFIG = GeneratorConfig(
    profile_name="full",
    seed=20261022,
    num_learners=10000,
    num_courses=200,  # Configurable default: 200 courses across 2,000 content items
    num_skills=500,
    num_content_items=2000,
    num_attempts=500000,
    num_learning_paths=8000,
    num_cold_start_learners=1000,
)

INTEGRATION_CONFIG = GeneratorConfig(
    profile_name="integration",
    seed=20261022,
    num_learners=500,
    num_courses=50,
    num_skills=200,
    num_content_items=500,
    num_attempts=20000,
    num_learning_paths=400,
    num_cold_start_learners=50,
)

PROFILES: Dict[str, GeneratorConfig] = {
    "development": DEVELOPMENT_CONFIG,
    "integration": INTEGRATION_CONFIG,
    "full": FULL_CONFIG,
}



class SyntheticDataGenerator:
    """Generates reproducible, relationally intact baseline synthetic data."""

    def __init__(
        self,
        session: Session,
        config: GeneratorConfig = DEVELOPMENT_CONFIG,
        batch_size: int = 5000,
    ) -> None:
        self.session = session
        self.config = config
        self.batch_size = max(1, batch_size)
        self.py_rng = random.Random(config.seed)
        self.np_rng = np.random.default_rng(config.seed)

        # Explicitly designate cold-start learner IDs (the last N learners in deterministic sequence)
        cold_start_start_idx = self.config.num_learners - self.config.num_cold_start_learners + 1
        self._cold_start_learner_ids: Set[str] = {
            format_learner_id(i) for i in range(cold_start_start_idx, self.config.num_learners + 1)
        }

    def get_cold_start_learner_ids(self) -> Set[str]:
        """Return the explicit, deterministic set of cold-start learner IDs."""
        return set(self._cold_start_learner_ids)

    def is_cold_start_learner(self, learner_id: str) -> bool:
        """Check if a learner identifier is designated as cold-start."""
        return learner_id in self._cold_start_learner_ids

    def _verify_target_safety(self) -> None:
        """Prevent writing synthetic data to the protected baseline database."""
        try:
            bind = self.session.get_bind()
            if bind and bind.url:
                url_str = str(bind.url).lower()
                if "skillpath.db" in url_str and "sandbox" not in url_str and "test" not in url_str:
                    baseline_path = Path("D:/SkillPathAI/skillpath.db").resolve()
                    if hasattr(bind.url, "database") and bind.url.database:
                        target = Path(bind.url.database).resolve()
                        if os.path.normcase(str(target)) == os.path.normcase(str(baseline_path)):
                            raise RuntimeError(
                                "CRITICAL SAFETY VIOLATION: Refusing to generate synthetic data into "
                                f"protected baseline database '{baseline_path}'. Specify an isolated output database."
                            )
        except RuntimeError:
            raise
        except Exception:
            pass

    def _verify_database_empty(self) -> None:
        """Ensure all 15 operational and supporting tables contain zero records."""
        tables_to_check = [
            Learner, Course, Skill, SkillPrerequisite, ContentItem, ContentSkill,
            Attempt, AssessmentResult, LearningPath, LearningPathItem,
            MasterySnapshot, Recommendation, RecommendationOutcome, AuditEvent, DataIssue
        ]
        for entity in tables_to_check:
            count = self.session.scalar(select(func.count()).select_from(entity))
            if count and count > 0:
                raise RuntimeError(
                    f"Target database is not empty. Table '{entity.__tablename__}' "
                    f"already contains {count} records. Refusing to overwrite or duplicate data."
                )

    @staticmethod
    def calculate_attempt_timing(
        start_date: datetime,
        offset_fraction: float,
        usable_span_seconds: int,
        duration_seconds: int,
        grading_delay_seconds: int,
    ) -> Tuple[datetime, datetime, datetime]:
        """Calculate started_at, completed_at, and graded_at timestamps deterministically.

        Mathematical guarantee:
        Given offset_fraction in [0.0, 1.0] and usable_span_seconds = total_seconds - MIN_REQUIRED_WINDOW_SECONDS,
        then offset_seconds <= total_seconds - 7260.
        completed_at = started_at + duration <= started_at + 7200 <= end_date - 60.
        graded_at = completed_at + delay <= completed_at + 60 <= end_date.
        No min() or truncation is used.
        """
        if not isinstance(start_date, datetime):
            raise ValueError(f"start_date must be a datetime instance, got {type(start_date).__name__}")

        # Strict type and boundary validation on inputs
        if type(offset_fraction) not in (float, int) or type(offset_fraction) is bool:
            raise ValueError(f"offset_fraction must be a finite float or int, got {type(offset_fraction).__name__}")
        if not math.isfinite(offset_fraction):
            raise ValueError(f"offset_fraction must be finite, got {offset_fraction!r}")
        if not (0.0 <= float(offset_fraction) <= 1.0):
            raise ValueError(f"offset_fraction must be in range [0.0, 1.0], got {offset_fraction}")

        if type(usable_span_seconds) is not int or type(usable_span_seconds) is bool:
            raise ValueError(f"usable_span_seconds must be an int, got {type(usable_span_seconds).__name__}")
        if usable_span_seconds < 0:
            raise ValueError(f"usable_span_seconds must be non-negative, got {usable_span_seconds}")

        if type(duration_seconds) is not int or type(duration_seconds) is bool:
            raise ValueError(f"duration_seconds must be an int, got {type(duration_seconds).__name__}")
        if not (1 <= duration_seconds <= MAX_ATTEMPT_DURATION_SECONDS):
            raise ValueError(
                f"duration_seconds must be in range [1, {MAX_ATTEMPT_DURATION_SECONDS}], got {duration_seconds}"
            )

        if type(grading_delay_seconds) is not int or type(grading_delay_seconds) is bool:
            raise ValueError(f"grading_delay_seconds must be an int, got {type(grading_delay_seconds).__name__}")
        if not (0 <= grading_delay_seconds <= MAX_GRADING_DELAY_SECONDS):
            raise ValueError(
                f"grading_delay_seconds must be in range [0, {MAX_GRADING_DELAY_SECONDS}], got {grading_delay_seconds}"
            )

        offset_seconds = int(offset_fraction * usable_span_seconds)
        started_at = start_date + timedelta(seconds=offset_seconds)
        completed_at = started_at + timedelta(seconds=duration_seconds)
        graded_at = completed_at + timedelta(seconds=grading_delay_seconds)
        return started_at, completed_at, graded_at

    @staticmethod
    def _allocate_proportions(total: int, proportions: Mapping[str, float]) -> Dict[str, int]:
        """Allocate integer counts using the Largest Remainder (Hamilton-Hare) method."""
        quotas = {k: total * p for k, p in proportions.items()}
        counts = {k: int(q) for k, q in quotas.items()}
        remainders = {k: quotas[k] - counts[k] for k in quotas}
        remainder_seats = total - sum(counts.values())
        sorted_keys = sorted(remainders.keys(), key=lambda k: remainders[k], reverse=True)
        for k in sorted_keys[:remainder_seats]:
            counts[k] += 1
        return counts

    def generate(self) -> Dict[str, int]:
        """Execute the transactional generation pipeline."""
        self._verify_target_safety()
        self._verify_database_empty()

        # Reject timezone-aware configurations for SQLite storage because standard DateTime columns
        # drop timezone offsets on persistence, leading to ambiguous round-trip comparisons.
        if self.config.start_date.tzinfo is not None:
            raise ValueError(
                "Timezone-aware datetime configurations are not supported for SQLite persistence "
                "because the current ORM schema uses naive DateTime columns that drop tzinfo on storage. "
                "Use timezone-naive UTC datetimes."
            )

        summary: Dict[str, int] = {}
        try:
            # Stage 1: Core Curriculum and Population Roots
            skills = self._generate_skills()
            summary["skills"] = len(skills)

            prereqs = self._generate_skill_prerequisites(skills)
            summary["skill_prerequisites"] = len(prereqs)

            courses = self._generate_courses()
            summary["courses"] = len(courses)

            content_items = self._generate_content_items(courses)
            summary["content_items"] = len(content_items)

            content_skills = self._generate_content_skills(content_items, skills)
            summary["content_skills"] = len(content_skills)

            learners = self._generate_learners()
            summary["learners"] = len(learners)

            paths, path_items = self._generate_learning_paths(learners, content_items)
            summary["learning_paths"] = len(paths)
            summary["learning_path_items"] = len(path_items)

            att_count, res_count = self._generate_attempts_and_assessments(learners, content_items)
            summary["attempts"] = att_count
            summary["assessment_results"] = res_count

            # Stage 2: Commit all records atomically
            self.session.commit()
            return summary

        except Exception:
            self.session.rollback()
            raise

    def _generate_skills(self) -> List[Skill]:
        """Generate skills distributed across the four domains using largest-remainder allocation."""
        skills: List[Skill] = []
        domain_proportions = {
            "Data Science": 0.30,
            "Web Development": 0.30,
            "DevOps": 0.20,
            "Cyber Security": 0.20,
        }
        counts = self._allocate_proportions(self.config.num_skills, domain_proportions)

        skill_idx = 1
        for domain in SKILL_DOMAINS:
            domain_count = counts[domain]
            for i in range(1, domain_count + 1):
                s_id = format_skill_id(skill_idx)
                difficulty = round(float(self.np_rng.uniform(0.10, 0.95)), 2)
                skill = Skill(
                    skill_id=s_id,
                    name=f"{domain} Competency {i:03d}",
                    domain=domain,
                    difficulty_level=difficulty,
                    description=f"Curriculum skill addressing core concepts in {domain}.",
                    is_active=True,
                    created_at=self.config.start_date,
                    updated_at=self.config.start_date,
                )
                skills.append(skill)
                self.session.add(skill)
                skill_idx += 1

        self.session.flush()
        return skills

    def _generate_skill_prerequisites(self, skills: List[Skill]) -> List[SkillPrerequisite]:
        """Generate prerequisite edges forming an acyclic DAG with maximum depth guaranteed <= 4."""
        prereqs: List[SkillPrerequisite] = []
        domain_skills: Dict[str, List[Skill]] = defaultdict(list)
        for s in skills:
            domain_skills[s.domain].append(s)

        # Partition each domain's skills into up to 4 distinct tiers. Edges strictly go from tier A to tier B where A < B.
        for domain, d_skills in domain_skills.items():
            n = len(d_skills)
            if n < 2:
                continue

            k = min(4, n)
            chunk_size = n // k
            tiers: List[List[Skill]] = []
            for t_idx in range(k):
                start = t_idx * chunk_size
                end = (t_idx + 1) * chunk_size if t_idx < k - 1 else n
                tiers.append(d_skills[start:end])

            for t_idx in range(1, len(tiers)):
                child_tier = tiers[t_idx]
                parent_pool = [s for sub in tiers[:t_idx] for s in sub]
                for child in child_tier:
                    if parent_pool and self.py_rng.random() < 0.70:
                        chosen = self.py_rng.choice(parent_pool)
                        prereq = SkillPrerequisite(
                            skill_id=child.skill_id,
                            prerequisite_skill_id=chosen.skill_id,
                            minimum_mastery=0.70,
                            is_required=True,
                            created_at=self.config.start_date,
                        )
                        prereqs.append(prereq)
                        self.session.add(prereq)

        self.session.flush()
        return prereqs

    def _generate_courses(self) -> List[Course]:
        """Generate courses with distinct codes and difficulty levels."""
        courses: List[Course] = []
        for i in range(1, self.config.num_courses + 1):
            c_id = format_course_id(i)
            diff = self.py_rng.choice(EXPERIENCE_LEVELS)
            course = Course(
                course_id=c_id,
                title=f"Curriculum Track Module {i:03d}",
                code=f"COURSE-{i:04d}",
                description=f"Structured syllabus for track module {i:03d}.",
                difficulty=diff,
                is_active=True,
                created_at=self.config.start_date,
                updated_at=self.config.start_date,
            )
            courses.append(course)
            self.session.add(course)

        self.session.flush()
        return courses

    def _generate_content_items(self, courses: List[Course]) -> List[ContentItem]:
        """Generate content items matching the configured distribution via largest-remainder allocation."""
        content_items: List[ContentItem] = []
        type_counts = self._allocate_proportions(
            self.config.num_content_items, self.config.content_type_proportions
        )

        content_types_pool: List[str] = []
        for c_type in sorted(self.config.content_type_proportions.keys()):
            content_types_pool.extend([c_type] * type_counts[c_type])
        self.py_rng.shuffle(content_types_pool)

        durations = {
            "VIDEO": (10, 45),
            "READING": (10, 30),
            "QUIZ": (15, 30),
            "LAB": (30, 90),
            "PROJECT": (60, 120),
        }

        for i in range(1, self.config.num_content_items + 1):
            c_id = format_content_id(i)
            course = courses[(i - 1) % len(courses)]
            c_type = content_types_pool[i - 1]
            min_dur, max_dur = durations.get(c_type, (15, 45))
            duration = self.py_rng.randint(min_dur, max_dur)
            difficulty = round(float(self.np_rng.uniform(0.10, 0.95)), 2)

            item = ContentItem(
                content_id=c_id,
                course_id=course.course_id,
                title=f"{c_type.title()} Unit {i:04d}",
                content_type=c_type,
                difficulty=difficulty,
                duration_minutes=duration,
                is_active=True,
                created_at=self.config.start_date,
                updated_at=self.config.start_date,
            )
            content_items.append(item)
            self.session.add(item)

        self.session.flush()
        return content_items

    def _generate_content_skills(
        self, content_items: List[ContentItem], skills: List[Skill]
    ) -> List[ContentSkill]:
        """Map 1 to 3 skills to each content item."""
        mappings: List[ContentSkill] = []
        for item in content_items:
            num_skills = min(len(skills), self.py_rng.choice([1, 2, 3]))
            assigned_skills = self.py_rng.sample(skills, num_skills)

            weights = [1.00] if num_skills == 1 else ([1.00, 0.75] if num_skills == 2 else [1.00, 0.75, 0.50])
            for skill, weight in zip(assigned_skills, weights):
                cs = ContentSkill(
                    content_id=item.content_id,
                    skill_id=skill.skill_id,
                    relevance_weight=weight,
                )
                mappings.append(cs)
                self.session.add(cs)

        self.session.flush()
        return mappings

    def _generate_learners(self) -> List[Learner]:
        """Generate learners with designated cold-start segment."""
        learners: List[Learner] = []
        exp_counts = self._allocate_proportions(
            self.config.num_learners,
            {"BEGINNER": 0.40, "INTERMEDIATE": 0.40, "ADVANCED": 0.20}
        )

        levels_pool: List[str] = (
            ["BEGINNER"] * exp_counts["BEGINNER"] +
            ["INTERMEDIATE"] * exp_counts["INTERMEDIATE"] +
            ["ADVANCED"] * exp_counts["ADVANCED"]
        )

        for i in range(1, self.config.num_learners + 1):
            l_id = format_learner_id(i)
            exp = levels_pool[i - 1]

            learner = Learner(
                learner_id=l_id,
                first_name=f"Learner{i:04d}",
                last_name=f"User{i:04d}",
                email=f"learner.{i:06d}@skillpath.local",
                experience_level=exp,
                is_active=True,
                created_at=self.config.start_date,
                updated_at=self.config.start_date,
            )
            learners.append(learner)
            self.session.add(learner)

        self.session.flush()
        return learners

    def _generate_learning_paths(
        self, learners: List[Learner], content_items: List[ContentItem]
    ) -> Tuple[List[LearningPath], List[LearningPathItem]]:
        """Generate learning paths and sequential items with consistent lifecycle state."""
        paths: List[LearningPath] = []
        path_items: List[LearningPathItem] = []

        active_learners = [l for l in learners if not self.is_cold_start_learner(l.learner_id)]
        cold_learners = [l for l in learners if self.is_cold_start_learner(l.learner_id)]

        # Guarantee proportional representation of cold-start learners deterministically
        num_cold_paths = 0
        if cold_learners and self.config.num_learning_paths > 0:
            prop = len(cold_learners) / len(learners)
            num_cold_paths = min(len(cold_learners), max(1, int(round(self.config.num_learning_paths * prop))))

        num_active_paths = min(len(active_learners), self.config.num_learning_paths - num_cold_paths)

        chosen_cold = self.py_rng.sample(cold_learners, num_cold_paths) if num_cold_paths else []
        chosen_active = self.py_rng.sample(active_learners, num_active_paths) if num_active_paths else []
        selected_learners = chosen_active + chosen_cold
        self.py_rng.shuffle(selected_learners)

        max_allowed_items = min(12, len(content_items))
        total_span = (self.config.end_date - self.config.start_date).total_seconds()

        for path_idx, learner in enumerate(selected_learners, start=1):
            p_id = format_learning_path_id(path_idx)
            is_cold = self.is_cold_start_learner(learner.learner_id)

            path = LearningPath(
                path_id=p_id,
                learner_id=learner.learner_id,
                title=f"Adaptive Career Pathway {path_idx:03d}",
                target_role=self.py_rng.choice(
                    ["Data Engineer", "Backend Developer", "DevOps Engineer", "Security Analyst"]
                ),
                status="ACTIVE",
                created_at=self.config.start_date,
                updated_at=self.config.start_date,
            )
            paths.append(path)
            self.session.add(path)

            num_items = self.py_rng.randint(min(5, max_allowed_items), max_allowed_items)
            chosen_content = self.py_rng.sample(content_items, num_items)

            # Cold-start learners strictly have 0 completed items in clean baseline
            completed_up_to = 0 if is_cold else self.py_rng.choice([0, 1, 2, 3])
            completed_up_to = min(completed_up_to, num_items)

            # Generate strictly ascending completion timestamps inside the window without clamping
            if completed_up_to > 0:
                step = (total_span * 0.5) / (completed_up_to + 1)
                comp_times = [
                    self.config.start_date + timedelta(seconds=int((i + 1) * step))
                    for i in range(completed_up_to)
                ]
            else:
                comp_times = []

            for seq, item in enumerate(chosen_content, start=1):
                if seq <= completed_up_to:
                    status = "COMPLETED"
                    completed_at = comp_times[seq - 1]
                elif seq == completed_up_to + 1:
                    status = "IN_PROGRESS"
                    completed_at = None
                else:
                    status = "PENDING"
                    completed_at = None

                lpi = LearningPathItem(
                    path_item_id=format_learning_path_item_id(p_id, seq),
                    path_id=p_id,
                    content_id=item.content_id,
                    sequence_order=seq,
                    is_mandatory=True,
                    status=status,
                    completed_at=completed_at,
                )
                path_items.append(lpi)
                self.session.add(lpi)

        self.session.flush()
        return paths, path_items

    def _generate_attempts_and_assessments(
        self, learners: List[Learner], content_items: List[ContentItem]
    ) -> Tuple[int, int]:
        """Generate attempts across active learners and eligible assessment results within date bounds.

        Memory-safe batching strategy:
        Uses bounded batches of raw dictionaries inserted via direct bulk insert
        (`session.execute(insert(...), batch)`), preventing accumulation of hundreds of
        thousands of ORM instances in SQLAlchemy's identity map. Preserves transactional
        integrity (atomic commit on success, rollback on failure) and foreign key
        enforcement while bounding memory consumption to O(batch_size).
        """
        active_learner_records: List[Tuple[str, str]] = [
            (l.learner_id, l.experience_level)
            for l in learners
            if not self.is_cold_start_learner(l.learner_id)
        ]
        content_item_records: List[Tuple[str, str, int, float]] = [
            (c.content_id, c.content_type, c.duration_minutes, float(c.difficulty))
            for c in content_items
        ]

        num_active = len(active_learner_records)
        counts_per_learner = [1] * num_active
        remaining = self.config.num_attempts - num_active

        weights = self.np_rng.dirichlet(np.ones(num_active))
        distributed = self.np_rng.multinomial(remaining, weights)
        for idx in range(num_active):
            counts_per_learner[idx] += int(distributed[idx])

        attempt_counters: Dict[Tuple[str, str], int] = {}
        total_seconds = int((self.config.end_date - self.config.start_date).total_seconds())

        usable_span = total_seconds - MIN_REQUIRED_WINDOW_SECONDS

        attempt_count = 0
        assessment_count = 0

        attempt_batch: List[Dict[str, Any]] = []
        assessment_batch: List[Dict[str, Any]] = []

        for (l_id, exp_level), num_att in zip(active_learner_records, counts_per_learner):
            fractions = sorted(self.py_rng.random() for _ in range(num_att))

            for seq_idx, fraction in enumerate(fractions, start=1):
                c_id, c_type, dur_mins, diff = self.py_rng.choice(content_item_records)
                pair_key = (l_id, c_id)
                attempt_counters[pair_key] = attempt_counters.get(pair_key, 0) + 1
                attempt_num = attempt_counters[pair_key]

                status_roll = self.py_rng.random()
                if status_roll < 0.85:
                    status = "COMPLETED"
                    raw_duration = dur_mins * 60 + self.py_rng.randint(-60, 180)
                    duration = max(60, min(MAX_ATTEMPT_DURATION_SECONDS, raw_duration))
                    grading_delay = self.py_rng.randint(2, MAX_GRADING_DELAY_SECONDS)
                    started_at, completed_at, graded_at = self.calculate_attempt_timing(
                        self.config.start_date, fraction, usable_span, duration, grading_delay
                    )
                    time_spent_seconds: Optional[int] = duration
                elif status_roll < 0.95:
                    status = "ABANDONED"
                    offset_seconds = int(fraction * usable_span)
                    started_at = self.config.start_date + timedelta(seconds=offset_seconds)
                    duration = self.py_rng.randint(30, 300)
                    time_spent_seconds = duration
                    completed_at = None
                    graded_at = None
                else:
                    status = "IN_PROGRESS"
                    offset_seconds = int(fraction * usable_span)
                    started_at = self.config.start_date + timedelta(seconds=offset_seconds)
                    time_spent_seconds = None
                    completed_at = None
                    graded_at = None

                att_id = format_attempt_id(l_id, seq_idx)
                attempt_batch.append({
                    "attempt_id": att_id,
                    "learner_id": l_id,
                    "content_id": c_id,
                    "attempt_number": attempt_num,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "time_spent_seconds": time_spent_seconds,
                    "status": status,
                })
                attempt_count += 1

                # Generate assessment result strictly for completed attempts of assessment types
                if status == "COMPLETED" and c_type in ("QUIZ", "LAB", "PROJECT"):
                    res_id = format_assessment_result_id(att_id)
                    max_score = 100.00

                    exp_bonus = {"BEGINNER": 0.0, "INTERMEDIATE": 8.0, "ADVANCED": 15.0}[exp_level]
                    mean_score = 75.0 + exp_bonus - (diff * 25.0)
                    raw = float(self.np_rng.normal(mean_score, 12.0))
                    raw_score = round(max(0.0, min(100.0, raw)), 2)
                    norm_score = round(raw_score / 100.0, 4)

                    assessment_batch.append({
                        "result_id": res_id,
                        "attempt_id": att_id,
                        "raw_score": raw_score,
                        "max_score": max_score,
                        "normalized_score": norm_score,
                        "is_passed": (norm_score >= 0.70),
                        "graded_at": graded_at,
                    })
                    assessment_count += 1

                # Flush bounded batches to SQLite via direct bulk insert
                if len(attempt_batch) >= self.batch_size:
                    self.session.execute(insert(Attempt), attempt_batch)
                    attempt_batch.clear()
                    if assessment_batch:
                        self.session.execute(insert(AssessmentResult), assessment_batch)
                        assessment_batch.clear()

        # Flush remaining trailing records
        if attempt_batch:
            self.session.execute(insert(Attempt), attempt_batch)
            attempt_batch.clear()
        if assessment_batch:
            self.session.execute(insert(AssessmentResult), assessment_batch)
            assessment_batch.clear()

        self.session.flush()
        return attempt_count, assessment_count

    def compute_dataset_signature(self) -> str:
        """Compute SHA-256 digest over canonicalized field values across all 10 baseline tables.

        The signature covers all generated baseline tables:
        (Learner, Course, Skill, SkillPrerequisite, ContentItem, ContentSkill,
         Attempt, AssessmentResult, LearningPath, LearningPathItem).
        The five supporting operational tables (MasterySnapshot, Recommendation,
        RecommendationOutcome, AuditEvent, DataIssue) are clean baseline exclusions.
        Uses streaming execution (yield_per) to avoid loading entire tables into Python lists.
        """
        hasher = hashlib.sha256()

        def _canon(val: Any) -> Any:
            if val is None:
                return None
            if isinstance(val, datetime):
                return val.isoformat()
            if isinstance(val, (float, np.floating, Decimal)):
                return f"{float(val):.4f}"
            if isinstance(val, bool):
                return bool(val)
            if isinstance(val, int):
                return int(val)
            return str(val).strip() 

        # 1. Skills
        for row in self.session.scalars(select(Skill).order_by(Skill.skill_id).execution_options(yield_per=1000)):
            line = json.dumps([
                "SKILL", row.skill_id, row.name, row.domain, _canon(row.difficulty_level),
                row.description, _canon(row.is_active), _canon(row.created_at), _canon(row.updated_at)
            ], separators=(",", ":"), ensure_ascii=True) + "\n"
            hasher.update(line.encode("utf-8"))

        # 2. SkillPrerequisites
        for row in self.session.scalars(
            select(SkillPrerequisite).order_by(SkillPrerequisite.skill_id, SkillPrerequisite.prerequisite_skill_id).execution_options(yield_per=1000)
        ):
            line = json.dumps([
                "PREREQ", row.skill_id, row.prerequisite_skill_id, _canon(row.minimum_mastery),
                _canon(row.is_required), _canon(row.created_at)
            ], separators=(",", ":"), ensure_ascii=True) + "\n"
            hasher.update(line.encode("utf-8"))

        # 3. Courses
        for row in self.session.scalars(select(Course).order_by(Course.course_id).execution_options(yield_per=1000)):
            line = json.dumps([
                "COURSE", row.course_id, row.title, row.code, row.description,
                row.difficulty, _canon(row.is_active), _canon(row.created_at), _canon(row.updated_at)
            ], separators=(",", ":"), ensure_ascii=True) + "\n"
            hasher.update(line.encode("utf-8"))

        # 4. ContentItems
        for row in self.session.scalars(select(ContentItem).order_by(ContentItem.content_id).execution_options(yield_per=1000)):
            line = json.dumps([
                "CONTENT", row.content_id, row.course_id, row.title, row.content_type,
                _canon(row.difficulty), row.duration_minutes, _canon(row.is_active),
                _canon(row.created_at), _canon(row.updated_at)
            ], separators=(",", ":"), ensure_ascii=True) + "\n"
            hasher.update(line.encode("utf-8"))

        # 5. ContentSkills
        for row in self.session.scalars(
            select(ContentSkill).order_by(ContentSkill.content_id, ContentSkill.skill_id).execution_options(yield_per=1000)
        ):
            line = json.dumps([
                "CS", row.content_id, row.skill_id, _canon(row.relevance_weight)
            ], separators=(",", ":"), ensure_ascii=True) + "\n"
            hasher.update(line.encode("utf-8"))

        # 6. Learners
        for row in self.session.scalars(select(Learner).order_by(Learner.learner_id).execution_options(yield_per=1000)):
            line = json.dumps([
                "LEARNER", row.learner_id, row.first_name, row.last_name, row.email,
                row.experience_level, _canon(row.is_active), _canon(row.created_at), _canon(row.updated_at)
            ], separators=(",", ":"), ensure_ascii=True) + "\n"
            hasher.update(line.encode("utf-8"))

        # 7. LearningPaths
        for row in self.session.scalars(select(LearningPath).order_by(LearningPath.path_id).execution_options(yield_per=1000)):
            line = json.dumps([
                "PATH", row.path_id, row.learner_id, row.title, row.target_role,
                row.status, _canon(row.created_at), _canon(row.updated_at)
            ], separators=(",", ":"), ensure_ascii=True) + "\n"
            hasher.update(line.encode("utf-8"))

        # 8. LearningPathItems
        for row in self.session.scalars(
            select(LearningPathItem).order_by(LearningPathItem.path_item_id).execution_options(yield_per=1000)
        ):
            line = json.dumps([
                "LPI", row.path_item_id, row.path_id, row.content_id, row.sequence_order,
                _canon(row.is_mandatory), row.status, _canon(row.completed_at)
            ], separators=(",", ":"), ensure_ascii=True) + "\n"
            hasher.update(line.encode("utf-8"))

        # 9. Attempts
        for row in self.session.scalars(select(Attempt).order_by(Attempt.attempt_id).execution_options(yield_per=1000)):
            line = json.dumps([
                "ATTEMPT", row.attempt_id, row.learner_id, row.content_id, row.attempt_number,
                _canon(row.started_at), _canon(row.completed_at), row.time_spent_seconds, row.status
            ], separators=(",", ":"), ensure_ascii=True) + "\n"
            hasher.update(line.encode("utf-8"))

        # 10. AssessmentResults
        for row in self.session.scalars(select(AssessmentResult).order_by(AssessmentResult.result_id).execution_options(yield_per=1000)):
            line = json.dumps([
                "RESULT", row.result_id, row.attempt_id, _canon(row.raw_score), _canon(row.max_score),
                _canon(row.normalized_score), _canon(row.is_passed), _canon(row.graded_at)
            ], separators=(",", ":"), ensure_ascii=True) + "\n"
            hasher.update(line.encode("utf-8"))

        return hasher.hexdigest()