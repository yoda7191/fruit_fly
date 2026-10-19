"""Parameter sweeps: many experiments varying one parameter, aggregated."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from .. import sweeps as sweep_logic
from ..db import SweepRow
from ..deps import canonical_request, charge, check_owner, get_jobs, get_store, writer
from ..events import stream_changes
from ..jobs import BadCursor, CapacityError, JobService, QueueUnavailable, new_id
from ..logs import request_id
from ..model import ModelStore
from ..schemas import SweepCancelResult, SweepDetail, SweepPage, SweepRequest, SweepSummary
from .experiments import SSE_RESPONSE

router = APIRouter(prefix="/api/sweeps", tags=["sweeps"])


def _get(jobs: JobService, sweep_id: str) -> SweepRow:
    sweep = jobs.get_sweep(sweep_id)
    if sweep is None:
        raise HTTPException(status_code=404, detail=f"no sweep '{sweep_id}'")
    return sweep


@router.post("", response_model=SweepSummary, status_code=202)
def create_sweep(body: SweepRequest, request: Request,
                 store: ModelStore = Depends(get_store),
                 jobs: JobService = Depends(get_jobs),
                 client: str = Depends(writer)):
    """Queue one experiment per (value, repeat). Spikes are not stored for
    sweep experiments, only their results."""
    limit = request.app.state.settings.max_sweep_size
    size = len(body.values) * body.repeats
    if size > limit:
        raise HTTPException(status_code=422,
                            detail=f"sweep would create {size} experiments; the limit is {limit}")
    body = body.model_copy(update={"base": canonical_request(store, body.base)})
    if body.parameter == "lesion":            # every lesion must exist in this circuit
        try:
            store.lesion_indices([l for l in map(sweep_logic.parse_lesion, body.values) if l])
        except KeyError as e:
            raise HTTPException(status_code=422, detail=e.args[0]) from None
    try:
        members = sweep_logic.expand(body)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None

    charge(request, client, len(members))     # a sweep costs one per experiment
    sweep = SweepRow(id=new_id(), parameter=body.parameter, values=body.values,
                     repeats=body.repeats, base_request=body.base.model_dump(mode="json"), owner=client)
    try:
        rows = jobs.submit_sweep(sweep, members, request_id=request_id.get())
    except CapacityError as e:
        request.app.state.metrics.refused.labels("capacity").inc()
        raise HTTPException(status_code=429, detail=str(e)) from None
    except QueueUnavailable as e:
        request.app.state.metrics.refused.labels("queue_unavailable").inc()
        raise HTTPException(status_code=503, detail=str(e)) from None
    request.app.state.metrics.submitted.labels("sweep").inc(len(members))
    return sweep_logic.summarize(sweep, sweep_logic.count_statuses(rows))


@router.get("", response_model=SweepPage)
def list_sweeps(limit: int = Query(50, ge=1, le=500),
                cursor: str | None = Query(None, description="next_cursor of the previous page"),
                jobs: JobService = Depends(get_jobs)):
    """Sweeps, newest first, one page at a time."""
    try:
        sweeps, next_cursor = jobs.list_sweeps(limit=limit, cursor=cursor)
    except BadCursor as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    counts = jobs.sweep_counts([s.id for s in sweeps])
    return {"items": [sweep_logic.summarize(s, counts[s.id]) for s in sweeps], "next_cursor": next_cursor}


@router.get("/{sweep_id}", response_model=SweepDetail)
def get_sweep(sweep_id: str, jobs: JobService = Depends(get_jobs)):
    """Status plus mean and SD of every metric per value (finished experiments only)."""
    sweep = _get(jobs, sweep_id)
    return sweep_logic.detail(sweep, jobs.sweep_members(sweep_id))


@router.get("/{sweep_id}/events", response_class=StreamingResponse, responses=SSE_RESPONSE)
async def sweep_events(sweep_id: str, request: Request, jobs: JobService = Depends(get_jobs)):
    """Live sweep progress as server-sent events: an `update` (the sweep detail,
    as from GET /api/sweeps/{id}) whenever a member starts or finishes, then `end`."""
    from starlette.concurrency import run_in_threadpool
    if await run_in_threadpool(jobs.get_sweep, sweep_id) is None:
        raise HTTPException(status_code=404, detail=f"no sweep '{sweep_id}'")

    def read():
        sweep = jobs.get_sweep(sweep_id)
        if sweep is None:
            return None
        detail = SweepDetail.model_validate(sweep_logic.detail(sweep, jobs.sweep_members(sweep_id)))
        return detail.model_dump_json(), detail.status != "running"

    # members finish close together: re-read at most twice a second
    return StreamingResponse(stream_changes(request, request.app.state.events, sweep_id, read,
                                            min_interval_s=0.5),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{sweep_id}/cancel", response_model=SweepCancelResult)
def cancel_sweep(sweep_id: str, request: Request, jobs: JobService = Depends(get_jobs),
                 client: str = Depends(writer)):
    """Cancel the queued experiments of a sweep and stop the running ones.
    Finished experiments keep their results."""
    check_owner(request, client, _get(jobs, sweep_id).owner)
    out = jobs.cancel_sweep(sweep_id)
    if out is None:
        raise HTTPException(status_code=404, detail=f"no sweep '{sweep_id}'")
    return out


@router.get("/{sweep_id}/results.csv", response_class=Response,
            responses={200: {"content": {"text/csv": {}}}})
def sweep_csv(sweep_id: str, jobs: JobService = Depends(get_jobs)):
    """One row per experiment, for analysis in R, Python or a spreadsheet."""
    sweep = _get(jobs, sweep_id)
    text = sweep_logic.results_csv(sweep, jobs.sweep_members(sweep_id))
    return Response(text, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="sweep-{sweep_id}.csv"'})


@router.delete("/{sweep_id}", status_code=204)
def delete_sweep(sweep_id: str, request: Request, jobs: JobService = Depends(get_jobs),
                 client: str = Depends(writer)):
    check_owner(request, client, _get(jobs, sweep_id).owner)
    try:
        found = jobs.delete_sweep(sweep_id)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    if not found:
        raise HTTPException(status_code=404, detail=f"no sweep '{sweep_id}'")
    return Response(status_code=204)