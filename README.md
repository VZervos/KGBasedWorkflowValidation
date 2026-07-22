# KG-Based Workflow Validation

Convert XES event logs into a PROV-O provenance knowledge graph, visualize it, and validate it with SPARQL rules.

## Workflow

| Step | Description | Pipeline stage |
|------|-------------|----------------|
| 1 | Workflow model / event logs | `input` |
| 2 | Extraction of entities and relations | `conversion` |
| 3 | Triples | `conversion` |
| 4 | Knowledge graph | `output` |
| 5 | SPARQL validation rules | `validation` |

Optional: `visualization` produces an interactive HTML graph.

## Requirements

- Python 3.11+
- Dependencies in `requirements.txt`

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS

pip install -r requirements.txt
```

## Quick start

Run the pipeline with one command:

```bash
python -m src.run_pipeline
```

By default, enable the steps you want with `true`/`false` flags in `config.ini`.

Outputs are written under a new run folder inside `output_dir`, named from the enabled stages/rules and a timestamp, e.g. `output/out_conv_vis_val_r1_r2_r3_r4_r5_r5b_r6_20260719_120530/`.

## Configuration

All settings are in `config.ini`:

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
| `validation` | `true`/`false` — run SPARQL validation rules |

Under `[validation]`, each rule is toggled independently (`R1 = true`, etc.). When `validation = true`, at least one rule must be enabled.

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
knowledge_graph = output/out_conv_.../file.prov.ttl
conversion = false
visualization = false
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

**Visualize an existing KG**

```ini
output_dir = output
knowledge_graph = output/out_conv_.../file.prov.ttl
conversion = false
visualization = true
validation = false
```

## Running individual steps

Each step reads `config.ini` and creates its own run folder:

```bash
python -m src.xes_to_prov_kg
python -m src.visualize_prov_kg
python -m src.validate_kg
```

Validation is independent of conversion: when `conversion = false`, point `knowledge_graph` at an existing `.ttl` file.

## Validation

SPARQL rules live in `src/validation_rules.py` and are executed by `src/validate_kg.py`.

The runner writes a JSON report (`validation.json`) with overall status, per-rule results, timings, and violating activity IRIs / details. If all enabled rules pass, the report and console log both say so.

Enable or disable each rule in `config.ini` under `[validation]`.

### Rules

Activity labels and roles below match the BPI Challenge 2020 *Domestic Declarations* log.

| Rule | Name | What it checks | Violation issue |
|------|------|----------------|-----------------|
| **R1** | `ACTIVITY_BELONGS_TO_CASE` | Every `prov:Activity` must have **exactly one** `wf:belongsToCase` | `missing_belongsToCase` or `multiple_belongsToCase` |
| **R2** | `ACTIVITY_HAS_STARTED_AT_TIME` | Every `prov:Activity` must have `prov:startedAtTime` | `missing_startedAtTime` |
| **R3** | `ACTIVITY_HAS_AGENT` | Every `prov:Activity` must have `prov:wasAssociatedWith` an agent | `missing_agent_association` |
| **R4** | `WAS_INFORMED_BY_TEMPORAL_CONSISTENCY` | On every `wasInformedBy` edge, both activities must have `prov:startedAtTime`, and `A.startedAtTime ≤ B.startedAtTime` | `non_monotonic_wasInformedBy`, `missing_startedAtTime_on_informed_activity`, or `missing_startedAtTime_on_informing_activity` |
| **R5** | `PAYMENT_HANDLED_BY_SYSTEM` | Every activity labelled `Payment Handled` must have `attr:xes-attr_org_resource = "SYSTEM"` | `payment_not_handled_by_system` |
| **R5B** | `PAYMENT_HANDLED_NOT_BY_EMPLOYEE` | Every activity labelled `Payment Handled` must **not** have `attr:xes-attr_org_role = "EMPLOYEE"` | `payment_handled_by_employee` |
| **R6** | `PAYMENT_PROVENANCE_CHAIN` | A payment is valid only if `Payment Handled` reaches `Request Payment` → `Declaration FINAL_APPROVED by SUPERVISOR` → `Declaration SUBMITTED by EMPLOYEE` via `prov:wasInformedBy+`, and **all belong to the same case** | `invalid_payment_provenance_chain` |

#### R4 detail

Reports every `wasInformedBy` edge where:

- the later activity’s start time is **strictly earlier** than the earlier activity’s start time, or
- either endpoint is missing `prov:startedAtTime` (end time may still be present).

#### R5 / R5B detail

These are complementary agent/resource checks on `Payment Handled` only:

- **R5** requires the handler resource to be `SYSTEM` (as in the real Domestic Declarations log).
- **R5B** forbids role `EMPLOYEE` (negative counterpart).

#### R6 detail

Uses **transitive** `prov:wasInformedBy+`, so optional intermediate steps (e.g. `Declaration APPROVED by PRE_APPROVER`) are allowed **between** the required milestones, as long as the ordered ancestry exists within one case:

```
Payment Handled
  ──wasInformedBy+──► Request Payment
                        ──wasInformedBy+──► Final Approval
                                             ──wasInformedBy+──► Submission
```

A scrambled chain such as `Payment Handled → Final Approval → Request Payment → Submission` fails, because `Request Payment` is not an ancestor of itself on the required nested path.

On large graphs, R6 is evaluated with an equivalent in-memory BFS (same semantics as the SPARQL rule) because RDFLib property paths are too slow at full-dataset scale.

## Benchmark generation

Create intentionally corrupted datasets with known ground-truth faults for evaluation:

```bash
python -m src.generate_benchmark
```

Configuration is in `benchmark.ini` (separate from `config.ini`).

### How injection works

1. Load a clean XES log.
2. Apply **XES-level** corruptions that must happen before conversion (**R2** only).
3. Convert the (possibly R2-corrupted) XES into a PROV-O KG.
4. Apply **KG-level** corruptions on the Turtle graph (**R1, R3, R5, R5B, R6, then R4**).
   R4 runs last so temporal breaks remain on the final `wasInformedBy` topology after R6 rewiring.
5. Write outputs under a stable folder name: `benchmarks/bench_<rule>_<label>/`
   (or `benchmarks/bench_all_<label>/` when multiple rules are enabled).
   Set optional `label` in `[benchmark]` (defaults to the `output_dir` folder name),
   e.g. `label = full` → `bench_r1_full`.

Some PROV links (`wf:belongsToCase`, `prov:wasAssociatedWith`, `prov:wasInformedBy`) are created during conversion, so those faults cannot be injected meaningfully in raw XES alone — conversion would recreate or reorder them. That is why R1/R3/R4/R5/R5B/R6 edit the generated KG.

### Targeting (`count` / `percent`)

For each `[rN]` section:

| Option | Meaning |
|--------|---------|
| `enabled` | `true` / `false` |
| `count` | Corrupt up to N eligible items (or all eligible if fewer) |
| `percent` | Target = `floor(percent/100 * xes_line_count)`, then capped by eligible items |

Use **either** `count` **or** `percent`, not both. If fewer eligible items exist than requested, all eligible items are corrupted. A shared `seed` makes sampling reproducible.

### What each rule corrupts

| Rule | Layer | Eligible items | Corruption action |
|------|-------|----------------|-------------------|
| **R1** | KG | Activities that have ≥1 `wf:belongsToCase` | Remove all `wf:belongsToCase` links |
| **R2** | XES | Events that have `time:timestamp` | Remove timestamp attribute(s); after conversion, activities lack `prov:startedAtTime` |
| **R3** | KG | Activities that have `prov:wasAssociatedWith` | Remove agent association(s) |
| **R4** | KG | `wasInformedBy` edges whose later activity has `startedAtTime` | Break temporal order (`later.startedAtTime < earlier`) |
| **R5** | KG | `Payment Handled` with resource `SYSTEM` | Rewrite `attr:xes-attr_org_resource` to a random invalid value (known roles, empty, or invented `BOGUS_RESOURCE_*`) |
| **R5B** | KG | `Payment Handled` whose role is not already `EMPLOYEE` | Rewrite `attr:xes-attr_org_role` to `EMPLOYEE` |
| **R6** | KG | `Payment Handled` activities that currently satisfy the R6 chain | Randomly scramble order, insert a bogus stage, or remove `wasInformedBy` links (see below) |

**R6 corruption modes** (chosen uniformly at random per payment):

1. **Scramble order** — clear milestone `wasInformedBy` edges and rewire into an invalid sequence, e.g. `Payment Handled → Submission → Approval → Request Payment`.
2. **Insert bogus stage** — create a fake activity in the same case and attach it under `Payment Handled`, using one of:
   - `dead_end`: payment → fake only (no further links)
   - `skip_request`: payment → fake → final approval (skips Request Payment)
   - `wrong_order_via_fake`: payment → fake → submission → approval
3. **Remove links** — delete `Payment Handled`'s `prov:wasInformedBy` edge(s), leaving the payment with no provenance predecessor.

### Example `benchmark.ini`

```ini
[benchmark]
input = dataset/DomesticDeclarations.sample_5declarations.xes
output_dir = benchmarks
seed = 42

[r1]
enabled = true
count = 3

[r2]
enabled = true
count = 2

[r3]
enabled = true
count = 2

[r4]
enabled = true
percent = 5

[r5]
enabled = true
count = 2

[r5b]
enabled = true
count = 2

[r6]
enabled = true
count = 2
```

### Benchmark outputs

| File | Description |
|------|-------------|
| `*.corrupted.xes` | XES after R2 (and unchanged otherwise) |
| `*.corrupted.prov.ttl` | KG after conversion + all enabled KG corruptions |
| `statistics.json` | Requested/applied counts, eligible sizes, and every corruption record (rule, action, before/after details) |

### Evaluating a benchmark

Point the pipeline at the **corrupted KG** with conversion off, otherwise re-conversion from the corrupted XES would rebuild a clean graph and erase R1/R3/R4/R5/R5B/R6 faults:

```ini
[pipeline]
output_dir = output
knowledge_graph = benchmarks/bench_r1_full/DomesticDeclarations.corrupted.prov.ttl
conversion = false
visualization = false
validation = true
```

Note: when several rules are enabled together, earlier KG corruptions can create **collateral** violations of later rules (e.g. R1 removing `belongsToCase` on a mid-chain activity also breaks R6). For clean per-rule ground truth, enable one rule section at a time (or interpret `statistics.json` applied counts as intentional faults).

## XES mapping

Conversion uses **XES-standard defaults** discovered from each file:

- Reads declared `<extension>` entries from the XES header
- Infers attribute types from XML tags (`string`, `date`, `float`, …)
- Resolves identity from primary XES keys (`id`, `concept:name`, `time:timestamp`, `org:resource`, `org:role`)
- Does not invent defaults for missing fields; warns on the console and leaves gaps for validation
- Maps standard keys to PROV-O (`concept:name`, `time:timestamp`, `org:resource`, `org:role`)

Domain attributes such as `Amount` and `BudgetNumber` are copied automatically from the XES file.

## Visualization

The visualization stage writes an interactive HTML file using pyvis. Open it in a browser:

```
output/DomesticDeclarations.sample.prov.html
```

- Blue boxes: `prov:Entity`
- Red ellipses: `prov:Activity`
- Green dots: `prov:Agent`

An internet connection is required when viewing the HTML (vis-network is loaded from a CDN).

## Project structure

```
KGBasedWorkflowValidation/
├── config.ini                  # Pipeline stages + validation rule toggles
├── benchmark.ini               # Fault-injection settings for benchmarks
├── dataset/
│   ├── DomesticDeclarations.sample*.xes
│   └── DomesticDeclarations.xes.gz
├── benchmarks/                 # Generated corrupted datasets
├── output/                     # Pipeline run folders
├── src/
│   ├── xes_to_prov_kg.py       # XES → PROV-O conversion (streaming)
│   ├── visualize_prov_kg.py    # HTML visualization
│   ├── validation_rules.py     # SPARQL validation rules
│   ├── validate_kg.py          # Independent validation runner
│   ├── generate_benchmark.py   # Intentional fault injection
│   ├── pipeline_config.py
│   └── run_pipeline.py         # Main pipeline runner
└── requirements.txt
```

## PROV-O mapping

| XES element | PROV-O node |
|-------------|-------------|
| Trace (case) | `prov:Entity` |
| Event | `prov:Activity` |
| `org:resource` + `org:role` | `prov:Agent` |

Relations:

- `prov:wasAssociatedWith` — activity performed by agent
- `prov:used` — every activity uses the case entity (the business object)
- `prov:wasInformedBy` — control-flow ordering within a case
- `prov:wasGeneratedBy` — the case is generated by the first activity in the trace
- `wf:belongsToCase` — links activities to their case

Design choices:

- **Activities only** — events are modeled as activities, not as separate event entities. This keeps the graph smaller while preserving workflow semantics.
- **Case-centric `prov:used`** — activities depend on the declaration (case), not on the previous event record. Ordering is captured exclusively by `prov:wasInformedBy`.
- **Full XES attribute preservation** — every XES attribute on traces and events is copied to `attr:xes-attr_*` predicates, including custom domain fields. Standard keys (`time:timestamp`, `org:resource`, etc.) are additionally mapped to PROV-O relations.
- **Explicit event ids** — the resolved event id is stored as `attr:xes-attr_id` on each activity, not only in the activity URI.
- **Readable XES attributes** — XES keys are stored as `attr:xes-attr_<key>` predicates with colons and semicolons replaced by underscores (e.g. `time:timestamp` → `attr:xes-attr_time_timestamp`).
- **Agent identity** — agent URIs are based on `org:resource` only. Missing resource/role values are not replaced with defaults; construction warns and omits incomplete associations so validation can detect them.

Case attributes (`Amount`, `BudgetNumber`, `DeclarationNumber`, etc.) stay on the case entity.

## Performance notes

- The **sample** dataset is small and suitable for demos.
- The **full** dataset contains ~10,500 traces and ~955k triples.
- Conversion streams trace-by-trace, so it does not load the whole XES log or full KG into memory.
- Visualization loads the serialized KG from disk and can take several minutes on large graphs.

## Outputs

Each pipeline run writes into `output/out_<stages>_<rules>_<timestamp>/`:

| File | Description |
|------|-------------|
| `*.prov.ttl` | PROV-O knowledge graph |
| `*.prov.html` | Interactive visualization |
| `validation.json` | SPARQL validation report |
| `statistics.json` | Run statistics (lines, traces/events/triples, stage/rule timings, violations) |
