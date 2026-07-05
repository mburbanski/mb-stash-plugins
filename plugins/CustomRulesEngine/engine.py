"""
Pure rule-evaluation engine.

Nothing in this module reads stdin, calls the Stash API, or touches disk.
Everything here operates on the validated dataclasses from schema.py
(Rule/Condition/Action) rather than raw dicts -- by the time a Rule reaches
this module, its shape is already guaranteed, so there's no defensive
`.get()` scattered through the evaluator. Malformed input is caught once,
at load time, in schema.py.

Condition types and action types are still dispatched through registries
(CONDITION_HANDLERS / ACTION_HANDLERS). The RuleError path here is now a
defense-in-depth safety net (e.g. for Rule objects constructed directly in
tests, bypassing schema validation) rather than the primary way unknown
types get caught -- that happens in schema.py now.
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
# Condition handlers
# ------------------------------------------------------------
def _cond_regex(entity: dict, cond: Condition) -> Optional[re.Match]:
    value = get_field(entity, cond.field)
    if value is None:
        return None

    # Pattern was already compiled and validated at load time (schema.py),
    # so no re.compile / re.error handling needed here.
    compiled = cond.compiled_pattern

    # List fields: first element that matches wins (mirrors original behavior).
    # NOTE: if a rule has multiple conditions targeting the same list field,
    # only the match from the LAST condition evaluated is kept for capture
    # group substitution -- a known limitation carried over from the
    # original implementation, not addressed by this rewrite.
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


CONDITION_HANDLERS: dict[str, Callable[[dict, Condition], Optional[re.Match]]] = {
    "regex": _cond_regex,
}


def evaluate_conditions(entity: dict, rule: Rule) -> Optional[re.Match]:
    """
    Evaluate every condition in `rule` against `entity`.

    Returns the match object from the last condition evaluated (used for
    capture-group substitution in actions) if ALL conditions pass, or None
    if any condition fails. (schema.py guarantees every rule has at least
    one condition, so an empty list here would indicate a Rule built
    outside the normal validation path.)
    """
    last_match = None
    for cond in rule.conditions:
        handler = CONDITION_HANDLERS.get(cond.type)
        if handler is None:
            # Should be unreachable for schema-validated rules.
            raise RuleError(f"unsupported condition type: {cond.type}")

        result = handler(entity, cond)
        if not result:
            return None
        last_match = result

    return last_match


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
        # Schema validation can't know the runtime type of a scene field,
        # so this check still has to happen here rather than at load time.
        raise RuleError(f"field '{action.field}' is not a list; cannot 'add'")

    # NOTE: substring-match dedup (not exact-match) carried over from the
    # original implementation -- flagged earlier as a correctness issue to
    # revisit separately, not addressed in this structural rewrite.
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


ACTION_HANDLERS: dict[str, Callable[[dict, Action, Optional[re.Match]], Optional[PlannedChange]]] = {
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
    match = evaluate_conditions(entity, rule)
    if not match:
        return None
    return plan_actions(entity, rule, match)


def run_rules(
    entity: dict,
    rules: list,  # list[Rule]
    hook_type: Optional[str] = None,
    on_error: Optional[Callable[[Rule, RuleError], None]] = None,
) -> "list[tuple[Rule, list]]":
    """
    Evaluate all `rules` against `entity`, in file order.

    Returns a list of (rule, changes) tuples for rules whose conditions
    matched. If a rule hits a runtime-only problem (e.g. a field turning out
    not to be a list for an 'add' action), it reports through
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
