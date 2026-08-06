# Experiments

| Folder | Description |
|--------|-------------|
| `baseline_single_run/` | Shared full-log benches (seed 42) + archived single-run outputs |
| `multi_run_n10/` | Paper **SPARQL** ×10 study (KG + DECLARE means / min / max) |

Archived python-engine ×10 results: `archive/python_engine_multi_run_n10/`  
Archived in-memory validators: `archive/python_rdflib_validation/`

## Reproduce the 10× full-log study

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

- Reuses `baseline_single_run/benchmarks`
- Validates ×10 via SPARQL on Fuseki (+ DECLARE on R1–R4)
- Writes `multi_run_n10/experiment_report.md` / `.json` and `experiment.log`
- KG-only: `python scripts/run_multi_run_experiment.py 10 --skip-declare`

Typical wall time: ~15–20 minutes with DECLARE.
