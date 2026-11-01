# SkillPath AI — Personalized Learning Recommendation System

**Specification References:**
- Functional & Domain Model Specification: **SRS v1.2.0-FINAL-SPEC**
- Temporal Evaluation & Quality Audit Specification: **Evaluation Methodology Version 2.3**

**Technology Stack:**
- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.0, SQLite, Pydantic v2
- **Frontend:** React 18, Vite, TypeScript 5.6, Recharts 2.15, Lucide React

---

## 1. Quick Start & Startup Commands

### Prerequisites
- Python 3.11 (`.venv` virtual environment configured at project root)
- Node.js >= 18 and npm >= 9

### Starting the Application Locally

#### Terminal 1 — Start the Backend (FastAPI)
```powershell
# Navigate to D:\SkillPathAI
.\.venv\Scripts\Activate.ps1
uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```
- Interactive Swagger API Docs: `http://localhost:8000/docs`
- ReDoc API Docs: `http://localhost:8000/redoc`
- System Health Endpoint: `http://localhost:8000/api/v1/health`

#### Terminal 2 — Start the Frontend (Vite + React)
```powershell
# Navigate to D:\SkillPathAI\frontend
cd frontend
npm run dev
```
- Web Application: `http://localhost:5173`

---

## 2. API Endpoints

| Category | Method | Endpoint | Description |
| :--- | :--- | :--- | :--- |
| **Health** | `GET` | `/health` / `/api/v1/health` | Service and database connectivity probe |
| **Learner Overview** | `GET` | `/api/v1/learners/{id}/overview` | Learner progress metrics, skills needing attention, and recent activity |
| **Recommendations** | `GET` | `/api/v1/learners/{id}/recommendations` | Point-in-time personalized recommendations with prerequisite gating |
| **Outcome Tracking** | `POST` | `/api/v1/recommendations/{id}/start` | Record recommendation start event |
| | `POST` | `/api/v1/recommendations/{id}/complete` | Record completion event |
| | `POST` | `/api/v1/recommendations/{id}/abandon` | Record abandonment event |
| | `POST` | `/api/v1/recommendations/{id}/evaluate` | Evaluate learning gain and outcome state transition |
| **Evaluation** | `GET` | `/api/v1/evaluation/latest` | Read-only access to latest multi-window Version 2.3 evaluation report |
| **Anomalies** | `GET` | `/api/v1/anomalies/status` | Read-only baseline audit (0 violations) and sandbox benchmark metrics (100% P/R) |

---

## 3. Interactive Dashboards

### A. Dashboard & Recommendation Tester
- Live recommendation testing for any learner ID (e.g. `LRN-000001` through `LRN-000100`).
- Configurable top-$K$ recommendations and cutoff timestamps.
- Interactive Recharts visualization breaking down ranking score components: Skill Gap (40%), Difficulty Suitability (25%), Path Alignment (20%), and Spaced Practice Urgency (15%).
- Detailed rejection diagnostics (prerequisite blocked, no skill gap, already mastered, unpublished).

### B. Temporal Evaluation Reports Tab
- **Multi-Window Navigation:** Evaluates recommendation quality across temporal splits: Window 1 (Aug 1, 2026), Window 2 (Sep 1, 2026), and Window 3 (Oct 1, 2026).
- **Partially Observed Horizon Flag:** Explicitly flags the October 2026 window as right-censored (14-day observation window through 2026-10-15 instead of 30 days), noting that unobserved interaction reflects exposure limits rather than lack of learner relevance.
- **Methodology Version 2.3 Metrics:**
  - *Precision@K (Fixed-K):* Strict denominator $K$ penalizing short lists.
  - *Realized Precision@K:* Denominator $\min(K, |\text{recs}|)$, accounting for prerequisite gating.
  - *Observed Precision@K:* Precision conditioned on items the learner completed.
  - *Unobserved Exposure Rate:* Fraction of recommendations unreached by the learner.
  - *NDCG@K (Pool):* IDCG computed against external post-cutoff engagement pool.
  - *Catalog Coverage & Gini Coefficient:* Measuring curriculum diversity and concentration.
- **Diagnostic Deep-Dives:**
  - *Cold-Start Conversion (Section 3.4):* Total, active, and converted learners with overall and conditional rates.
  - *Observational Learning Gain (Section 3.3):* Hake-normalized learning gain $g = \frac{\text{Post} - \text{Pre}}{1 - \text{Pre}}$.
  - *Stratified Activity Disparity (Section 3.5.2):* Equity audit across `low`, `med`, `high` strata with $N \ge 5$ threshold and diagnostic status codes (`EQUITY_MET`, `DISPARITY_WARNING`, `ZERO_MAX_METRIC`).
- **Honest Null Handling:** Formats unobserved or undefined values as `—` or `N/A`, never fabricating artificial zeros.

### C. Data Quality & Anomaly Detection Tab
- **Section 1: Baseline Production Database Integrity (`skillpath.db`):**
  - Read-only execution with `PRAGMA query_only = ON;`.
  - Audits all 5 SRS anomaly categories (A1: Prerequisite Violation, A2: Timestamp Order Inversion, A3: Nonexistent Skill Reference, A4: Future Mastery Leakage, A5: Learning Path Loops).
  - Confirms **0 violations** across all checked entities.
- **Section 2: Isolated Sandbox Benchmark:**
  - Evaluates detector accuracy against ground-truth labels (`data/ground_truth/anomaly_labels.csv`) using the isolated sandbox (`data/anomalies/skillpath_anomaly_sandbox.db`).
  - Reports **100.0% Precision, 100.0% Recall, 1.0000 F1-score** across all five canonical anomaly categories.

---

## 4. Synthetic Data Generator

The generator (`generate_data.py`) materializes relationally intact SQLite databases with parent-before-child ordering and deterministic random seeding (`seed=20261022`).

### Supported Profiles

| Profile | Learners | Skills | Courses | Content Items | Attempts | Cold-Start |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **development** | 100 | 50 | 10 | 100 | 2,000 | 10 |
| **integration** | 500 | 200 | 50 | 500 | 20,000 | 50 |
| **full** | 10,000 | 500 | 200 | 2,000 | 500,000 | 1,000 |

### Memory-Safe Batching Architecture
- Generates attempts and assessments using bounded dictionary batches (`--batch-size`, default: 5,000).
- Emits direct bulk inserts via `session.execute(insert(...), batch)`, preventing accumulation of hundreds of thousands of ORM instances in SQLAlchemy's identity map.
- Bounds memory footprint to $O(\text{batch\_size})$ while preserving transactional integrity (atomic commit on success, full rollback on error).

### Strict Safety Constraints
- **Baseline Protection:** Refuses to write to, alter, or recreate the baseline database (`skillpath.db`) under any argument or flag.
- **Overwrite Safety:** Refuses to overwrite an existing database file unless `--overwrite` is explicitly supplied.
- **Post-Generation Validation:** Runs `PRAGMA foreign_key_check;` and verifies exact profile counts after generation.

### Generator CLI Usage Examples
```powershell
# Generate development dataset to a safe isolated destination
python generate_data.py --profile development --output-db data/generated/dev_test.db --overwrite

# Generate integration dataset (500 learners, 20,000 attempts)
python generate_data.py --profile integration --output-db data/generated/integration.db --overwrite

# Specify custom batch size for memory-constrained environments
python generate_data.py --profile integration --output-db data/generated/integration.db --batch-size 2000 --overwrite
```

> **Performance Testing Disclosure:**
> While the generator architecture and bounded batching theoretically scale to the full profile (10,000 learners, 500,000 attempts), full-scale generation has **not** been claimed as performance-tested under operational memory and time constraints. Development and Integration profiles are fully verified and tested.

---

## 5. Relational Dataset Exporter

The export utility (`export_dataset.py`) extracts database tables into structured CSV and JSON files accompanied by an export manifest (`manifest.json`).

### Export Features
- **Strict Read-Only Connection:** Enforces SQLite URI read-only mode (`?mode=ro`) and `PRAGMA query_only = ON;`. The source database is never modified.
- **Dual Formats:** Simultaneously outputs comma-separated values (`.csv`) and formatted JSON (`.json`) for each table.
- **Deterministic Ordering:** Exports tables in parent-first dependency order (skills, courses, content, learners, attempts, assessments, etc.).
- **Consistent Serialization:** Dates formatted as ISO 8601 strings, decimals formatted with 4 decimal places, nulls formatted as `""` (CSV) and `null` (JSON), booleans formatted as `true`/`false`.
- **Empty Table Handling:** Handles zero-row tables safely by writing header-only CSVs and empty JSON arrays `[]`.
- **Export Manifest:** Generates `manifest.json` detailing row counts, file paths, byte sizes, and column names.
- *(Note: Parquet format is not supported or claimed.)*

### Exporter CLI Usage Examples
```powershell
# Export all tables from baseline database to data/exports/baseline/
python export_dataset.py --db-path skillpath.db --output-dir data/exports/baseline

# Export integration database
python export_dataset.py --db-path data/generated/integration.db --output-dir data/exports/integration

# Export specific subset of tables
python export_dataset.py --db-path skillpath.db --output-dir data/exports/curriculum --tables skills courses content_items
```

---

## 6. Testing & Quality Verification

### Running Automated Backend Tests
```powershell
# Run the complete test suite (194 passing tests)
.\.venv\Scripts\python.exe -m pytest -q

# Run generator profile, batching, and safety tests
.\.venv\Scripts\python.exe -m pytest tests/unit/test_generator_profiles_batching.py -v

# Run dataset export tests
.\.venv\Scripts\python.exe -m pytest tests/unit/test_dataset_export.py -v

# Run evaluation and anomaly API tests
.\.venv\Scripts\python.exe -m pytest tests/api/test_evaluation_anomalies_api.py -v
```

### Running Frontend Verification
```powershell
cd frontend

# Run TypeScript typecheck (zero errors)
npm run lint
```

### Verifying Baseline Database Integrity
```powershell
.\.venv\Scripts\python.exe -c "import hashlib; print(hashlib.sha256(open('skillpath.db', 'rb').read()).hexdigest().upper())"
# Expected: 252331E11EA93056AA6DAEBAB1AFAB8F75B00354B4628B30671E65C5E790E3D2
```

---

## 7. Current Verified Verification Summary

| Verification Target | Command / Metric | Verified Outcome |
| :--- | :--- | :--- |
| **Backend Test Suite** | `pytest -q` | **194 passed, 1 warning** (116s) |
| **Frontend TypeScript** | `npm run lint` (`tsc --noEmit`) | **0 errors, 0 warnings** |
| **Baseline DB SHA-256** | SHA-256 Checksum | `252331E11EA93056AA6DAEBAB1AFAB8F75B00354B4628B30671E65C5E790E3D2` **(Untouched)** |
| **Integration Generation** | `generate_data.py --profile integration` | **32,925 rows generated, 0 FK violations** (9s) |
| **Dataset Export** | `export_dataset.py` | **15 tables exported to CSV + JSON with manifest** (4s) |
| **Anomaly Benchmark** | `AnomalyEvaluator` | **Precision: 1.0, Recall: 1.0, F1: 1.0** across A1–A5 |
