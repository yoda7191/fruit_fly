"""Conditioning experiments: submit, follow, cancel, fetch spikes, export, delete."""

import csv
import io
import json

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from ..db import ExperimentRow
from ..deps import canonical_request, charge, check_owner, get_jobs, get_store, writer
from ..events import stream_changes
from ..jobs import BadCursor, CapacityError, JobService, QueueUnavailable
from ..logs import request_id
from ..model import ModelStore
from ..schemas import (CancelResult, ConditioningRequest, ExperimentDetail, ExperimentPage,
                       ExperimentSummary, NeuronActivity, SpikeWindow)

router = APIRouter(prefix="/api/experiments", tags=["experiments"])

SSE_RESPONSE = {200: {"content": {"text/event-stream": {}},
                      "description": "`update` events (JSON), then `end` or `gone`"}}


def summary(row: ExperimentRow) -> dict:
    progress = ({"done": row.progress_done, "total": row.progress_total}
                if row.progress_total else None)
    return {"id": row.id, "sweep_id": row.sweep_id, "status": row.status, "progress": progress,
            "created_at": row.created_at, "started_at": row.started_at,
            "finished_at": row.finished_at, "request": row.request, "error": row.error}


def _get(jobs: JobService, experiment_id: str) -> ExperimentRow:
    row = jobs.get(experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no experiment '{experiment_id}'")
    return row


def _done(jobs: JobService, experiment_id: str) -> ExperimentRow:
    row = _get(jobs, experiment_id)
    if row.status != "done":
        raise HTTPException(status_code=409, detail=f"experiment is {row.status}")
    return row


def _with_spikes(jobs: JobService, experiment_id: str) -> ExperimentRow:
    row = _done(jobs, experiment_id)
    if not row.store_spikes or not jobs.spikes.exists(row.id):
        raise HTTPException(status_code=409, detail="spikes were not stored for this experiment")
    return row


def _attachment(name: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{name}"'}


@router.post("/conditioning", response_model=ExperimentSummary, status_code=202,
             responses={200: {"description": "an identical experiment already exists; it is returned"}})
def submit_conditioning(req: ConditioningRequest, request: Request, response: Response,
                        reuse: bool = Query(True, description="return a stored identical experiment "
                                                              "instead of running it again"),
                        store: ModelStore = Depends(get_store),
                        jobs: JobService = Depends(get_jobs),
                        client: str = Depends(writer)):
    """Start differential conditioning in the background, then follow it with
    GET /api/experiments/{id}/events (or poll GET /api/experiments/{id}).

    The simulator is deterministic, so a request identical to a stored one
    (same settings and seed, same model) returns that experiment with status
    200 instead of 202, without running or charging anything. This also makes
    retrying a submission safe. Change the seed for an independent repeat."""
    req = canonical_request(store, req)
    key = store.request_key(req)
    if reuse and (existing := jobs.find_reusable(key)) is not None:
        request.app.state.metrics.submitted.labels("reused").inc()
        response.status_code = 200
        return summary(existing)
    charge(request, client, 1)                 # after validation: rejected requests are free
    try:
        row = jobs.submit(req, request_key=key, request_id=request_id.get(), owner=client)
    except CapacityError as e:
        request.app.state.metrics.refused.labels("capacity").inc()
        raise HTTPException(status_code=429, detail=str(e)) from None
    except QueueUnavailable as e:
        request.app.state.metrics.refused.labels("queue_unavailable").inc()
        raise HTTPException(status_code=503, detail=str(e)) from None
    request.app.state.metrics.submitted.labels("single").inc()
    return summary(row)


@router.get("", response_model=ExperimentPage)
def list_experiments(include_sweeps: bool = Query(False, description="also list sweep members"),
                     limit: int = Query(50, ge=1, le=500),
                     cursor: str | None = Query(None, description="next_cursor of the previous page"),
                     jobs: JobService = Depends(get_jobs)):
    """Stored experiments, newest first, one page at a time."""
    try:
        rows, next_cursor = jobs.list(include_sweeps=include_sweeps, limit=limit, cursor=cursor)
    except BadCursor as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return {"items": [summary(r) for r in rows], "next_cursor": next_cursor}


@router.get("/{experiment_id}", response_model=ExperimentDetail)
def get_experiment(experiment_id: str, jobs: JobService = Depends(get_jobs)):
    row = _get(jobs, experiment_id)
    return {**summary(row), "result": row.result if row.status == "done" else None}


@router.get("/{experiment_id}/events", response_class=StreamingResponse, responses=SSE_RESPONSE)
async def experiment_events(experiment_id: str, request: Request, jobs: JobService = Depends(get_jobs)):
    """Live status and progress as server-sent events: an `update` (the
    experiment summary, as from GET /api/experiments) whenever it changes,
    then `end` when it has finished. Fetch the result with GET afterwards."""
    from starlette.concurrency import run_in_threadpool
    if await run_in_threadpool(jobs.get, experiment_id) is None:
        raise HTTPException(status_code=404, detail=f"no experiment '{experiment_id}'")

    def read():
        row = jobs.get(experiment_id)
        if row is None:
            return None
        return ExperimentSummary.model_validate(summary(row)).model_dump_json(), row.finished

    return StreamingResponse(stream_changes(request, request.app.state.events, experiment_id, read),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{experiment_id}/cancel", response_model=CancelResult)
def cancel_experiment(experiment_id: str, request: Request, jobs: JobService = Depends(get_jobs),
                      client: str = Depends(writer)):
    """Stop a queued or running experiment. A queued one is cancelled at once;
    a running one stops after its current odour presentation (status stays
    "running" until then). 409 if it had already finished. On a server that
    doesn't require API keys, only whoever submitted it may cancel it."""
    check_owner(request, client, _get(jobs, experiment_id).owner)
    status = jobs.cancel(experiment_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"no experiment '{experiment_id}'")
    if status in ("done", "failed"):
        raise HTTPException(status_code=409, detail=f"experiment already {status}")
    return {"status": status}


@router.get("/{experiment_id}/neurons/{index}", response_model=NeuronActivity)
def neuron_activity(experiment_id: str, index: int,
                    store: ModelStore = Depends(get_store),
                    jobs: JobService = Depends(get_jobs)):
    """One neuron's spike count and rate in every presentation of an experiment."""
    if not 0 <= index < len(store.network):
        raise HTTPException(status_code=404, detail=f"no neuron {index}")
    row = _with_spikes(jobs, experiment_id)
    timeline = row.result["timeline"]
    end = max((e["t_end_ms"] for e in timeline), default=0.0) + 1.0
    mask = np.zeros(len(store.network), bool)
    mask[index] = True
    _, times, _ = jobs.spikes.window(row.id, 0.0, end, mask, 10_000_000)
    out = []
    for e in timeline:
        n = int(np.count_nonzero((times >= e["t_start_ms"]) & (times < e["t_end_ms"])))
        dur = (e["t_end_ms"] - e["t_start_ms"]) / 1000.0
        out.append({"label": e["label"], "phase": e["phase"], "us": e["us"], "t_start_ms": e["t_start_ms"],
                    "t_end_ms": e["t_end_ms"], "spikes": n, "rate_hz": n / dur if dur > 0 else 0.0})
    return {"index": index, "total_spikes": int(len(times)), "presentations": out}


def _group_mask(store: ModelStore, group: list[str] | None) -> np.ndarray | None:
    if not group:
        return None
    unknown = sorted(set(group) - set(store.group_counts))
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown group(s): {unknown}")
    return np.isin(store.group, group)


@router.get("/{experiment_id}/spikes", response_model=SpikeWindow)
def get_spikes(experiment_id: str,
               t0_ms: float = Query(0.0, ge=0.0),
               t1_ms: float = Query(1000.0, gt=0.0),
               group: list[str] | None = Query(None, description="repeat to select several"),
               max_spikes: int = Query(200_000, ge=1, le=2_000_000),
               store: ModelStore = Depends(get_store),
               jobs: JobService = Depends(get_jobs)):
    """Recorded spikes in a time window, for playback in the 3D viewer."""
    if t1_ms <= t0_ms:
        raise HTTPException(status_code=422, detail="t1_ms must be greater than t0_ms")
    row = _with_spikes(jobs, experiment_id)
    mask = _group_mask(store, group)
    neurons, times, truncated = jobs.spikes.window(row.id, t0_ms, t1_ms, mask, max_spikes)
    return {"t0_ms": t0_ms, "t1_ms": t1_ms, "count": int(len(neurons)),
            "truncated": truncated, "neurons": neurons.tolist(),
            "times_ms": [round(float(t), 2) for t in times]}


# ---------------------------------------------------------------- exports

@router.get("/{experiment_id}/export.json", response_model=ExperimentDetail,
            responses={200: {"content": {"application/json": {}}}})
def export_json(experiment_id: str, store: ModelStore = Depends(get_store),
                jobs: JobService = Depends(get_jobs)):
    """The request and full result as a file, plus the fingerprint of the model
    that produced it (identical fingerprint + request = identical result)."""
    row = _done(jobs, experiment_id)
    body = ExperimentDetail.model_validate({**summary(row), "result": row.result}).model_dump(mode="json")
    body["model_fingerprint"] = store.fingerprint
    return Response(json.dumps(body, indent=1), media_type="application/json",
                    headers=_attachment(f"experiment-{experiment_id}.json"))


@router.get("/{experiment_id}/mbons.csv", response_class=Response,
            responses={200: {"content": {"text/csv": {}}}})
def export_mbons(experiment_id: str, jobs: JobService = Depends(get_jobs)):
    """One row per output-neuron type: evoked spikes to CS+ and CS− before and
    after training, and the mean KC→MBON weight afterwards (fraction of initial)."""
    row = _done(jobs, experiment_id)
    weights: dict[str, list[float]] = {}
    for w in row.result["mbon_weights"]:
        weights.setdefault(w["cell_type"], []).append(w["weight_ratio"])
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(["cell_type", "neurons", "us_target", "pre_plus", "post_plus", "pre_minus", "post_minus",
                  "weight_ratio"])
    for m in row.result["mbons"]:
        w = weights.get(m["cell_type"])
        out.writerow([m["cell_type"], m["n"], int(m["us_target"]),
                      *(f"{m[k]:.6g}" for k in ("pre_plus", "post_plus", "pre_minus", "post_minus")),
                      f"{sum(w) / len(w):.6g}" if w else ""])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers=_attachment(f"experiment-{experiment_id}-mbons.csv"))


@router.get("/{experiment_id}/spikes.csv", response_class=StreamingResponse,
            responses={200: {"content": {"text/csv": {}}}})
def export_spikes(experiment_id: str,
                  group: list[str] | None = Query(None, description="repeat to select several"),
                  store: ModelStore = Depends(get_store),
                  jobs: JobService = Depends(get_jobs)):
    """Every recorded spike (time, neuron index, FlyWire id, group, cell type),
    streamed one second at a time, so even millions of spikes never sit in memory."""
    row = _with_spikes(jobs, experiment_id)
    mask = _group_mask(store, group)
    duration = float(row.result["duration_ms"])
    root = [str(r) for r in store.network.root_id]

    def lines():
        yield "time_ms,neuron,root_id,group,cell_type\n"
        t0 = 0.0
        while t0 <= duration:
            n, t, _ = jobs.spikes.window(row.id, t0, t0 + 1000.0, mask, 2**62)
            buf = io.StringIO()
            out = csv.writer(buf)
            for i, ti in zip(n.tolist(), t.tolist()):
                out.writerow([f"{ti:.2f}", i, root[i], store.group[i], store.cell_type[i]])
            yield buf.getvalue()
            t0 += 1000.0

    return StreamingResponse(lines(), media_type="text/csv",
                             headers=_attachment(f"experiment-{experiment_id}-spikes.csv"))


@router.delete("/{experiment_id}", status_code=204)
def delete_experiment(experiment_id: str, request: Request, jobs: JobService = Depends(get_jobs),
                      client: str = Depends(writer)):
    check_owner(request, client, _get(jobs, experiment_id).owner)
    try:
        found = jobs.delete(experiment_id)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    if not found:
        raise HTTPException(status_code=404, detail=f"no experiment '{experiment_id}'")
    return Response(status_code=204)
