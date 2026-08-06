# KG-Based Workflow Validation

Convert XES event logs into a PROV-O provenance knowledge graph, visualize it, and validate workflow executions with graph rules. Control-flow rules R1–R4 are aligned with DECLARE templates so the same faults can be checked on XES (PM4Py DECLARE) and on the KG. Domain rules R5–R6 are evaluated on the KG.

## Workflow

| Step | Description | Pipeline stage |
|------|-------------|----------------|
| 1 | XES event log (traces / events) | `input` |
| 2 | Extract entities and relations | `conversion` |
| 3 | Emit RDF triples (Turtle) | `conversion` |
| 4 | Provenance knowledge graph | `*.prov.ttl` |
| 5 | Rule-based validation | `validation` |
| 6 | Violation report | `validation.json` |

Optional: `visualization` writes an interactive HTML graph.

```
XES event log → Mapping (XES → KG) → Provenance KG → Validation rules → Violation report
```

## Requirements

- Python 3.11+
- Dependencies in `requirements.txt` (`rdflib`, `pyvis`, `pm4py`, `requests`)
- A SPARQL 1.1 triple store with Graph Store Protocol (Apache Jena Fuseki via Docker is the default)

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS

pip install -r requirements.txt
```

## Triple-store (SPARQL) validation

KG validation is **SPARQL-only**: every rule (R1–R6) is a SPARQL `SELECT` executed on a remote triple store after the Turtle KG is bulk-loaded. Conversion still uses `rdflib` locally; validation does not.

The previous in-memory Python traversal engine is archived under `archive/python_rdflib_validation/`.

### 1. Start Fuseki

```powershell
# PowerShell — dot-source so env vars apply to your shell
. .\scripts\start_triplestore.ps1
```

```bash
# Linux / macOS / Git Bash
source scripts/start_triplestore.sh
```

Or manually:

```bash
docker compose -f docker-compose.fuseki.yml up -d
```

### 2. Configure endpoints (Fuseki defaults)

`start_triplestore.*` sets these for you. Manual equivalent:

```bash
# PowerShell
$env:KG_SPARQL_QUERY_ENDPOINT = "http://localhost:3030/ds/sparql"
$env:KG_SPARQL_UPDATE_ENDPOINT = "http://localhost:3030/ds/update"
$env:KG_SPARQL_GSP_ENDPOINT = "http://localhost:3030/ds/data"
$env:KG_SPARQL_USER = "admin"
$env:KG_SPARQL_PASSWORD = "admin"
```

Any SPARQL 1.1 store with Graph Store Protocol works (GraphDB, Blazegraph, …): point the three endpoint URLs at that server.

Stop later with `.\scripts\stop_triplestore.ps1` or `source scripts/stop_triplestore.sh`.

### 3. Smoke-test / single file

```bash
python scripts/run_triplestore_validation.py --ping
python scripts/run_triplestore_validation.py experiments/baseline_single_run/benchmarks/bench_r1_full/*.prov.ttl --rule R1
```

### 4. Run experiments

Paper multi-run (recommended):

```bash
python scripts/run_multi_run_experiment.py 10
```

Regenerate benches from scratch (optional, slower):

```bash
python scripts/run_full_experiment_suite.py all
```

| Env var | Meaning |
|---------|---------|
| `KG_SPARQL_QUERY_ENDPOINT` | SPARQL query URL (**required**) |
| `KG_SPARQL_UPDATE_ENDPOINT` | SPARQL update URL (CLEAR) |
| `KG_SPARQL_GSP_ENDPOINT` | Graph Store Protocol URL (Turtle upload) |
| `KG_SPARQL_USER` / `KG_SPARQL_PASSWORD` | Optional HTTP basic auth |
| `KG_SPARQL_TIMEOUT_SECONDS` | Per-request timeout (default 3600) |

Load time is CLEAR + Turtle upload; rule times are SPARQL query latency.

## Quick start

```bash
# Fuseki must be up and KG_SPARQL_* set (see above)
python -m src.run_pipeline
```

Enable stages with `true`/`false` in `config.ini`. Each run writes a folder under `output_dir`, e.g. `output/out_conv_vis_val_r1_r2_r3_r4_r5_r5b_r6_20260719_120530/`.

To **reproduce the paper multi-run timings** (full log ×10, SPARQL + DECLARE), see `experiments/README.md`:

```bash
python scripts/run_multi_run_experiment.py 10
```

To **regenerate all benches from scratch**, use `python scripts/run_full_experiment_suite.py all` (requires Fuseki; see [Experiment reproduction](#experiment-reproduction)).

## Configuration

All pipeline settings are in `config.ini`:

```ini
[pipeline]
input = dataset/DomesticDeclarations.sample_5declarations.xes
output_dir = output

conversion = true
visualization = true
validation = true

[validation]
R1 = true
R2 = true
R3 = true
R4 = true
R5 = true
R5B = true
R6 = true
```

| Option | Description |
|--------|-------------|
| `input` | Path to the XES event log (`.xes` or `.xes.gz`); required when `conversion = true` |
| `output_dir` | Base directory for run folders |
| `knowledge_graph` | Existing `.ttl` path; required when `conversion = false` |
| `conversion` | `true`/`false` — run XES → PROV-O conversion |
| `visualization` | `true`/`false` — write interactive HTML |
| `validation` | `true`/`false` — run validation rules |

Under `[validation]`, toggle each rule independently. When `validation = true`, at least one rule must be enabled.

Each run folder contains:

| File | Description |
|------|-------------|
| `*.prov.ttl` | PROV-O knowledge graph |
| `*.prov.html` | Interactive visualization (if enabled) |
| `validation.json` | Validation report (if enabled) |
| `statistics.json` | Counts, timings, and violation totals |

### Common examples

**Full demo**

```ini
conversion = true
visualization = true
validation = true
```

**Build KG only**

```ini
input = dataset/DomesticDeclarations.xes.gz
output_dir = output
conversion = true
visualization = false
validation = false
```

**Validate an existing KG**

```ini
output_dir = output
knowledge_graph = experiments/baseline_single_run/benchmarks/bench_r1_full/DomesticDeclarations.corrupted.prov.ttl
conversion = false
visualization = false
validation = true
```

**Visualize an existing KG**

```ini
output_dir = output
knowledge_graph = experiments/baseline_single_run/benchmarks/bench_r1_full/DomesticDeclarations.corrupted.prov.ttl
conversion = false
visualization = true
validation = false
```

## Running individual steps

```bash
python -m src.xes_to_prov_kg
python -m src.visualize_prov_kg
python -m src.validate_kg
```

Validation does not re-read XES: when `conversion = false`, set `knowledge_graph` to an existing `.ttl` file.

## XES → PROV-O conversion

Implemented in `src/xes_to_prov_kg.py`. The converter **streams** the log one trace at a time: each trace becomes a small RDF fragment appended to a Turtle file, so large logs need not be fully resident in memory.

### Mapping

| XES element | PROV-O / KG element | Main properties / relations |
|-------------|---------------------|-----------------------------|
| Trace (case) | `prov:Entity` | case id / label |
| Event | `prov:Activity` | activity label, event id |
| `org:resource` (+ role) | `prov:Agent` | `prov:wasAssociatedWith` |
| `time:timestamp` | time literals | `prov:startedAtTime`, `prov:endedAtTime` |
| Event order in a trace | control-flow link | `prov:wasInformedBy` |
| Trace membership | case link | `wf:belongsToCase`, `prov:used` |

Relations in more detail:

- `prov:wasAssociatedWith` — activity performed by agent
- `prov:used` — every activity uses the case entity
- `prov:wasInformedBy` — control-flow ordering within a case (later informed by earlier)
- `prov:wasGeneratedBy` — the case is generated by the first activity in the trace
- `wf:belongsToCase` — links activities to their case

### Design choices

- **Activities only** — events are modeled as activities (no separate event-entity layer).
- **Case-centric `prov:used`** — activities depend on the declaration (case); ordering is captured by `prov:wasInformedBy`.
- **No invented defaults** — missing timestamps/resources are omitted (with optional console warnings) so validation can detect gaps.
- **Full attribute preservation** — XES attributes are copied as `attr:xes-attr_*` predicates (colons → underscores).
- **Agent identity** — agent URIs are based on `org:resource` only.
- **Standard keys** — `id`, `concept:name`, `time:timestamp`, `org:resource`, `org:role` drive identity and PROV mapping; domain fields such as `Amount` / `BudgetNumber` are copied automatically.

## Visualization

`src/visualize_prov_kg.py` writes interactive HTML with **pyvis**:

- Blue boxes: `prov:Entity`
- Red ellipses: `prov:Activity`
- Green dots: `prov:Agent`

An internet connection is needed when viewing the HTML (vis-network CDN).

## Validation

Rules live in `src/validation_rules.py` (SPARQL definitions + DECLARE model) and are executed by `src/validate_kg.py` against a configured triple store (`src/sparql_endpoint.py`).

### How validation runs

1. `CLEAR` the store and bulk-upload the Turtle KG (Graph Store Protocol).
2. For each enabled rule, run its SPARQL `SELECT` on the query endpoint.
3. Aggregate into `validation.json` (overall status, per-rule status/counts/timings, and detailed findings).

Each answer / finding row is one violation, with an `issue` code and entity bindings.

The former in-memory Python traversals are archived under `archive/python_rdflib_validation/` and are not used.

### Rules overview

Activity labels match the BPI Challenge 2020 *Domestic Declarations* log.

- **R1–R4** — control-flow constraints aligned with DECLARE (`existence` / `response` / `precedence` / `succession`). The same faults can be checked with PM4Py DECLARE on XES and with the KG validator.
- **R5 / R5B / R6** — domain and provenance constraints around payment handling. Standard DECLARE templates do not cover these attribute- and path-level checks; we evaluate them on the KG.

| Rule | Name | DECLARE template | Violation issue(s) |
|------|------|------------------|--------------------|
| **R1** | `SUBMISSION_EXISTENCE` | `existence` | `missing_submission_existence` |
| **R2** | `APPROVAL_REQUEST_RESPONSE` | `response` | `missing_response_request_after_approval` |
| **R3** | `REQUEST_BEFORE_PAYMENT` | `precedence` | `missing_precedence_request_before_payment` |
| **R4** | `REQUEST_PAYMENT_SUCCESSION` | `succession` | `missing_succession_response_payment_after_request`, `missing_succession_precedence_request_before_payment` |
| **R5** | `PAYMENT_HANDLED_BY_SYSTEM` | (KG) | `payment_not_handled_by_system` |
| **R5B** | `PAYMENT_HANDLED_NOT_BY_EMPLOYEE` | (KG) | `payment_handled_by_employee` |
| **R6** | `PAYMENT_PROVENANCE_CHAIN` | (KG) | `invalid_payment_provenance_chain` |

Canonical DECLARE model for R1–R4: `DECLARE_MODEL_R1_R4` in `src/validation_rules.py`.

### How each rule is validated

#### R1 — submission existence (DECLARE `existence`)

- **Mechanism:** every case must contain an activity labelled `Declaration SUBMITTED by EMPLOYEE`.
- **Fails when:** a case has no submission activity.
- **Reports:** the case IRI.

#### R2 — approval → request response (DECLARE `response`)

- **Mechanism:** for each final approval, require a same-case `Request Payment` reachable via `request wasInformedBy+ approval`.
- **Fails when:** approval exists but no later request is reachable in the provenance chain.
- **Reports:** case and approval IRIs.
- **Note:** multiple approvals in one case can yield multiple rows for the same case.

#### R3 — request before payment (DECLARE `precedence`)

- **Mechanism:** for each `Payment Handled`, require a same-case `Request Payment` with `payment wasInformedBy+ request`.
- **Fails when:** payment has no request ancestor.
- **Reports:** case and payment IRIs.

#### R4 — request/payment succession (DECLARE `succession`)

- **Mechanism:** both halves of succession: every request must be followed by a payment, and every payment must be preceded by a request (via `wasInformedBy+`).
- **Fails when:** either direction is missing.
- **Reports:** case and the violating request or payment IRI.
- **Note:** one broken case may produce **two** R4 rows (one per succession half).

#### R5 — payment handled by SYSTEM

- **Mechanism:** SPARQL over activities labelled `Payment Handled`.
- **Fails when:** `attr:xes-attr_org_resource` is not `"SYSTEM"` (missing or wrong).
- **Reports:** the activity IRI and observed resource (if any).

#### R5B — payment not handled by EMPLOYEE

- **Mechanism:** SPARQL over `Payment Handled` activities that have a role.
- **Fails when:** `attr:xes-attr_org_role = "EMPLOYEE"`.
- **Reports:** the activity IRI and role.
- **Relation to R5:** complementary — R5 requires the correct resource; R5B forbids an invalid role.

#### R6 — payment provenance chain

- **Mechanism:** for each `Payment Handled` with a case, SPARQL `prov:wasInformedBy+` property paths must reach same-case Request Payment → final approval → submission milestones.
- **Valid iff** there exist same-case milestones:

```
Payment Handled
  ──wasInformedBy+──► Request Payment
                        ──wasInformedBy+──► Declaration FINAL_APPROVED by SUPERVISOR
                                             ──wasInformedBy+──► Declaration SUBMITTED by EMPLOYEE
```

- Optional intermediate steps (e.g. `PRE_APPROVER`) are allowed **between** milestones.
- **Fails when:** the nested ancestry does not exist (scrambled order, missing request/approval/submission, or cross-case links).
- **Reports:** payment IRI and case IRI.

### Validation report (`validation.json`)

| Field | Meaning |
|-------|---------|
| `status` | `PASSED` / `FAILED` (any enabled rule with violations → `FAILED`) |
| `knowledge_graph` | Path to the validated `.ttl` |
| `duration_seconds` | Total validation wall time |
| `total_violations` | Sum of per-rule counts |
| `rules_run` | Enabled rule ids |
| `results[]` | Per rule: `status`, `violation_count`, `duration_seconds`, `violations[]` |
| `violations[].issue` | Issue code (see tables above) |
| `violations[].details` | Entity bindings (activity, times, resource, …) |

## Benchmark generation

Create intentionally corrupted datasets with known ground-truth faults:

```bash
python -m src.generate_benchmark
```

Configuration is in `benchmark.ini` (separate from `config.ini`).

### How injection works

1. Load a clean XES log.
2. Apply **XES-level** control-flow corruptions for enabled **R1–R4** (order: R1 → R2 → R4 → R3; R3/R4 use disjoint traces so they do not cancel each other).
3. Convert the corrupted XES into a PROV-O KG.
4. Apply **KG-level** corruptions for enabled **R5, R5B, R6**.
5. Write outputs under a stable name: `benchmarks/bench_<rule>_<label>/`
   (or `benchmarks/bench_all_<label>/` when multiple rules are enabled).

Because R1–R4 faults live in XES, re-converting the corrupted XES preserves them.
R5–R6 faults live only in the KG file.

### Targeting (`count` / `percent`)

| Option | Meaning |
|--------|---------|
| `enabled` | `true` / `false` |
| `count` | Corrupt up to N eligible items |
| `percent` | Target = `floor(percent/100 * xes_line_count)`, capped by eligible items |

Use **either** `count` **or** `percent`, not both. Shared `seed` makes sampling reproducible.

### What each rule corrupts

| Rule | Layer | Eligible items | Corruption action |
|------|-------|----------------|-------------------|
| **R1** | XES | Traces with `Declaration SUBMITTED by EMPLOYEE` | Remove the submission event |
| **R2** | XES | Traces with final approval and `Request Payment` | Remove `Request Payment` after approval |
| **R3** | XES | Traces with both Request and Payment | Swap identity attrs (keep timestamps) so conversion order places Payment before Request |
| **R4** | XES | Traces with both Request and Payment | Remove `Payment Handled` (breaks succession without undoing R3) |
| **R5** | KG | `Payment Handled` with resource `SYSTEM` | Rewrite resource to a random invalid value |
| **R5B** | KG | `Payment Handled` whose role is not already `EMPLOYEE` | Set role to `EMPLOYEE` |
| **R6** | KG | `Payment Handled` that currently satisfy the R6 chain | Scramble order, insert a bogus stage, or remove payment `wasInformedBy` links |

**R6 corruption modes** (uniform random per payment):

1. **Scramble order** — rewire milestones into an invalid sequence.
2. **Insert bogus stage** — fake activity under payment (`dead_end` / `skip_request` / `wrong_order_via_fake`).
3. **Remove links** — delete `Payment Handled`'s `prov:wasInformedBy` edge(s).

### Example `benchmark.ini`

```ini
[benchmark]
input = dataset/DomesticDeclarations.xes.gz
output_dir = benchmarks
label = full
seed = 42

[r1]
enabled = true
count = 100

[r2]
enabled = false

# ... other rules ...
```

### Benchmark outputs

| File | Description |
|------|-------------|
| `*.corrupted.xes` | XES after enabled R1–R4 corruptions |
| `*.corrupted.prov.ttl` | KG after conversion + enabled R5–R6 corruptions |
| `statistics.json` | Requested/applied counts, eligible sizes, every corruption record |

### Evaluating a benchmark

For **R1–R4**, validate the corrupted XES with DECLARE and/or the converted KG with the KG validator. Compare on **violated cases** (injected `trace_id`), not raw row counts (the KG may emit multiple rows per case).

For **R5–R6**, point the pipeline at the **corrupted KG** with conversion off (re-converting from XES would erase those KG-only faults):

```ini
[pipeline]
output_dir = output
knowledge_graph = experiments/baseline_single_run/benchmarks/bench_r5_full/DomesticDeclarations.corrupted.prov.ttl
conversion = false
visualization = false
validation = true
```

When several rules are injected together, corruptions can create **collateral** violations of other rules. For clean per-rule ground truth, enable one rule at a time (or treat `statistics.json` applied counts as the intentional faults). Precision below 1 often reflects pre-existing faults in the clean BPI log and/or collateral effects, not missed injections (recall of injected faults is the main correctness check).

## Experiment reproduction

Paper timings and SPARQL validation results come from the **10× full-log multi-run** on shared benches
(see `experiments/README.md`). The full suite script can regenerate benches from scratch if needed.

### Recommended: reproduce paper timings (SPARQL ×10)

```powershell
. .\scripts\start_triplestore.ps1
python scripts\run_multi_run_experiment.py 10
.\scripts\stop_triplestore.ps1
```

```bash
source scripts/start_triplestore.sh
python scripts/run_multi_run_experiment.py 10
source scripts/stop_triplestore.sh
```

- Reuses `experiments/baseline_single_run/benchmarks` (seed 42, full log).
- Runs KG SPARQL validation (+ DECLARE on R1–R4) ten times; writes mean/min/max to `experiments/multi_run_n10/`.
- Progress: console + `experiments/multi_run_n10/experiment.log`.
- KG-only (skip DECLARE): add `--skip-declare`.

**Runtime:** roughly 15–20 minutes with DECLARE on a modern laptop (dominated by Turtle uploads to Fuseki).

### Optional: regenerate all benches from scratch

Requires Fuseki + `KG_SPARQL_*` (use `start_triplestore`). Regenerates isolated/combined benches for both datasets and writes under `benchmarks/` + `output/per_rule_validation/`:

```bash
python scripts/run_full_experiment_suite.py all
```

| Dataset | Input | Faults / rule | Seed |
|---------|-------|---------------|------|
| `10declarations` | `dataset/DomesticDeclarations.sample_10declarations.xes` | 5 | 42 |
| `full` | `dataset/DomesticDeclarations.xes.gz` | 100 | 42 |

Phases: `isolated` | `combined` | `all`. Full-log regeneration is dominated by XES→KG conversion (often much longer than the multi-run validation-only study).

### Where to find paper results

| Kind | Path |
|------|------|
| Multi-run report (human) | `experiments/multi_run_n10/experiment_report.md` |
| Multi-run report (machine) | `experiments/multi_run_n10/experiment_report.json` |
| Shared benches | `experiments/baseline_single_run/benchmarks/bench_*_full/` |
| Live log | `experiments/multi_run_n10/experiment.log` |

Archived python-engine multi-run: `archive/python_engine_multi_run_n10/`.  
Archived in-memory validators: `archive/python_rdflib_validation/`.

### How to verify a successful multi-run

1. Console ends with `Multi-run experiment Done` and every run `PASS`.
2. Isolated row counts match baseline (R1–R6: 235 / 134 / 107 / 110 / 100 / 100 / 109); combined total **1829**.
3. Injected-fault recall is **1.0** for every rule; isolated R1–R4 KG and DECLARE case sets match.

### Helper scripts

| Script | Purpose |
|--------|---------|
| `scripts/start_triplestore.ps1` / `.sh` | Start Fuseki + set `KG_SPARQL_*` |
| `scripts/stop_triplestore.ps1` / `.sh` | Stop Fuseki |
| `scripts/run_triplestore_validation.py` | Ping store / validate one Turtle file |
| `scripts/run_multi_run_experiment.py` | **Paper multi-run** (`[N] [--skip-declare]`) |
| `scripts/run_full_experiment_suite.py` | Regenerate suite benches (`all` / `isolated` / `combined`) |
| `scripts/run_declare_baseline_comparison.py` | Lightweight DECLARE vs KG on 10-decl R1–R4 |
| `scripts/extract_declaration_samples.py` | Extract N full declaration traces into sample XES |
| `scripts/extract_xes_samples.py` | Extract small event/trace samples for demos |
| `scripts/experiment_logging.py` | Shared progress logging + SPARQL preflight |

## Dataset

The primary dataset is BPI Challenge 2020 *Domestic Declarations* (`dataset/DomesticDeclarations.xes.gz`):

- ~10,500 cases / traces
- ~56,437 events
- ~850k RDF triples after conversion
- ~470k lines in the compressed XES source

Smaller samples under `dataset/` (e.g. `DomesticDeclarations.sample_10declarations.xes`, `DomesticDeclarations.declaration_86795.xes`) are useful for demos and paper figures.

## Project structure

```
KGBasedWorkflowValidation/
├── config.ini                      # Pipeline stages + validation rule toggles
├── benchmark.ini                   # Fault-injection settings
├── docker-compose.fuseki.yml       # Local Apache Jena Fuseki
├── dataset/                        # XES logs and samples
├── experiments/
│   ├── baseline_single_run/        # Shared benches (seed 42) + archived single-run
│   ├── multi_run_n10/              # Paper SPARQL ×10 results
│   └── README.md
├── archive/
│   ├── python_rdflib_validation/   # Old in-memory validators (unused)
│   └── python_engine_multi_run_n10/# Old python-engine ×10 timings
├── output/                         # Ad-hoc pipeline outputs
├── scripts/
│   ├── start_triplestore.ps1/.sh
│   ├── stop_triplestore.ps1/.sh
│   ├── run_multi_run_experiment.py
│   ├── run_full_experiment_suite.py
│   ├── run_triplestore_validation.py
│   └── …
├── src/
│   ├── xes_to_prov_kg.py           # Streaming XES → PROV-O conversion
│   ├── visualize_prov_kg.py        # HTML visualization
│   ├── validation_rules.py         # SPARQL rules + DECLARE model
│   ├── sparql_endpoint.py          # SPARQL / Graph Store client
│   ├── validate_kg.py              # SPARQL-only KG validation
│   ├── validate_declare_baseline.py
│   ├── generate_benchmark.py
│   ├── pipeline_config.py
│   └── run_pipeline.py
└── requirements.txt
```

## Performance notes

- Conversion streams trace-by-trace (does not keep the full XES/KG in memory while writing).
- Validation uploads Turtle to Fuseki, then runs SPARQL `SELECT`s (R1–R6).
- Full-log conversion typically takes tens to low hundreds of seconds; store load is ~10\,s per ~850k-triple graph; SPARQL queries are usually well under 1\,s per rule (R6 ~1\,s).
- DECLARE on the full log is typically ~2\,s per R1–R4 template.
- Validation cost follows rule complexity (case/label scans for R1–R4, `O(P)` for R5/R5B, `O(P · E_case)` for R6).
- Visualizing the **full** graph can be slow; prefer per-case or small-sample HTML.
