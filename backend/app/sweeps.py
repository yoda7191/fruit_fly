"""Parameter sweeps: expand one request into many experiments, then aggregate.

A sweep varies one parameter over a list of values and repeats each value
with different seeds, so every point comes with a spread (mean ± SD).
"""

from __future__ import annotations

import csv
import io
import math
import statistics

from pydantic import ValidationError

from .db import ExperimentRow, SweepRow
from .schemas import ConditioningRequest, Lesion, SweepRequest

# name -> how to read it from an experiment result; display order
METRICS: dict[str, tuple[str, ...]] = {
    "performance_index": ("behavior", "performance_index"),
    "cs_plus_change": ("compartment_change", "cs_plus"),
    "cs_minus_change": ("compartment_change", "cs_minus"),
    "kc_active_plus": ("separation", "kc_active_plus"),
    "kc_correlation": ("separation", "kc_correlation"),
    "pn_correlation": ("separation", "pn_correlation"),
    "mean_weight_ratio": ("mean_weight_ratio",),
    "mbon_discrimination": ("population_stats", "mbon_discrimination"),
    "learned_drive": ("behavior", "learned_drive"),
    "weight_floor_frac": ("weight_stats", "floor_fraction"),
}


def parse_lesion(label: str) -> Lesion | None:
    """ "none" -> None (intact control), "group:APL" / "type:MBON01" -> a Lesion."""
    if label == "none":
        return None
    kind, _, name = label.partition(":")
    return Lesion(group=name) if kind == "group" else Lesion(cell_type=name)


def member_value(row: ExperimentRow) -> float | str | None:
    """The sweep value an experiment ran with (labels for lesion scans)."""
    return row.sweep_label if row.sweep_label is not None else row.sweep_value


def with_parameter(base: ConditioningRequest, parameter: str, value: float | str,
                   seed: int) -> ConditioningRequest:
    """A copy of `base` with one (dotted) parameter set, validated like any request.
    For a lesion scan, the value's lesion is added to the base request's lesions."""
    data = base.model_dump(mode="json")
    data["seed"] = seed
    if parameter == "lesion":
        lesion = parse_lesion(str(value))
        if lesion is not None:
            data["lesions"] = [*data.get("lesions", []), lesion.model_dump(mode="json")]
        return ConditioningRequest.model_validate(data)
    if parameter == "trials":
        if not float(value).is_integer():
            raise ValueError(f"trials must be whole numbers, got {value}")
        value = int(value)
    target = data
    *path, last = parameter.split(".")
    for key in path:
        target = target.setdefault(key, {})
    target[last] = value
    return ConditioningRequest.model_validate(data)


def expand(sweep: SweepRequest) -> list[tuple[float | str, ConditioningRequest]]:
    """One (value, request) per experiment. Raises ValueError with a readable message."""
    if len(set(sweep.values)) != len(sweep.values):
        raise ValueError("sweep values must be unique")
    members = []
    for value in sweep.values:
        for k in range(sweep.repeats):
            try:
                members.append((value, with_parameter(sweep.base, sweep.parameter, value,
                                                      sweep.base.seed + k)))
            except ValidationError as e:
                problem = e.errors()[0]
                raise ValueError(f"{sweep.parameter}={value}: {problem['msg']}") from None
    return members


def metric_values(result: dict | None) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for name, path in METRICS.items():
        v: object = result
        for key in path:
            v = v.get(key) if isinstance(v, dict) else None
        out[name] = float(v) if isinstance(v, (int, float)) and math.isfinite(v) else None
    return out


def _stats(values: list[float]) -> dict:
    if not values:
        return {"mean": None, "std": None, "n": 0}
    return {"mean": statistics.fmean(values),
            "std": statistics.stdev(values) if len(values) > 1 else None,
            "n": len(values)}


def count_statuses(members: list[ExperimentRow]) -> dict[str, int]:
    counts = {"queued": 0, "running": 0, "done": 0, "failed": 0, "cancelled": 0}
    for m in members:
        counts[m.status] = counts.get(m.status, 0) + 1
    return counts


def summarize(sweep: SweepRow, counts: dict[str, int]) -> dict:
    """Status: "running" while anything is pending; "failed" or "cancelled" only
    if nothing succeeded (a few failed or cancelled runs still leave usable
    averages; counts show them)."""
    if counts.get("queued") or counts.get("running"):
        status = "running"
    elif counts.get("done"):
        status = "done"
    else:
        status = "cancelled" if counts.get("cancelled") and not counts.get("failed") else "failed"
    return {"id": sweep.id, "created_at": sweep.created_at, "parameter": sweep.parameter,
            "values": sweep.values, "repeats": sweep.repeats, "total": sum(counts.values()),
            "counts": counts, "status": status, "base": sweep.base_request}


def detail(sweep: SweepRow, members: list[ExperimentRow]) -> dict:
    points = []
    for value in sweep.values:
        done = [m for m in members if member_value(m) == value and m.status == "done"]
        per_metric: dict[str, list[float]] = {name: [] for name in METRICS}
        for m in done:
            for name, v in metric_values(m.result).items():
                if v is not None:
                    per_metric[name].append(v)
        points.append({"value": value, "done": len(done),
                       "metrics": {name: _stats(vals) for name, vals in per_metric.items()}})
    return {**summarize(sweep, count_statuses(members)), "metrics": list(METRICS), "points": points}


def results_csv(sweep: SweepRow, members: list[ExperimentRow]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["experiment_id", sweep.parameter, "seed", "status", *METRICS, "error"])
    for m in sorted(members, key=lambda m: (sweep.values.index(member_value(m))
                                            if member_value(m) in sweep.values else 0,
                                            m.request.get("seed", 0))):
        vals = metric_values(m.result)
        w.writerow([m.id, member_value(m), m.request.get("seed"), m.status,
                    *("" if vals[k] is None else f"{vals[k]:.6g}" for k in METRICS),
                    m.error or ""])
    return buf.getvalue()