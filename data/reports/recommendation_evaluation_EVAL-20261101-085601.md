# SkillPath AI — Recommendation Quality & Temporal Evaluation Report

**Evaluation ID:** `EVAL-20261101-085601`  
**Generated At:** `2026-11-01T08:56:01.588406+00:00`  
**Dataset Profile:** `development` (`skillpath.db`)  

---

## 1. Relevance Mapping & Methodology Specifications

| Grade | Level | Operational Definition in Outcome Window $(T, T + 30\text{ days}]$ |
|:---:|---|---|
| **0** | Grade 0 | Unobserved / Non-relevant (no completed interaction in outcome window) |
| **1** | Grade 1 | Engaged (completed content attempt in outcome window) |
| **2** | Grade 2 | Proficient (completed attempt with normalized score >= 0.70) |
| **3** | Grade 3 | Target Gap Closed (prior mastery < 0.70, assessment passed, and mastery improved) |

### Methodology & Methodological Invariants:
- Temporal Isolation: Recommendations and historical mastery use evidence with timestamp <= T.
- Fixed-K Precision: Denominator is strictly K, penalizing incomplete recommendation lists.
- Realized Precision: Denominator is realized list length min(K, |recs|), accounting for prerequisite gating.
- External Ideal Pool NDCG: IDCG computed from complete outcome-window engagement pool.
- Observational Learning Gain: Hake-normalized delta evaluated using earliest post-cutoff assessment.
- Cold-Start Conversion: Evaluates conversion into active, proficient learners without prior history.
- Stratified Activity Disparity: Audits relative and absolute equity across low, med, high activity strata.
- Primary Recall: Denominator is |Relevant|, bounded Recall reported as auxiliary.
- Unobserved Interaction: Unobserved interaction reflects exposure limits, not proof of irrelevance.
- Causality Disclaimer: Retrospective alignment measures predictive correlation, not causal lift.
- Partially Observed Horizon: Windows extending past dataset max timestamp are flagged and bounded.

---

## 2. Multi-Cutoff Evaluation Results

### Window 1: Cutoff `2026-08-01T00:00:00`

- **Outcome Interval:** `2026-08-01T00:00:00` to `2026-08-31T00:00:00`
- **Planned End:** `2026-08-31T00:00:00` | **Truncated:** `False`
- **Learner Accounting:** Total = `100`, Evaluated = `63`, Excluded = `37`, Cold-Start = `14`
- **Active Catalog Size:** `100` items

| Rank K | Precision@K | Realized Prec@K | Observed Prec@K | Exposure Rate | Std Recall@K | NDCG@K (Pool) | Coverage | Gini |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **@1** | 0.0000 | 0.0000 | N/A | 1.0000 | 0.0000 | 0.0000 | 0.2000 | 0.8930 |
| **@3** | 0.0423 | 0.0423 | 1.0000 | 0.9577 | 0.0556 | 0.0457 | 0.3200 | 0.8805 |
| **@5** | 0.0317 | 0.0317 | 1.0000 | 0.9683 | 0.0635 | 0.0445 | 0.4000 | 0.8728 |
| **@10** | 0.0317 | 0.0317 | 1.0000 | 0.9683 | 0.1341 | 0.0670 | 0.5500 | 0.8344 |

#### Version 2.3 Diagnostic Dimensions:
- **Cold-Start Conversion:** Total=14, Active=0, Converted=0 | Overall Rate=`0.0000`, Conditional Rate=`N/A` (Diagnostic: `NO_COLD_START_ATTEMPTS`)
- **Observational Learning Gain (Earliest Assessment):** `-0.0578`
- **Stratified Activity Disparity (Rank @5):** Absolute=`0.0273`, Ratio=`0.4000` (Diagnostic: `DISPARITY_WARNING`)

#### Read-Only Business-Rule & Anomaly Audits:
- **PREREQUISITE_COMPLIANCE (PREREQUISITE_VIOLATION):** `0` violations across `1000` checked — ✅ PASS
- **TIMESTAMP_ORDERING (TIMESTAMP_ORDER_INVERSION):** `0` violations across `2000` checked — ✅ PASS
- **ORPHANED_CONTENT_SKILLS (NONEXISTENT_SKILL_REFERENCE):** `0` violations across `193` checked — ✅ PASS
- **FUTURE_MASTERY_LEAKAGE (FUTURE_ATTEMPT_LEAKAGE):** `0` violations across `1000` checked — ✅ PASS
- **LEARNING_PATH_LOOPS (LEARNING_PATH_LOOP):** `0` violations across `699` checked — ✅ PASS

### Window 2: Cutoff `2026-09-01T00:00:00`

- **Outcome Interval:** `2026-09-01T00:00:00` to `2026-10-01T00:00:00`
- **Planned End:** `2026-10-01T00:00:00` | **Truncated:** `False`
- **Learner Accounting:** Total = `100`, Evaluated = `61`, Excluded = `39`, Cold-Start = `14`
- **Active Catalog Size:** `100` items

| Rank K | Precision@K | Realized Prec@K | Observed Prec@K | Exposure Rate | Std Recall@K | NDCG@K (Pool) | Coverage | Gini |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **@1** | 0.0164 | 0.0164 | 1.0000 | 0.9836 | 0.0082 | 0.0164 | 0.2000 | 0.8916 |
| **@3** | 0.0055 | 0.0055 | 1.0000 | 0.9945 | 0.0082 | 0.0101 | 0.3300 | 0.8785 |
| **@5** | 0.0066 | 0.0066 | 1.0000 | 0.9934 | 0.0115 | 0.0106 | 0.3900 | 0.8685 |
| **@10** | 0.0213 | 0.0213 | 1.0000 | 0.9787 | 0.0718 | 0.0341 | 0.5500 | 0.8253 |

#### Version 2.3 Diagnostic Dimensions:
- **Cold-Start Conversion:** Total=14, Active=1, Converted=1 | Overall Rate=`0.0714`, Conditional Rate=`1.0000` (Diagnostic: `None`)
- **Observational Learning Gain (Earliest Assessment):** `-0.0113`
- **Stratified Activity Disparity (Rank @5):** Absolute=`0.0129`, Ratio=`0.0000` (Diagnostic: `DISPARITY_WARNING`)

#### Read-Only Business-Rule & Anomaly Audits:
- **PREREQUISITE_COMPLIANCE (PREREQUISITE_VIOLATION):** `0` violations across `1000` checked — ✅ PASS
- **TIMESTAMP_ORDERING (TIMESTAMP_ORDER_INVERSION):** `0` violations across `2000` checked — ✅ PASS
- **ORPHANED_CONTENT_SKILLS (NONEXISTENT_SKILL_REFERENCE):** `0` violations across `193` checked — ✅ PASS
- **FUTURE_MASTERY_LEAKAGE (FUTURE_ATTEMPT_LEAKAGE):** `0` violations across `1000` checked — ✅ PASS
- **LEARNING_PATH_LOOPS (LEARNING_PATH_LOOP):** `0` violations across `699` checked — ✅ PASS

### Window 3: Cutoff `2026-10-01T00:00:00` (⚠️ Partially Observed Horizon)

- **Outcome Interval:** `2026-10-01T00:00:00` to `2026-10-30T19:20:44`
- **Planned End:** `2026-10-31T00:00:00` | **Truncated:** `True`
- **Learner Accounting:** Total = `100`, Evaluated = `66`, Excluded = `34`, Cold-Start = `13`
- **Active Catalog Size:** `100` items

| Rank K | Precision@K | Realized Prec@K | Observed Prec@K | Exposure Rate | Std Recall@K | NDCG@K (Pool) | Coverage | Gini |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **@1** | 0.0303 | 0.0303 | 1.0000 | 0.9697 | 0.0114 | 0.0303 | 0.2300 | 0.8800 |
| **@3** | 0.0354 | 0.0354 | 1.0000 | 0.9646 | 0.0333 | 0.0348 | 0.3600 | 0.8731 |
| **@5** | 0.0273 | 0.0273 | 1.0000 | 0.9727 | 0.0485 | 0.0397 | 0.4100 | 0.8641 |
| **@10** | 0.0348 | 0.0348 | 1.0000 | 0.9652 | 0.1153 | 0.0723 | 0.5700 | 0.8203 |

#### Version 2.3 Diagnostic Dimensions:
- **Cold-Start Conversion:** Total=13, Active=0, Converted=0 | Overall Rate=`0.0000`, Conditional Rate=`N/A` (Diagnostic: `NO_COLD_START_ATTEMPTS`)
- **Observational Learning Gain (Earliest Assessment):** `0.0039`
- **Stratified Activity Disparity (Rank @5):** Absolute=`0.0414`, Ratio=`0.0000` (Diagnostic: `DISPARITY_WARNING`)

#### Read-Only Business-Rule & Anomaly Audits:
- **PREREQUISITE_COMPLIANCE (PREREQUISITE_VIOLATION):** `0` violations across `1000` checked — ✅ PASS
- **TIMESTAMP_ORDERING (TIMESTAMP_ORDER_INVERSION):** `0` violations across `2000` checked — ✅ PASS
- **ORPHANED_CONTENT_SKILLS (NONEXISTENT_SKILL_REFERENCE):** `0` violations across `193` checked — ✅ PASS
- **FUTURE_MASTERY_LEAKAGE (FUTURE_ATTEMPT_LEAKAGE):** `0` violations across `1000` checked — ✅ PASS
- **LEARNING_PATH_LOOPS (LEARNING_PATH_LOOP):** `0` violations across `699` checked — ✅ PASS

