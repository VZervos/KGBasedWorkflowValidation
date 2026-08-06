"""Smoke-test / one-shot validation against a SPARQL triple store.

Examples:
  # Start Fuseki + env (PowerShell): . .\\scripts\\start_triplestore.ps1
  # Start Fuseki + env (bash):       source scripts/start_triplestore.sh

  # Ping the store:
  python scripts/run_triplestore_validation.py --ping

  # Validate one Turtle file with pure SPARQL (all enabled rules in the file's suite):
  python scripts/run_triplestore_validation.py path/to/graph.prov.ttl

  # Single rule:
  python scripts/run_triplestore_validation.py path/to/graph.prov.ttl --rule R1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sparql_endpoint import SparqlEndpoint, suggest_fuseki_env
from src.validate_kg import log_validation_summary, validate_ttl
from src.validation_rules import VALIDATION_RULES


def _apply_fuseki_defaults() -> None:
    defaults = suggest_fuseki_env()
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ttl", nargs="?", type=Path, help="Turtle KG to load and validate")
    parser.add_argument("--rule", action="append", default=[], help="Rule id (repeatable), default: all")
    parser.add_argument("--ping", action="store_true", help="Only check store connectivity")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Validation JSON path (default: output/triplestore_validation/validation.json)",
    )
    args = parser.parse_args()

    _apply_fuseki_defaults()

    endpoint = SparqlEndpoint()
    if args.ping:
        info = endpoint.ping()
        print(json.dumps(info, indent=2))
        return

    if args.ttl is None:
        parser.error("ttl path is required unless --ping is set")

    rule_ids = {r.upper() for r in args.rule} if args.rule else None
    rules = (
        tuple(r for r in VALIDATION_RULES if r.rule_id in rule_ids)
        if rule_ids
        else VALIDATION_RULES
    )
    if not rules:
        raise SystemExit(f"No matching rules for {sorted(rule_ids or [])}")

    report_path = args.report or (
        ROOT / "output" / "triplestore_validation" / "validation.json"
    )
    report, load_seconds = validate_ttl(
        args.ttl,
        report_path=report_path,
        rules=rules,
        sparql_endpoint=endpoint,
    )
    print(f"Store load (CLEAR+upload): {load_seconds:.4f}s")
    log_validation_summary(report)


if __name__ == "__main__":
    main()
