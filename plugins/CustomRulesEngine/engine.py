"""
Pure rule-evaluation engine.

Nothing in this module reads stdin, calls the Stash API, or touches disk.
Every function here is callable and testable with plain dicts, which is what
makes a future dry-run mode (and unit tests) cheap: you can hand it a sample
scene dict and a rules list and inspect exactly what it *would* do.

Condition types and action types are dispatched through registries
(CONDITION_HANDLERS / ACTION_HANDLERS) rather than if/elif chains, so adding
a new condition or action type later means writing a handler function and
registering it here -- not editing a growing branch of existing logic.
"""

import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Optional

from resolvers import get_field


class RuleError(Exception):
    """Raised for malformed rule definitions: bad regex, unknown types, etc."""


@dataclass
class PlannedChange:
    """A single field change a rule's actions would make, not yet applied."""
    field: str
    new_value: Any
    action_type: str
    reason: str = ""


# ------------------------------------------------------------
# Substitution helper (capture groups -> {1}, {2}, ...)
# ------------------------------------------------------------
def substitute(template: str, match: Optional[re.Match]) -> str:
    out = template
    if match:
        for i, g in enumerate(match.groups(), start=1):
            out = out.replace(f"{{{i}}}", g or "")
    return out


# ------------------------------------------------------------
# Condition handlers
# ------------------------------------------------------------
def _cond_regex(entity: dict, cond: dict) -> Optional[re.Match]:
    field_path = cond.get("field")
    pattern = cond.get("pattern")
    value = get_field(entity, field_path)

    if value is None:
        return None

    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise RuleError(f"invalid regex '{pattern}' for field '{field_path}': {e}")

    # List fields: first element that matches wins (mirrors original behavior).
    # NOTE: if a rule has multiple conditions targeting the same list field,
    # only the match from the LAST condition evaluated is kept for capture
    # group substitution -- this is a known limitation carried over from the
    # original implementation, not something this rewrite changes.
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                m = compiled.search(item)
                if m:
                    return m
        return None

    if not isinstance(value, str):
        return None

    return compiled.search(value)


CONDITION_HANDLERS: dict[str, Callable[[dict, dict], Optional[re.Match]]] = {
    "regex": _cond_regex,
}


def evaluate_conditions(entity: dict, rule: dict) -> Optional[re.Match]:
    """
    Evaluate every condition in `rule` against `entity`.

    Returns the match object from the last condition evaluated (used for
    capture-group substitution in actions) if ALL conditions pass, or None
    if the rule has no conditions or any condition fails.

    Raises RuleError if a condition uses an unregistered type or a bad
    pattern -- the caller decides whether to skip just this rule or abort.
    """
    conditions = rule.get("conditions", [])
    if not conditions:
        return None

    last_match = None
    for cond in conditions:
        ctype = cond.get("type")
        handler = CONDITION_HANDLERS.get(ctype)
        if handler is None:
            raise RuleError(f"unsupported condition type: {ctype}")

        result = handler(entity, cond)
        if not result:
            return None
        last_match = result

    return last_match


# ------------------------------------------------------------
# Action handlers
# ------------------------------------------------------------
def _action_set(entity: dict, action: dict, match: Optional[re.Match]) -> Optional[PlannedChange]:
    field_path = action.get("field")
    mode = action.get("mode", "always")
    template = action.get("template", "")

    if mode != "always":
        raise RuleError(f"unsupported mode for 'set': {mode}")

    new_value = substitute(template, match)
    current_value = get_field(entity, field_path)
    if current_value == new_value:
        return None  # already correct, no-op

    return PlannedChange(
        field=field_path,
        new_value=new_value,
        action_type="set",
        reason=f"setting {field_path} -> {new_value}",
    )


def _action_add(entity: dict, action: dict, match: Optional[re.Match]) -> Optional[PlannedChange]:
    field_path = action.get("field")
    mode = action.get("mode", "if_missing")
    template = action.get("template", "")

    if mode != "if_missing":
        raise RuleError(f"unsupported mode for 'add': {mode}")

    new_value = substitute(template, match)
    existing = entity.get(field_path)
    if existing is None:
        existing = []
    if not isinstance(existing, list):
        raise RuleError(f"field '{field_path}' is not a list; cannot 'add'")

    # NOTE: substring-match dedup (not exact-match) carried over from the
    # original implementation -- flagged earlier as a correctness issue to
    # revisit separately, not addressed in this structural rewrite.
    already_present = any(
        isinstance(item, str) and new_value in item for item in existing
    )
    if already_present:
        return None

    return PlannedChange(
        field=field_path,
        new_value=existing + [new_value],
        action_type="add",
        reason=f"adding to {field_path} -> {new_value}",
    )


ACTION_HANDLERS: dict[str, Callable[[dict, dict, Optional[re.Match]], Optional[PlannedChange]]] = {
    "set": _action_set,
    "add": _action_add,
}


def plan_actions(entity: dict, rule: dict, match: Optional[re.Match]) -> list[PlannedChange]:
    """
    Compute the PlannedChange list that applying `rule`'s actions to `entity`
    would produce, WITHOUT calling out to Stash. Safe to use for previews /
    dry-runs since it never mutates `entity` or calls any API.
    """
    changes = []
    for action in rule.get("actions", []):
        atype = action.get("type")
        handler = ACTION_HANDLERS.get(atype)
        if handler is None:
            raise RuleError(f"unsupported action type: {atype}")

        change = handler(entity, action, match)
        if change is not None:
            changes.append(change)
    return changes


def evaluate_rule(entity: dict, rule: dict) -> Optional[list[PlannedChange]]:
    """
    Evaluate a single rule against `entity`.
    Returns a list of PlannedChange (possibly empty) if the rule's
    conditions matched, or None if they did not.
    """
    match = evaluate_conditions(entity, rule)
    if not match:
        return None
    return plan_actions(entity, rule, match)


def run_rules(
    entity: dict,
    rules: list[dict],
    hook_type: Optional[str] = None,
    on_error: Optional[Callable[[dict, RuleError], None]] = None,
) -> list[tuple[dict, list[PlannedChange]]]:
    """
    Evaluate all `rules` against `entity`, in file order.

    Returns a list of (rule, changes) tuples for rules whose conditions
    matched. A malformed rule reports through `on_error(rule, error)` (if
    given) and is skipped -- it does not abort evaluation of the remaining
    rules.
    """
    results = []
    for rule in rules:
        events = rule.get("events")
        if events and hook_type not in events:
            continue

        try:
            changes = evaluate_rule(entity, rule)
        except RuleError as e:
            if on_error:
                on_error(rule, e)
            continue

        if changes is None:
            continue

        results.append((rule, changes))

    return results
