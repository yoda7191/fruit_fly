"""Ready-made protocols (extinction, reversal, second-order, backward pairing, ...)."""

from fastapi import APIRouter

from ..protocols import PRESETS, Preset

router = APIRouter(prefix="/api/protocols", tags=["protocols"])


@router.get("", response_model=list[Preset])
def list_protocols():
    """Each preset gives steps, readout and parameter overrides to put in an
    experiment request, plus what flies do and what to expect from the model."""
    return PRESETS