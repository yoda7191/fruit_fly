"""DoOR odours: search, per-glomerulus responses, similarity."""

import math

from fastapi import APIRouter, Depends, Query

from ..deps import get_store, require_odours, unknown_odour
from ..model import ModelStore
from ..schemas import OdourCatalog, OdourDetail, OdourList, OdourSimilarity

router = APIRouter(prefix="/api/odours", tags=["odours"])

def _resolve(store: ModelStore, name: str) -> str:
    try:
        return store.resolve_odour(name)
    except KeyError as e:
        raise unknown_odour(name, e.args[0]) from None


@router.get("", response_model=OdourList)
def list_odours(search: str = Query("", max_length=200), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=1000), store: ModelStore = Depends(get_store)):
    require_odours(store)
    names = store.odour_search(search)
    page = names[offset:offset+limit]
    return {"total": len(names), "offset": offset, "limit": limit, "items": [{"name": n, "coverage": store.odour_coverage(n)} for n in page]}


@router.get("/catalog", response_model=OdourCatalog)
def odour_catalog(store: ModelStore = Depends(get_store)):
    """Every odour with its chemical class and coverage, for an odour menu."""
    require_odours(store)
    return {"items": store.odour_catalog()}


@router.get("/detail", response_model=OdourDetail)
def odour_detail(name: str = Query(..., min_length=1, max_length=200), store: ModelStore = Depends(get_store)):
    """Response of every glomerulus to one odour (None = never measured)."""
    require_odours(store)
    canonical = _resolve(store, name)
    lib = store.library
    raw = lib.raw(canonical)
    spont = lib.spontaneous
    return {
        "name": canonical,
        "coverage": store.odour_coverage(canonical),
        "glomeruli": [
            {"glomerulus": g,
             "response": float(raw[i]) if math.isfinite(raw[i]) else None,
             "spontaneous": float(spont[i])} for i, g in enumerate(lib.glomeruli)
        ],
    }


@router.get("/similarity", response_model=OdourSimilarity)
def odour_similarity(a: str=Query(..., min_length=1, max_length=200), b: str = Query(..., min_length=1, max_length=200), store: ModelStore = Depends(get_store)):
    """Correlation of two odours' receptor responses (1 = identical pattern)."""
    require_odours(store)
    ca, cb = _resolve(store, a), _resolve(store, b)
    s = store.library.similarity(ca, cb)
    return {"a": ca, "b": cb, "similarity": s if math.isfinite(s) else None}