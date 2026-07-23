"""PM4Py DECLARE baseline aligned with KG rules R1–R4.

Uses the canonical DECLARE model in ``validation_rules.DECLARE_MODEL_R1_R4``
(existence, response, precedence, succession).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pm4py

from src.validation_rules import DECLARE_MODEL_R1_R4


@dataclass(frozen=True)
class LogViolation:
    issue: str
    details: dict[str, str]


@dataclass(frozen=True)
class BaselineRuleResult:
    rule_id: str
    method: str
    status: str
    violation_count: int
    duration_seconds: float
    note: str
    violations: tuple[LogViolation, ...]
    extra: dict[str, Any]


def declare_model_for_rule(rule_id: str) -> dict[str, dict]:
    """Slice DECLARE_MODEL_R1_R4 to the single template used by that rule."""
    mapping = {
        "R1": "existence",
        "R2": "response",
        "R3": "precedence",
        "R4": "succession",
    }
    template = mapping[rule_id]
    return {template: dict(DECLARE_MODEL_R1_R4[template])}


def load_xes(path: Path) -> pd.DataFrame:
    return pm4py.read_xes(str(path))


def run_declare_conformance(
    log: pd.DataFrame,
    declare_model: dict[str, dict] | None = None,
) -> BaselineRuleResult:
    model = declare_model if declare_model is not None else DECLARE_MODEL_R1_R4
    started = time.perf_counter()
    if "time:timestamp" in log.columns and log["time:timestamp"].isna().any():
        duration = round(time.perf_counter() - started, 6)
        missing = int(log["time:timestamp"].isna().sum())
        return BaselineRuleResult(
            rule_id="DECLARE",
            method="pm4py.conformance_declare",
            status="NOT_APPLICABLE",
            violation_count=0,
            duration_seconds=duration,
            note=(
                f"PM4Py DECLARE requires complete timestamps ({missing} missing)."
            ),
            violations=(),
            extra={"skipped_reason": "missing_timestamps"},
        )

    conf = pm4py.conformance_declare(log, model, return_diagnostics_dataframe=False)
    duration = round(time.perf_counter() - started, 6)

    violations: list[LogViolation] = []
    unfit = 0
    total_devs = 0
    for row in conf:
        case_id = str(row.get("case_id", ""))
        is_fit = bool(row.get("is_fit", True))
        n_dev = int(row.get("no_dev_total", 0) or 0)
        total_devs += n_dev
        if not is_fit:
            unfit += 1
        for dev in row.get("deviations") or []:
            if isinstance(dev, dict):
                issue = str(dev.get("type") or dev.get("constraint") or "declare_deviation")
                details = {str(k): str(v) for k, v in dev.items()}
            elif isinstance(dev, (list, tuple)) and len(dev) >= 2:
                issue = str(dev[0])
                details = {"constraint": str(dev[1]), "case": case_id}
            else:
                issue = "declare_deviation"
                details = {"raw": str(dev), "case": case_id}
            if case_id and "case" not in details:
                details["case"] = case_id
            violations.append(LogViolation(issue=issue, details=details))

    n_constraints = sum(len(bucket) for bucket in model.values())
    return BaselineRuleResult(
        rule_id="DECLARE",
        method="pm4py.conformance_declare",
        status="PASSED" if total_devs == 0 else "FAILED",
        violation_count=total_devs,
        duration_seconds=duration,
        note=(
            "Control-flow conformance against DECLARE_MODEL_R1_R4 "
            f"({sorted(model)}, {n_constraints} constraints)."
        ),
        violations=tuple(violations),
        extra={
            "unfit_traces": unfit,
            "trace_count": len(conf),
            "constraint_count": n_constraints,
            "templates": sorted(model),
            "mean_dev_fitness": round(
                sum(float(r.get("dev_fitness", 1.0) or 1.0) for r in conf)
                / max(len(conf), 1),
                6,
            ),
        },
    )


def result_to_dict(result: BaselineRuleResult) -> dict[str, Any]:
    return asdict(result)
