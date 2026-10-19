"""Circuit structure: summary numbers, the neuron table, connections, and the anatomy
files the 3D viewer draws."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from ..deps import get_store
from ..model import ModelStore
from ..schemas import CircuitSummary, GroupConnection, NeuronConnections, NeuronDetail, NeuronTable

router = APIRouter(prefix="/api/circuit", tags=["circuit"])


@router.get("", response_model=CircuitSummary)
def circuit_summary(store: ModelStore = Depends(get_store)):
    return store.summary()


@router.get("/lesion-options")
def lesion_options(store: ModelStore = Depends(get_store)) -> dict[str, list[str]]:
    """Groups and cell types that can be silenced (the `lesions` request field)."""
    return store.lesion_options()


@router.get("/neurons", response_model=NeuronTable)
def neuron_table(store: ModelStore = Depends(get_store)):
    """Every neuron's ID, group, cell type and position. List position = neuron
    index, the index used by spike data."""
    return store.neuron_payload()

@router.get("/neurons/{index}", response_model=NeuronDetail)
def neuron_detail(index: int, limit: int = Query(8, ge=1, le=50), store: ModelStore = Depends(get_store)):
    """One neuron (by its index in the neuron table): identity, transmitter, and its
    largest input and output partners grouped by cell type."""
    return store.neuron_detail(_neuron(store, index), limit)


def _neuron(store: ModelStore, index: int) -> int:
    if not 0 <= index < len(store.network):
        raise HTTPException(status_code=404, detail=f"no neuron {index}")
    return index


@router.get("/neurons/{index}/connections", response_model=NeuronConnections)
def neuron_connections(index: int, min_synapses: int = Query(1, ge=1, le=1000),
                       limit: int = Query(200, ge=1, le=2000), store: ModelStore = Depends(get_store)):
    """Each partner neuron of one neuron, strongest first, for drawing its connections."""
    return store.connections(_neuron(store, index), min_synapses, limit)


@router.get("/connectivity", response_model=list[GroupConnection])
def group_connectivity(store: ModelStore = Depends(get_store)):
    """Synapses between every pair of neuron groups, largest first."""
    return store.group_connectivity()


def _anatomy_file(request: Request, path: Path, media_type: str) -> FileResponse:
    """The file, or its prebuilt gzip copy for clients that accept gzip (compressing
    the 15 MB morphology on every request would cost seconds of CPU each time)."""
    if not path.exists():
        raise HTTPException(status_code=404,
                            detail=f"this circuit has no {path.name}; run scripts/build_anatomy.py")
    # The ETag lets browsers revalidate instead of downloading again.
    headers = {"Cache-Control": "no-cache"}
    gz = path.with_name(path.name + ".gz")
    if ("gzip" in request.headers.get("accept-encoding", "") and gz.exists()
            and gz.stat().st_mtime >= path.stat().st_mtime):
        # (the GZip middleware leaves encoded responses alone, and adds Vary only to its own)
        return FileResponse(gz, media_type=media_type,
                            headers={**headers, "Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return FileResponse(path, media_type=media_type, headers=headers)


@router.get("/regions")
def brain_regions(request: Request, store: ModelStore = Depends(get_store)) -> FileResponse:
    """Brain region meshes (FlyWire space, nm) as JSON: see scripts/build_anatomy.py."""
    return _anatomy_file(request, store.regions_file, "application/json")


@router.get("/morphology")
def morphology(request: Request, store: ModelStore = Depends(get_store)) -> FileResponse:
    """Every neuron's simplified skeleton, binary: see scripts/build_anatomy.py."""
    return _anatomy_file(request, store.morphology_file, "application/octet-stream")

