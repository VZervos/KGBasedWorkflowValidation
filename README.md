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

Outputs are written under a new run folder inside `output_dir`, named from the enabled stages/rules and a timestamp, e.g. `output/out_conv_vis_val_r1_r2_r3_20260719_120530/`.

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

## Benchmark generation

Create intentionally corrupted datasets for evaluation:

```bash
python -m src.generate_benchmark
```

Configure `benchmark.ini`:

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
percent = 5
```

Use either `count` or `percent` per rule (not both). `percent` is relative to total XES lines, then capped by eligible items.

Each run writes `benchmarks/bench_r1_r2_r3_<timestamp>/` with:

| File | Description |
|------|-------------|
| `*.corrupted.xes` | XES after R2 timestamp removals |
| `*.corrupted.prov.ttl` | KG with R1/R2/R3 faults injected |
| `statistics.json` | Requested/applied counts and every corruption record |

Notes:

- **R2** removes `time:timestamp` from XES events before conversion
- **R1** removes `wf:belongsToCase` on the KG (that link is created by conversion)
- **R3** breaks activity times on the KG while keeping `wasInformedBy` (conversion re-sorts XES times, so pure XES edits cannot create R3 violations)

## Validation

SPARQL rules live in `src/validation_rules.py` and are executed by `src/validate_kg.py`.

Currently implemented:

| Rule | Description |
|------|-------------|
| R1 | Every `prov:Activity` must have exactly one `wf:belongsToCase` |
| R2 | Every `prov:Activity` must have `prov:startedAtTime` |
| R3 | If `B prov:wasInformedBy A`, then `A.startedAtTime <= B.startedAtTime` |

The runner writes a JSON report with overall status, per-rule results, and any violating activity IRIs. If all rules pass, the report and console log both say so.

Enable or disable each rule in `config.ini` under `[validation]`.

Planned next rules: ordering constraints (submitted → approved → payment) and multi-hop payment provenance.
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
├── config.ini
├── dataset/
│   ├── DomesticDeclarations.sample.xes
│   └── DomesticDeclarations.xes.gz
├── output/
├── src/
│   ├── xes_to_prov_kg.py       # XES → PROV-O conversion (streaming)
│   ├── visualize_prov_kg.py    # HTML visualization
│   ├── validation_rules.py     # SPARQL validation rules
│   ├── validate_kg.py          # Independent validation runner
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
