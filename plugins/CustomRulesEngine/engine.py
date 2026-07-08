"""
Pure rule-evaluation engine.

Nothing in this module reads stdin, calls the Stash API, or touches disk.
Everything here operates on the validated dataclasses from schema.py
(Rule/Condition/Action) rather than raw dicts -- by the time a Rule reaches
this module, its shape is already guaranteed, so there's no defensive
`.get()` scattered through the evaluator. Malformed input is caught once,
at load time, in schema.py.

CONDITIONS, v2: modifier-based rather than regex-only. MODIFIER_HANDLERS
maps a modifier name (schema.MODIFIER_ARITY's keys) to a function
(value, condition) -> (passed: bool, match: Optional[re.Match]).
Every handler returns that same two-tuple shape uniformly, including
non-regex ones (which just return None for match) -- this is what lets
evaluate_conditions() avoid special-casing "is this a regex condition"
in the evaluation loop itself.

IMPORTANT CORRECTNESS NOTE: earlier versions of this engine used "is there
a regex match object" as a stand-in for "did the conditions pass". That
conflation breaks the moment a condition can pass without ever producing a
match object (e.g. a lone EQUALS or IS_NULL condition) -- under the old
logic such a rule would incorrectly be treated as never matching. This
version tracks pass/fail and the optional capture-group match as two
separate things throughout.
"""

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from resolvers import get_field
from schema import Rule, Condition, Action


class RuleError(Exception):
    """Raised when a rule reaches the engine in a state schema validation should have caught."""


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
# Value coercion / comparison helpers
# ------------------------------------------------------------
def _stringify(value) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _coerce_like(value, raw):
    """
    Best-effort coercion of a rules-file value (always JSON-typed, usually
    a plain string since the UI currently only produces strings) to match
    the type of the field value being compared against -- so comparing a
    numeric/boolean field still works correctly even though the authoring
    side hasn't been taught to produce typed values yet. Falls back to the
    raw value unchanged if coercion isn't sensible.
    """
    if isinstance(value, bool):
        if isinstance(raw, str):
            return raw.strip().lower() in ("true", "1", "yes")
        return bool(raw)
    if isinstance(value, int):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return raw
    if isinstance(value, float):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return raw
    return raw


def _is_empty(value) -> bool:
    return value is None or value == "" or value == []


def _regex_search_any(value, compiled: re.Pattern) -> Optional[re.Match]:
    """Search a string field, or the first matching element of a list field."""
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                m = compiled.search(item)
                if m:
                    return m
        return None
    if isinstance(value, str):
        return compiled.search(value)
    return None


# ------------------------------------------------------------
# Modifier handlers
# ------------------------------------------------------------
# Every handler: (value, condition) -> (passed: bool, match: Optional[re.Match]).
# `value` is whatever get_field() resolved (may be None, str, int, bool, list).
# `condition` is the validated schema.Condition (gives access to .values and,
# for regex modifiers, .compiled_pattern).

def _mod_equals(value, cond: Condition):
    return value == _coerce_like(value, cond.values[0]), None


def _mod_not_equals(value, cond: Condition):
    passed, _ = _mod_equals(value, cond)
    return not passed, None


def _mod_includes(value, cond: Condition):
    target = cond.values[0]
    if isinstance(value, list):
        return any(target in _stringify(item) for item in value), None
    return target in _stringify(value), None


def _mod_excludes(value, cond: Condition):
    passed, _ = _mod_includes(value, cond)
    return not passed, None


def _mod_matches_regex(value, cond: Condition):
    match = _regex_search_any(value, cond.compiled_pattern)
    return match is not None, match


def _mod_not_matches_regex(value, cond: Condition):
    match = _regex_search_any(value, cond.compiled_pattern)
    return match is None, None


def _mod_greater_than(value, cond: Condition):
    if value is None:
        return False, None
    try:
        return value > _coerce_like(value, cond.values[0]), None
    except TypeError:
        return False, None


def _mod_less_than(value, cond: Condition):
    if value is None:
        return False, None
    try:
        return value < _coerce_like(value, cond.values[0]), None
    except TypeError:
        return False, None


def _mod_is_null(value, cond: Condition):
    return _is_empty(value), None


def _mod_not_null(value, cond: Condition):
    return not _is_empty(value), None


def _mod_between(value, cond: Condition):
    if value is None:
        return False, None
    try:
        lo = _coerce_like(value, cond.values[0])
        hi = _coerce_like(value, cond.values[1])
        return lo <= value <= hi, None
    except TypeError:
        return False, None


def _mod_not_between(value, cond: Condition):
    passed, _ = _mod_between(value, cond)
    return not passed, None


MODIFIER_HANDLERS: dict = {
    "EQUALS": _mod_equals,
    "NOT_EQUALS": _mod_not_equals,
    "INCLUDES": _mod_includes,
    "EXCLUDES": _mod_excludes,
    "MATCHES_REGEX": _mod_matches_regex,
    "NOT_MATCHES_REGEX": _mod_not_matches_regex,
    "GREATER_THAN": _mod_greater_than,
    "LESS_THAN": _mod_less_than,
    "IS_NULL": _mod_is_null,
    "NOT_NULL": _mod_not_null,
    "BETWEEN": _mod_between,
    "NOT_BETWEEN": _mod_not_between,
}


def evaluate_conditions(entity: dict, rule: Rule) -> "tuple[bool, Optional[re.Match]]":
    """
    Evaluate every condition in `rule` against `entity`.

    Returns (passed, match). `passed` is True only if every condition
    passed. `match` is the re.Match from the last regex-based condition
    that contributed one (used for {1}/{2} capture-group substitution in
    actions), or None if no regex condition ran or matched -- this is
    independent of `passed`, since a rule can fully match using only
    non-regex modifiers.

    NOTE: if a rule has multiple regex conditions on the same list field,
    only the match from the LAST one evaluated is kept for substitution --
    a known limitation carried over from earlier versions, not addressed
    here.
    """
    last_match = None
    for cond in rule.conditions:
        value = get_field(entity, cond.field)
        handler = MODIFIER_HANDLERS.get(cond.modifier)
        if handler is None:
            # Should be unreachable for schema-validated rules.
            raise RuleError(f"unsupported modifier: {cond.modifier}")

        passed, match = handler(value, cond)
        if not passed:
            return False, None
        if match is not None:
            last_match = match

    return True, last_match


# ------------------------------------------------------------
# Action handlers
# ------------------------------------------------------------
def _action_set(entity: dict, action: Action, match: Optional[re.Match]) -> Optional[PlannedChange]:
    new_value = substitute(action.template, match)
    current_value = get_field(entity, action.field)
    if current_value == new_value:
        return None  # already correct, no-op

    return PlannedChange(
        field=action.field,
        new_value=new_value,
        action_type="set",
        reason=f"setting {action.field} -> {new_value}",
    )


def _action_add(entity: dict, action: Action, match: Optional[re.Match]) -> Optional[PlannedChange]:
    new_value = substitute(action.template, match)
    existing = entity.get(action.field)
    if existing is None:
        existing = []
    if not isinstance(existing, list):
        raise RuleError(f"field '{action.field}' is not a list; cannot 'add'")

    # NOTE: substring-match dedup (not exact-match) is intentional -- see
    # earlier design discussion. Not a bug, not addressed here.
    already_present = any(
        isinstance(item, str) and new_value in item for item in existing
    )
    if already_present:
        return None

    return PlannedChange(
        field=action.field,
        new_value=existing + [new_value],
        action_type="add",
        reason=f"adding to {action.field} -> {new_value}",
    )


ACTION_HANDLERS: dict = {
    "set": _action_set,
    "add": _action_add,
}


def plan_actions(entity: dict, rule: Rule, match: Optional[re.Match]) -> list:
    """
    Compute the PlannedChange list that applying `rule`'s actions to `entity`
    would produce, WITHOUT calling out to Stash. Safe to use for previews /
    dry-runs since it never mutates `entity` or calls any API.
    """
    changes = []
    for action in rule.actions:
        handler = ACTION_HANDLERS.get(action.type)
        if handler is None:
            # Should be unreachable for schema-validated rules.
            raise RuleError(f"unsupported action type: {action.type}")

        change = handler(entity, action, match)
        if change is not None:
            changes.append(change)
    return changes


def evaluate_rule(entity: dict, rule: Rule) -> Optional[list]:
    """
    Evaluate a single rule against `entity`.
    Returns a list of PlannedChange (possibly empty) if the rule's
    conditions matched, or None if they did not.
    """
    passed, match = evaluate_conditions(entity, rule)
    if not passed:
        return None
    return plan_actions(entity, rule, match)


def run_rules(
    entity: dict,
    rules: list,  # list[Rule]
    hook_type: Optional[str] = None,
    on_error: Optional[Callable] = None,
) -> "list[tuple[Rule, list]]":
    """
    Evaluate all `rules` against `entity`, in file order.

    Returns a list of (rule, changes) tuples for rules whose conditions
    matched. If a rule hits a runtime-only problem, it reports through
    `on_error(rule, error)` if given, and is skipped -- it does not abort
    evaluation of the remaining rules.
    """
    results = []
    for rule in rules:
        if rule.events and hook_type not in rule.events:
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