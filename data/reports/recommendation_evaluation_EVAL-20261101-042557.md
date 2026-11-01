# SkillPath AI — Recommendation Quality & Temporal Evaluation Report

**Evaluation ID:** `EVAL-20261101-042557`  
**Generated At:** `2026-11-01T04:25:57.045573+00:00`  
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
- Primary Recall: Denominator is |Relevant|, bounded Recall reported as auxiliary.
- Unobserved Interaction: Unobserved interaction reflects exposure limits, not proof of irrelevance.
- Causality Disclaimer: Retrospective alignment measures predictive correlation, not causal lift.
- Partially Observed Horizon: Windows extending past dataset max timestamp are flagged and bounded.

---

## 2. Multi-Cutoff Evaluation Results

### Window 1: Cutoff `2026-08-01T00:00:00`

- **Outcome Interval:** `2026-08-01T00:00:00` to `2026-08-31T00:00:00`
- **Planned End:** `2026-08-31T00:00:00` | **Truncated:** `False`
- **Learner Accounting:** Total = `100`, Evaluated = `63`, Excluded = `37`, Cold-Start = `11`
- **Active Catalog Size:** `100` items

| Rank K | Precision@K (Fixed-K) | Standard Recall@K | Bounded Recall@K | NDCG@K (Grades 0-3) | Catalog Coverage | Gini Coefficient |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **@1** | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.2000 | 0.8930 |
| **@3** | 0.0423 | 0.0556 | 0.0635 | 0.0457 | 0.3200 | 0.8805 |
| **@5** | 0.0317 | 0.0635 | 0.0656 | 0.0445 | 0.4000 | 0.8728 |
| **@10** | 0.0317 | 0.1341 | 0.1341 | 0.0670 | 0.5500 | 0.8344 |

- **Prerequisite Compliance Rate:** `1.0000` (0 violations) ✅ PASS
- **Temporal Leakage Rate:** `0.0000` (0 leaking calculations) ✅ ZERO LEAKAGE

### Window 2: Cutoff `2026-09-01T00:00:00`

- **Outcome Interval:** `2026-09-01T00:00:00` to `2026-10-01T00:00:00`
- **Planned End:** `2026-10-01T00:00:00` | **Truncated:** `False`
- **Learner Accounting:** Total = `100`, Evaluated = `61`, Excluded = `39`, Cold-Start = `11`
- **Active Catalog Size:** `100` items

| Rank K | Precision@K (Fixed-K) | Standard Recall@K | Bounded Recall@K | NDCG@K (Grades 0-3) | Catalog Coverage | Gini Coefficient |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **@1** | 0.0164 | 0.0082 | 0.0164 | 0.0164 | 0.2000 | 0.8916 |
| **@3** | 0.0055 | 0.0082 | 0.0082 | 0.0101 | 0.3300 | 0.8785 |
| **@5** | 0.0066 | 0.0115 | 0.0115 | 0.0106 | 0.3900 | 0.8685 |
| **@10** | 0.0213 | 0.0718 | 0.0718 | 0.0341 | 0.5500 | 0.8253 |

- **Prerequisite Compliance Rate:** `1.0000` (0 violations) ✅ PASS
- **Temporal Leakage Rate:** `0.0000` (0 leaking calculations) ✅ ZERO LEAKAGE

### Window 3: Cutoff `2026-10-01T00:00:00` (⚠️ Partially Observed Horizon)

- **Outcome Interval:** `2026-10-01T00:00:00` to `2026-10-30T19:20:44`
- **Planned End:** `2026-10-31T00:00:00` | **Truncated:** `True`
- **Learner Accounting:** Total = `100`, Evaluated = `66`, Excluded = `34`, Cold-Start = `10`
- **Active Catalog Size:** `100` items

| Rank K | Precision@K (Fixed-K) | Standard Recall@K | Bounded Recall@K | NDCG@K (Grades 0-3) | Catalog Coverage | Gini Coefficient |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **@1** | 0.0303 | 0.0114 | 0.0303 | 0.0303 | 0.2300 | 0.8800 |
| **@3** | 0.0354 | 0.0333 | 0.0404 | 0.0348 | 0.3600 | 0.8731 |
| **@5** | 0.0273 | 0.0485 | 0.0503 | 0.0397 | 0.4100 | 0.8641 |
| **@10** | 0.0348 | 0.1153 | 0.1159 | 0.0723 | 0.5700 | 0.8203 |

- **Prerequisite Compliance Rate:** `1.0000` (0 violations) ✅ PASS
- **Temporal Leakage Rate:** `0.0000` (0 leaking calculations) ✅ ZERO LEAKAGE

