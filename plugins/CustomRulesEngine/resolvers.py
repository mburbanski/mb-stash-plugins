"""
Field resolution for Stash entities (scenes, and later performers/studios/etc).

This module knows how to pull a value out of an entity dict given a field
path string. Two kinds of paths are supported:

  1. Dotted paths against the raw entity dict, e.g. "studio.name" or
     "files.0.path".
  2. "Virtual" fields registered in FIELD_RESOLVERS, for values that either
     don't map directly to a dotted path (e.g. "file.path", which needs to
     pick the *primary* file) or that require custom logic to compute.

To expose a new piece of metadata to conditions/actions later, add an entry
to FIELD_RESOLVERS rather than special-casing it elsewhere in the engine.
"""

from typing import Any, Callable, Optional


def resolve_field(obj: dict, field_path: str) -> Optional[Any]:
    """Resolve a dotted path (e.g. 'files.0.path') against a nested dict/list."""
    parts = field_path.split(".")
    cur = obj
    for p in parts:
        if isinstance(cur, list):
            try:
                idx = int(p)
                cur = cur[idx]
            except (ValueError, IndexError):
                return None
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
            if cur is None:
                return None
    return cur


def get_primary_file(scene: dict) -> Optional[dict]:
    """Return the scene's primary file dict, falling back to the first file."""
    files = scene.get("files") or []
    if not files:
        return None
    primary_id = scene.get("primary_file_id")
    for f in files:
        if f.get("id") == primary_id:
            return f
    return files[0]


def _resolve_file_path(scene: dict) -> Optional[str]:
    primary = get_primary_file(scene)
    return primary.get("path") if primary else None


# Virtual field registry: name -> resolver(entity) -> value.
# Add new entries here as new "kinds of metadata" become supported, instead
# of adding special cases to the condition/action evaluators.
FIELD_RESOLVERS: dict[str, Callable[[dict], Optional[Any]]] = {
    "file.path": _resolve_file_path,
}


def get_field(entity: dict, field_path: str) -> Optional[Any]:
    """
    Resolve `field_path` against `entity`. Checks the virtual field registry
    first, then falls back to a plain dotted-path lookup.
    """
    resolver = FIELD_RESOLVERS.get(field_path)
    if resolver:
        return resolver(entity)
    return resolve_field(entity, field_path)
