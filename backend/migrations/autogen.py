"""Autogenerate helpers shared by env.py and the tests (env.py itself can only
run inside Alembic, so it can't be imported)."""

from __future__ import annotations


def compare_type(ctx, inspected_column, metadata_column, inspected_type, metadata_type):
    """Compare through TypeDecorators (UTCDateTime is a DateTime(timezone=True)
    in the database), so autogenerate doesn't report it as a change."""
    impl = getattr(metadata_type, "impl", None)
    if impl is not None:
        return ctx.impl.compare_type(inspected_column, metadata_column.copy(type_=impl))
    return None          # default comparison


def render_item(type_, obj, autogen_context):
    """Write app-specific column types as their plain database type, so a
    migration never imports application code (which keeps changing; a
    migration must stay exactly what it was when it was written)."""
    impl = getattr(obj, "impl", None)
    if type_ == "type" and impl is not None:
        autogen_context.imports.add("import sqlalchemy as sa")
        return f"sa.{impl!r}"
    return False         # default rendering