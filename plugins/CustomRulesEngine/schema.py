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
shape changes in a backwards-incompatible way. Files without a
schema_version are treated as version 1.

CONDITION SHAPE, v2: conditions are now {field, modifier, values}, where
`modifier` is one of Stash's own CriterionModifier-style names (EQUALS,
INCLUDES, MATCHES_REGEX, IS_NULL, BETWEEN, ...) rather than the old
regex-only {type: "regex", field, pattern} shape. Existing rules files
using the old shape are transparently upgraded at load time (see
_normalize_legacy_condition) -- nobody needs to hand-edit an existing
config.json for this change to take effect.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

SCHEMA_VERSION = 1

# Modifier -> how many values it expects in "values". Mirrors Stash's own
# CriterionModifier semantics (IS_NULL/NOT_NULL take none; BETWEEN/
# NOT_BETWEEN take two; everything else takes exactly one). Extend this
# alongside engine.MODIFIER_HANDLERS when a new modifier is added.
MODIFIER_ARITY = {
    "EQUALS": 1,
    "NOT_EQUALS": 1,
    "INCLUDES": 1,
    "EXCLUDES": 1,
    "MATCHES_REGEX": 1,
    "NOT_MATCHES_REGEX": 1,
    "GREATER_THAN": 1,
    "LESS_THAN": 1,
    "IS_NULL": 0,
    "NOT_NULL": 0,
    "BETWEEN": 2,
    "NOT_BETWEEN": 2,
}

REGEX_MODIFIERS = ("MATCHES_REGEX", "NOT_MATCHES_REGEX")

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
    field: str
    modifier: str
    values: list = field(default_factory=list)
    # Only set (and only meaningful) for MATCHES_REGEX / NOT_MATCHES_REGEX.
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
# Backward compatibility: upgrade the old regex-only condition shape
# ------------------------------------------------------------
def _normalize_legacy_condition(raw: dict) -> dict:
    """
    Rules written before the modifier-based condition schema used
    {"type": "regex", "field": ..., "pattern": ...}. Transparently upgrade
    that shape to {"field": ..., "modifier": "MATCHES_REGEX",
    "values": [pattern]} so existing rules files keep working completely
    unchanged -- nobody should have to hand-edit a working config.json
    because the plugin's internals changed shape.
    """
    if isinstance(raw, dict) and raw.get("type") == "regex" and "modifier" not in raw:
        upgraded = dict(raw)
        upgraded["modifier"] = "MATCHES_REGEX"
        upgraded["values"] = [raw.get("pattern")]
        upgraded.pop("type", None)
        upgraded.pop("pattern", None)
        return upgraded
    return raw


# ------------------------------------------------------------
# Per-item validation
# ------------------------------------------------------------
def _validate_condition(raw: dict, rule_index: int, rule_name: str) -> Condition:
    if not isinstance(raw, dict):
        raise RuleValidationError(rule_index, rule_name, "condition must be an object")

    raw = _normalize_legacy_condition(raw)

    field_name = raw.get("field")
    if not field_name:
        raise RuleValidationError(rule_index, rule_name, "condition missing required field 'field'")

    modifier = raw.get("modifier")
    if modifier not in MODIFIER_ARITY:
        raise RuleValidationError(
            rule_index, rule_name,
            f"unsupported modifier {modifier!r} (known: {sorted(MODIFIER_ARITY)})",
        )

    values = raw.get("values", [])
    if not isinstance(values, list):
        raise RuleValidationError(rule_index, rule_name, "'values' must be a list")

    expected_arity = MODIFIER_ARITY[modifier]
    if len(values) != expected_arity:
        raise RuleValidationError(
            rule_index, rule_name,
            f"modifier '{modifier}' expects {expected_arity} value(s) in 'values', got {len(values)}",
        )

    compiled_pattern = None
    if modifier in REGEX_MODIFIERS:
        pattern = values[0]
        try:
            compiled_pattern = re.compile(pattern)
        except re.error as e:
            raise RuleValidationError(rule_index, rule_name, f"invalid regex '{pattern}': {e}")

    return Condition(field=field_name, modifier=modifier, values=values, compiled_pattern=compiled_pattern)


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