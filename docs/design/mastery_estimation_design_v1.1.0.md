# Technical Design Specification: Learner Skill Mastery Estimation Module

**Document Version:** 1.1.0-DESIGN  
**Status:** Approved Design Specification — Implementation Pending  
**Target Module:** `src/services/mastery_service.py`  
**Reference Specification:** SRS v1.2.0-FINAL-SPEC  
**System Baseline Date:** October 31, 2026

---

## 1. Executive Overview

The Mastery Estimation Module calculates a learner's estimated competency in individual skills using historical assessment results.

It must:

1. Calculate mastery using an unbiased recency- and relevance-weighted average.
2. Distinguish unknown mastery from measured zero mastery.
3. Prevent temporal leakage by excluding evidence graded after the decision cutoff.
4. Preserve the IDs and timestamps of all contributing assessment results.
5. Store historical snapshots using append-only semantics.
6. Support deterministic, repeatable calculations.
7. Keep recommendation ranking and cold-start heuristics outside this module.

The existing verified development database must remain unchanged except for the insertion of mastery snapshot records.

## 2. Existing Database Contract

The implementation uses the existing SQLAlchemy models in `src/models/entities.py`.

Relevant entities:

- `Learner`
- `Skill`
- `Attempt`
- `AssessmentResult`
- `ContentSkill`
- `MasterySnapshot`

The existing `mastery_snapshots` table contains:

| Field | Purpose |
|---|---|
| snapshot_id | Unique snapshot identifier |
| learner_id | Learner foreign key |
| skill_id | Skill foreign key |
| mastery_level | Nullable mastery estimate |
| evidence_count | Number of contributing results |
| confidence_score | Evidence-volume indicator |
| cutoff_timestamp | Historical decision timestamp |
| max_evidence_graded_at | Latest contributing assessment timestamp |
| evidence_result_ids_json | JSON array of contributing result IDs |
| algorithm_version | Algorithm version |
| calculated_at | Snapshot creation timestamp |

The existing unique constraint is:

`(learner_id, skill_id, cutoff_timestamp, algorithm_version)`

No schema migration is authorized for this implementation unless an actual model mismatch is discovered and reviewed first.

## 3. Mathematical Formulation

### 3.1 Evidence Eligibility

For learner \(l\), skill \(s\), and cutoff timestamp \(T\), define \(E(l,s,T)\) as the set of eligible positive-weight assessment records.

A result is eligible only when:

- Its attempt belongs to learner \(l\).
- Its attempt content is mapped to skill \(s\).
- The attempt status is `COMPLETED`.
- `started_at <= completed_at`.
- `completed_at <= graded_at`.
- `graded_at <= T`.
- Its content-skill relevance weight is strictly positive.

Only records with a positive effective weight are included in the evidence set.

### 3.2 Recency Weight

For every eligible result:

\[
\Delta t_i = T - graded\_at_i
\]

The half-life is 30 days.

\[
w_i = 2^{-\frac{\Delta t_i}{30\text{ days}}}
\]

Equivalent exponential formulation:

\[
w_i = \exp(-\lambda\Delta t_i)
\]

where:

\[
\lambda = \frac{\ln 2}{2,592,000}
\]

and elapsed time is measured in seconds for the exponential formulation.

### 3.3 Mastery Calculation

Let:

- \(s_i\) = normalized assessment score.
- \(r_{i,s}\) = relevance weight for skill \(s\).
- \(w_i\) = recency weight.

Then:

\[
M(l,s,T)=
\frac{\sum_{i=1}^{n}w_i r_{i,s}s_i}
{\sum_{i=1}^{n}w_i r_{i,s}}
\]

The result is rounded to four decimal places using half-to-even rounding.

If no eligible evidence exists:

\[
M(l,s,T)=NULL
\]

The result must remain between 0.0000 and 1.0000.

### 3.4 Evidence-Volume Confidence Indicator

This indicator represents the volume of available evidence. It is not a statistical confidence interval and does not assume independent assessments.

\[
C(l,s,T)=
\begin{cases}
0.0000 & n=0\\
\min(1,\frac{n}{3}) & n>0
\end{cases}
\]

The indicator reaches 1.0000 when three or more eligible assessment results exist.

Confidence must not be multiplied into the mastery estimate.

## 4. Assessment Score Rules

Assessment results originate from completed attempts.

Normalized score:

\[
s_i=\frac{raw\_score}{max\_score}
\]

Requirements:

- `raw_score >= 0`.
- `max_score > 0`.
- `normalized_score` must match the calculated ratio within the existing database tolerance.
- Scores must be bounded between 0 and 1.
- Use continuous normalized scores rather than pass/fail flags.

The existing pass threshold is 0.70.

Only assessment-bearing content types such as `QUIZ`, `LAB`, and `PROJECT` contribute assessment evidence.

`VIDEO` and `READING` attempts do not contribute unless a valid assessment result exists.

## 5. Content-Skill Relevance Weights

The `content_skills.relevance_weight` column uses `Numeric(3, 2)`.

The database allows values in:

\[
0.00 \le r_{i,s} \le 1.00
\]

The synthetic generator currently creates values from 0.50 to 1.00.

The mastery service must not assume that the database enforces a minimum of 0.50.

**Strict positivity rule:** Only records where `relevance_weight > 0.00` contribute to mastery.

A zero-relevance record is excluded from the evidence set entirely. It must not be counted in `evidence_count`, the lineage array, or the confidence indicator.

The weighted contribution is:

\[
w_i \times r_{i,s}
\]

## 6. Retake Handling

Every eligible completed and graded attempt contributes a distinct evidence record.

Repeated attempts on identical content are not necessarily statistically independent because question familiarity can influence later scores.

However:

- Do not discard earlier attempts.
- Do not overwrite historical assessment results.
- Include every eligible retake.
- Apply the same recency-weighting formula to every result.
- Preserve every contributing result ID in the lineage.

The service must behave deterministically for repeated calculations with identical input data.

## 7. Unknown Mastery Versus Measured Zero

These states must never be confused.

| Property | Unknown | Measured zero |
|---|---|---|
| mastery_level | NULL | 0.0000 |
| evidence_count | 0 | At least 1 |
| confidence_score | 0.0000 | At least 0.3333 |
| is_unknown | True | False |
| max_evidence_graded_at | NULL | Non-null |
| evidence_result_ids_json | [] | Non-empty array |

Unknown means the skill has not been assessed.

Measured zero means an assessment occurred and the learner received zero points.

## 8. Temporal Leakage Prevention

The SQL query must enforce:

```sql
SELECT
    ar.result_id,
    ar.normalized_score,
    ar.graded_at,
    cs.relevance_weight,
    a.started_at,
    a.completed_at
FROM assessment_results ar
JOIN attempts a
    ON ar.attempt_id = a.attempt_id
JOIN content_skills cs
    ON a.content_id = cs.content_id
WHERE a.learner_id = :learner_id
  AND cs.skill_id = :skill_id
  AND a.status = 'COMPLETED'
  AND a.started_at <= a.completed_at
  AND a.completed_at <= ar.graded_at
  AND ar.graded_at <= :cutoff_timestamp
  AND cs.relevance_weight > 0.0;
```

The service must never use an assessment graded after the requested cutoff.

An assessment at exactly the cutoff is eligible.

An assessment one second after the cutoff is excluded.

## 9. Evidence Lineage

Each snapshot must preserve:

- The number of eligible results.
- The JSON array of result IDs.
- The latest contributing assessment timestamp.
- The decision cutoff timestamp.
- The algorithm version.
- The calculation timestamp.

### Mandatory invariants

1. `evidence_count == len(json.loads(evidence_result_ids_json))`.
2. Evidence IDs must be unique.
3. Every evidence ID must reference an existing assessment result.
4. Every referenced result must satisfy `graded_at <= cutoff_timestamp`.
5. `max_evidence_graded_at` must equal the maximum `graded_at` among the referenced results.
6. Empty evidence must use the exact representation:

```text
mastery_level = NULL
evidence_count = 0
confidence_score = 0.0000
max_evidence_graded_at = NULL
evidence_result_ids_json = []
```

7. Non-empty evidence must have non-null mastery, positive evidence count, positive confidence, and non-null maximum evidence timestamp.

### Deterministic ordering

Store evidence IDs ordered by:

1. `graded_at ASC`
2. `result_id ASC`

This makes lineage reproducible.

## 10. Snapshot Immutability and Versioning

Snapshots use write-once, append-only semantics.

The mastery service must never update or delete an existing snapshot.

For an identical tuple:

`(learner_id, skill_id, cutoff_timestamp, algorithm_version)`

the service must return the existing snapshot rather than inserting a duplicate.

If the algorithm version changes, a separate snapshot may be created for the same learner, skill, and cutoff.

Example:

- `v1.2.0`
- `v1.3.0`

Both versions may coexist for the same learner, skill, and cutoff timestamp.

The implementation must verify immutability through actual SQL statement monitoring or SQLAlchemy event listeners, not only by inspecting source code.

## 11. Cold-Start Handling

The verified development dataset contains exactly 10 cold-start learners:

`LRN-000091` through `LRN-000100`.

For a learner without eligible assessment evidence:

- `mastery_level = NULL`
- `is_unknown = True`
- `evidence_count = 0`
- `confidence_score = 0.0000`
- `max_evidence_graded_at = NULL`
- `evidence_result_ids_json = []`

The mastery service must not implement recommendation ranking, candidate filtering, curriculum sequencing, or default cold-start ranking scores.

Those responsibilities belong to the recommendation engine.

## 12. Worked Examples

### Example A — Single assessment

- Score: 0.8800
- Relevance: 1.00
- Assessment graded 12 hours before cutoff.

The recency weight is approximately 0.988514.

Because only one assessment contributes:

\[
M=0.8800
\]

Confidence:

\[
C=0.3333
\]

### Example B — Three assessments

| Age | Score | Relevance | Recency weight |
|---|---:|---:|---:|
| 60 days | 0.6000 | 1.00 | 0.25 |
| 30 days | 0.8000 | 0.75 | 0.50 |
| 0 days | 0.9500 | 0.50 | 1.00 |

Numerator:

\[
0.15+0.30+0.475=0.925
\]

Denominator:

\[
0.25+0.375+0.50=1.125
\]

Mastery:

\[
M=0.8222
\]

Confidence:

\[
C=1.0000
\]

### Example C — Three retakes

One quiz is attempted three times:

| Attempt | Score | Age | Weight |
|---|---:|---:|---:|
| 1 | 0.30 | 60 days | 0.25 |
| 2 | 0.60 | 30 days | 0.50 |
| 3 | 0.90 | 0 days | 1.00 |

Mastery:

\[
M=\frac{0.075+0.300+0.900}{0.25+0.50+1.00}
\]

\[
M=0.7286
\]

Confidence:

\[
C=1.0000
\]

All three attempts remain in the evidence lineage.

### Example D — Zero versus Unknown

A learner scores 0/100:

- Mastery = 0.0000
- Evidence count = 1
- Confidence = 0.3333
- Unknown = False

A learner has no assessment evidence:

- Mastery = NULL
- Evidence count = 0
- Confidence = 0.0000
- Unknown = True

## 13. Edge Cases

| Scenario | Expected behavior |
|---|---|
| Graded exactly at cutoff | Include |
| Graded one second after cutoff | Exclude |
| Identical timestamps | Sort by result ID |
| Zero relevance | Exclude entirely |
| Old assessment | Apply recency decay |
| In-progress attempt | Exclude |
| Abandoned attempt | Exclude |
| Video or reading without assessment | Exclude |
| Multiple retakes | Include all eligible retakes |
| Empty evidence | Return Unknown |

## 14. Unit Tests and Acceptance Criteria

Target file:

`tests/unit/test_mastery_service.py`

Required tests:

| Test | Expected result |
|---|---|
| MAST-001 Empty history | Unknown state |
| MAST-002 Zero score | Mastery 0.0000 |
| MAST-003 Perfect score | Mastery 1.0000 |
| MAST-004 Half-life | 30-day weight ratio is 1:0.5 |
| MAST-005 Relevance | Weight scales relative contribution |
| MAST-006 Zero relevance | Excluded from evidence |
| MAST-007 Three retakes | All three contribute |
| MAST-008 Future evidence | Excluded |
| MAST-009 Lineage count | Count matches JSON length |
| MAST-010 Timestamp agreement | Maximum timestamp matches lineage |
| MAST-011 Unique IDs | No duplicate lineage IDs |
| MAST-012 Immutability | No UPDATE or DELETE statements |
| MAST-013 Idempotency | Existing snapshot returned |
| MAST-014 Version coexistence | Different versions create distinct snapshots |

Additional requirements:

- Verify foreign-key integrity of lineage IDs.
- Verify empty and non-empty lineage representations.
- Verify deterministic ordering.
- Verify mastery remains within [0, 1].
- Verify existing database records are not modified.

## 15. Implementation Boundaries

The implementation target is:

`src/services/mastery_service.py`

The service should contain focused responsibilities:

1. Retrieve eligible assessment evidence.
2. Calculate recency weights.
3. Calculate weighted mastery.
4. Calculate the evidence-volume confidence indicator.
5. Build deterministic evidence lineage.
6. Retrieve an existing snapshot when appropriate.
7. Persist a new append-only snapshot.
8. Return the resulting snapshot.

Do not implement recommendation ranking, anomaly injection, synthetic data generation, frontend changes, or database migrations in this milestone.

## 16. Implementation Sequence

1. Inspect existing SQLAlchemy models.
2. Confirm actual column names and types.
3. Implement the mastery service.
4. Write isolated unit tests.
5. Run the new mastery tests.
6. Run the complete existing pytest suite.
7. Verify database row counts and foreign-key integrity.
8. Verify that no existing records were modified.
9. Document actual test results.

**Final acceptance condition:** The mastery module is complete only when all specified tests pass and the original development dataset remains intact.