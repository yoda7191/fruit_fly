"""FastAPI dependencies and helpers shared by the routers."""

from fastapi import HTTPException, Request

from . import apikeys
from .ratelimit import RateLimited

from .jobs import JobService
from .model import ModelStore
from .schemas import ConditioningRequest


def get_store(request: Request) -> ModelStore:
    return request.app.state.store


def get_jobs(request: Request) -> JobService:
    return request.app.state.jobs


def require_odours(store: ModelStore) -> None:
    if not store.has_odours:
        raise HTTPException(
            status_code=503,
            detail="odour data not loaded; run scripts/download_door.sh or set FRUIT_FLY_DOOR_DIR")


def unknown_odour(name: str, suggestions: list[str], status_code: int = 404) -> HTTPException:
    return HTTPException(status_code=status_code,
                         detail={"message": f"unknown odour '{name}'", "suggestions": suggestions})


def canonical_request(store: ModelStore, req: ConditioningRequest) -> ConditioningRequest:
    """Check a request's odours (against DoOR) and lesions (against the circuit);
    return it with canonical odour names."""
    try:
        store.lesion_indices(req.lesions)
    except KeyError as e:
        raise HTTPException(status_code=422, detail=e.args[0]) from None
    if req.odour_source != "door":
        return req
    if not store.has_odours:
        raise HTTPException(status_code=409, detail="odour data not loaded; use odour_source='random'")
    names = {}
    for field in ("cs_plus", "cs_minus"):
        try:
            names[field] = store.resolve_odour(getattr(req, field))
        except KeyError as e:
            raise unknown_odour(getattr(req, field), e.args[0], status_code=422) from None
    if names["cs_plus"] == names["cs_minus"]:
        raise HTTPException(status_code=422, detail="cs_plus and cs_minus must be different odours")
    extras = {}
    for slot, name in req.extra_odours.items():
        try:
            extras[slot] = store.resolve_odour(name)
        except KeyError as e:
            raise unknown_odour(name, e.args[0], status_code=422) from None
    return req.model_copy(update={**names, "extra_odours": extras})

def client_address(request: Request) -> str:
    """The visitor's address. Behind FRUIT_FLY_PROXY_HOPS proxies of our own, it is
    the entry the outermost one appended to X-Forwarded-For (counted from the
    right); anything to its left came from the client and could be forged to
    dodge per-address rate limits."""
    hops = request.app.state.settings.proxy_hops
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if hops and forwarded:
        return forwarded[-hops] if len(forwarded) >= hops else forwarded[0]
    return request.client.host if request.client else "unknown"


def writer(request: Request) -> str:
    """Who is changing something: an API key's id when keys are required (else 401),
    otherwise the client address. Used for the write endpoints."""
    state = request.app.state
    if not state.settings.require_api_key:
        return f"addr:{client_address(request)}"
    key_id = apikeys.verify(state.sessions, request.headers.get("X-API-Key"))
    if key_id is None:
        state.metrics.refused.labels("api_key").inc()
        raise HTTPException(status_code=401, detail="a valid X-API-Key header is required",
                            headers={"WWW-Authenticate": "X-API-Key"})
    return f"key:{key_id}"


def check_owner(request: Request, client: str, owner: str | None) -> None:
    """May `client` cancel or delete something `owner` submitted? On a server that
    requires API keys every key holder may (they are trusted operators). On an
    open server (a public demo) only the owner may, or a request that carries a
    valid API key anyway; otherwise 403. Rows from before owners were recorded
    have none, and only key holders may change them."""
    state = request.app.state
    if state.settings.require_api_key or (owner is not None and client == owner):
        return
    if apikeys.verify(state.sessions, request.headers.get("X-API-Key")) is not None:
        return
    state.metrics.refused.labels("not_owner").inc()
    raise HTTPException(status_code=403, detail="only whoever submitted it can change it")


def charge(request: Request, client: str, experiments: int) -> None:
    """Count experiments against the client's per-minute limit (429 + Retry-After when over)."""
    try:
        request.app.state.rate_limiter.charge(client, experiments)
    except RateLimited as e:
        request.app.state.metrics.refused.labels("rate_limit").inc()
        raise HTTPException(status_code=429, detail=str(e),
                            headers={"Retry-After": str(e.retry_after)}) from None
