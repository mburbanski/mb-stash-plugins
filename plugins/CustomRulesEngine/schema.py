"""
Rule schema and validation.

Rules are loaded from JSON and validated against this schema BEFORE they're
ever handed to the engine. This is what lets the engine trust the shape of
a Rule/Condition/Action instead of defensively `.get()`-ing every field, and
what lets process_scene() tell "this rule is broken" (a config problem worth
logging loudly) apart from "this rule's conditions didn't match" (an
ordinary, silent outcome) -- previously both collapsed into the same `None`.

SCHEMA_VERSION describes the *rules file format* and is independent of the
plugin's own version in CustomRulesEngine.yml. Bump it when the rule JSON
shape changes in a backwards-incompatible way -- this is the field a future
config UI would read to know whether it can safely parse/write a given
rules file. Files without a schema_version are treated as version 1, so
existing rules files continue to load unchanged.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

SCHEMA_VERSION = 1

# Condition types and the raw fields they require. Extend this alongside
# engine.CONDITION_HANDLERS when a new condition type is added.
CONDITION_TYPE_FIELDS = {
    "regex": {"field", "pattern"},
}

# Action types: required fields and the one mode the engine currently
# supports for each. Extend alongside engine.ACTION_HANDLERS.
ACTION_TYPE_SPECS = {
    "set": {"required": {"field"}, "default_mode": "always"},
    "add": {"required": {"field"}, "default_mode": "if_missing"},
}


class RulesFileError(Exception):
    """File-level problem: unreadable, invalid JSON, bad shape, unsupported schema_version."""


class RuleValidationError(Exception):
    """A single rule's definition doesn't match the expected schema."""

    def __init__(self, rule_index: int, rule_name: str, message: str):
        self.rule_index = rule_index
        self.rule_name = rule_name
        self.message = message
        super().__init__(f"rule #{rule_index} ('{rule_name}'): {message}")


@dataclass
class Condition:
    type: str
    field: str
    pattern: str
    compiled_pattern: Optional[re.Pattern] = None


@dataclass
class Action:
    type: str
    field: str
    template: str = ""
    mode: Optional[str] = None


@dataclass
class Rule:
    name: str
    conditions: list = field(default_factory=list)   # list[Condition]
    actions: list = field(default_factory=list)       # list[Action]
    events: Optional[list] = None                     # list[str] or None


# ------------------------------------------------------------
# Per-item validation
# ------------------------------------------------------------
def _validate_condition(raw: dict, rule_index: int, rule_name: str) -> Condition:
    if not isinstance(raw, dict):
        raise RuleValidationError(rule_index, rule_name, "condition must be an object")

    ctype = raw.get("type")
    if ctype not in CONDITION_TYPE_FIELDS:
        raise RuleValidationError(
            rule_index, rule_name,
            f"unsupported condition type {ctype!r} (known: {sorted(CONDITION_TYPE_FIELDS)})",
        )

    missing = [f for f in CONDITION_TYPE_FIELDS[ctype] if not raw.get(f)]
    if missing:
        raise RuleValidationError(
            rule_index, rule_name,
            f"condition type '{ctype}' missing required field(s): {missing}",
        )

    pattern = raw["pattern"]
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise RuleValidationError(rule_index, rule_name, f"invalid regex '{pattern}': {e}")

    return Condition(type=ctype, field=raw["field"], pattern=pattern, compiled_pattern=compiled)


def _validate_action(raw: dict, rule_index: int, rule_name: str) -> Action:
    if not isinstance(raw, dict):
        raise RuleValidationError(rule_index, rule_name, "action must be an object")

    atype = raw.get("type")
    if atype not in ACTION_TYPE_SPECS:
        raise RuleValidationError(
            rule_index, rule_name,
            f"unsupported action type {atype!r} (known: {sorted(ACTION_TYPE_SPECS)})",
        )

    spec = ACTION_TYPE_SPECS[atype]
    missing = [f for f in spec["required"] if not raw.get(f)]
    if missing:
        raise RuleValidationError(
            rule_index, rule_name,
            f"action type '{atype}' missing required field(s): {missing}",
        )

    mode = raw.get("mode", spec["default_mode"])
    if mode != spec["default_mode"]:
        raise RuleValidationError(
            rule_index, rule_name,
            f"unsupported mode {mode!r} for action type '{atype}' "
            f"(only {spec['default_mode']!r} is currently supported)",
        )

    return Action(type=atype, field=raw["field"], template=raw.get("template", ""), mode=mode)


def _validate_rule(raw: dict, rule_index: int) -> Rule:
    if not isinstance(raw, dict):
        raise RuleValidationError(rule_index, "?", "rule must be an object")

    name = raw.get("name") or f"rule #{rule_index}"

    raw_conditions = raw.get("conditions", [])
    if not isinstance(raw_conditions, list):
        raise RuleValidationError(rule_index, name, "'conditions' must be a list")
    if not raw_conditions:
        raise RuleValidationError(rule_index, name, "rule has no conditions and can never match")

    raw_actions = raw.get("actions", [])
    if not isinstance(raw_actions, list):
        raise RuleValidationError(rule_index, name, "'actions' must be a list")
    if not raw_actions:
        raise RuleValidationError(rule_index, name, "rule has no actions and would have no effect")

    events = raw.get("events")
    if events is not None and not (isinstance(events, list) and all(isinstance(e, str) for e in events)):
        raise RuleValidationError(rule_index, name, "'events' must be a list of strings if present")

    conditions = [_validate_condition(c, rule_index, name) for c in raw_conditions]
    actions = [_validate_action(a, rule_index, name) for a in raw_actions]

    return Rule(name=name, conditions=conditions, actions=actions, events=events)


# ------------------------------------------------------------
# Whole-file validation
# ------------------------------------------------------------
def validate_rules_data(data) -> "tuple[list[Rule], list[RuleValidationError]]":
    """
    Validate a parsed rules JSON document.

    Returns (valid_rules, errors). A rule that fails validation is omitted
    from valid_rules and reported in errors, rather than raising -- one bad
    rule in the file shouldn't prevent the rest from loading.

    File-level problems (wrong top-level shape, unsupported schema_version,
    missing 'rules' key) raise RulesFileError immediately, since there's
    nothing usable to fall back to in those cases.
    """
    if not isinstance(data, dict):
        raise RulesFileError("rules file must contain a JSON object")

    schema_version = data.get("schema_version", 1)
    if schema_version != SCHEMA_VERSION:
        raise RulesFileError(
            f"unsupported schema_version {schema_version!r} "
            f"(this plugin supports version {SCHEMA_VERSION})"
        )

    raw_rules = data.get("rules")
    if raw_rules is None:
        raise RulesFileError("rules file missing top-level 'rules' list")
    if not isinstance(raw_rules, list):
        raise RulesFileError("'rules' must be a list")

    valid_rules = []
    errors = []
    for i, raw in enumerate(raw_rules):
        try:
            valid_rules.append(_validate_rule(raw, i))
        except RuleValidationError as e:
            errors.append(e)

    return valid_rules, errors
