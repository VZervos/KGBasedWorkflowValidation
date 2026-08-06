"""Shared progress logging + SPARQL preflight for experiment scripts."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


class TeeStdout:
    """Mirror stdout to a log file (line-buffered)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("a", encoding="utf-8")
        self._out = sys.stdout

    def write(self, s: str) -> int:
        self._out.write(s)
        self._file.write(s)
        self._file.flush()
        return len(s)

    def flush(self) -> None:
        self._out.flush()
        self._file.flush()

    def isatty(self) -> bool:
        return getattr(self._out, "isatty", lambda: False)()

    def close(self) -> None:
        self._file.close()


def preflight_sparql(*, label: str = "experiment") -> dict:
    """Fail fast if KG_SPARQL_* is unset or the store is unreachable."""
    from src.sparql_endpoint import SparqlEndpoint, SparqlEndpointError

    try:
        info = SparqlEndpoint().ping()
    except SparqlEndpointError as exc:
        raise SystemExit(
            f"SPARQL preflight failed for {label}: {exc}\n"
            "Start the store and set env vars:\n"
            "  PowerShell:  . .\\scripts\\start_triplestore.ps1\n"
            "  bash:        source scripts/start_triplestore.sh"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — surface any client/network error
        raise SystemExit(
            f"SPARQL preflight failed for {label}: {exc}\n"
            "Start the store and set env vars:\n"
            "  PowerShell:  . .\\scripts\\start_triplestore.ps1\n"
            "  bash:        source scripts/start_triplestore.sh"
        ) from exc

    log(
        f"SPARQL OK query={info['query_endpoint']} "
        f"triples_in_store={info['triple_count']}"
    )
    return info


def fmt_eta(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    if seconds < 90:
        return f"{seconds:.0f}s"
    mins = seconds / 60.0
    if mins < 90:
        return f"{mins:.1f} min"
    return f"{mins / 60.0:.1f} h"
