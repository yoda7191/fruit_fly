"""API keys for the write endpoints (submitting and deleting experiments and sweeps).

Keys are random tokens shown once at creation; the database stores only their
SHA-256 hash, so a leaked database doesn't leak usable keys. Manage them with:

    python -m backend.app.apikeys create "lab laptop"     # prints the key once
    python -m backend.app.apikeys list
    python -m backend.app.apikeys revoke <id>

The API checks keys only when FRUIT_FLY_REQUIRE_API_KEY=1.
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import sys

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from .db import ApiKeyRow, utcnow

PREFIX = "ff_"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create(sessions: sessionmaker, name: str) -> tuple[str, str]:
    """A new key: returns (id, key). The key isn't stored and can't be shown again."""
    key = PREFIX + secrets.token_urlsafe(32)
    row = ApiKeyRow(id=secrets.token_hex(16), name=name[:64], key_hash=hash_key(key))
    with sessions.begin() as s:
        s.add(row)
    return row.id, key


def revoke(sessions: sessionmaker, key_id: str) -> bool:
    with sessions.begin() as s:
        n = s.execute(update(ApiKeyRow).where(ApiKeyRow.id == key_id, ApiKeyRow.revoked_at.is_(None))
                      .values(revoked_at=utcnow())).rowcount
    return n == 1


def list_keys(sessions: sessionmaker) -> list[ApiKeyRow]:
    with sessions() as s:
        return list(s.scalars(select(ApiKeyRow).order_by(ApiKeyRow.created_at)))


def verify(sessions: sessionmaker, key: str | None) -> str | None:
    """The key's id if it is valid and not revoked, else None. Records last use."""
    if not key or not key.startswith(PREFIX):
        return None
    with sessions.begin() as s:
        row = s.scalar(select(ApiKeyRow).where(ApiKeyRow.key_hash == hash_key(key)))
        if row is None or row.revoked_at is not None:
            return None
        row.last_used_at = utcnow()
        return row.id


def main(argv: list[str] | None = None) -> int:
    from .config import Settings
    from .db import init_db, make_engine, make_sessionmaker

    ap = argparse.ArgumentParser(description="Manage fruit_fly API keys")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create").add_argument("name")
    sub.add_parser("list")
    sub.add_parser("revoke").add_argument("id")
    args = ap.parse_args(argv)

    engine = make_engine(Settings.from_env().db_url)
    init_db(engine)
    sessions = make_sessionmaker(engine)
    if args.cmd == "create":
        key_id, key = create(sessions, args.name)
        print(f"id   {key_id}\nkey  {key}\n(store the key now: it cannot be shown again)")
    elif args.cmd == "list":
        for k in list_keys(sessions):
            state = f"revoked {k.revoked_at:%Y-%m-%d}" if k.revoked_at else "active"
            used = f"last used {k.last_used_at:%Y-%m-%d %H:%M}" if k.last_used_at else "never used"
            print(f"{k.id}  {k.name:24}  {state:18}  {used}")
    elif args.cmd == "revoke":
        if not revoke(sessions, args.id):
            print(f"no active key {args.id}", file=sys.stderr)
            return 1
        print(f"revoked {args.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
