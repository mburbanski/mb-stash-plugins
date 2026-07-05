"""
I/O and Stash-API glue.

This is where disk access, logging, and StashInterface calls live, so that
engine.py and schema.py can stay pure and independently testable.
CustomRulesEngine.py (the plugin's actual exec target) is a thin script that
parses stdin and hands off to the functions here.

Nothing in this module is Scene-specific: process_entity() and
apply_changes() work against whatever EntityHooks config the incoming hook
type resolves to (see hooks.py). That's the seam future entity types plug
into without touching this file.
"""

import json
import os

import stashapi.log as log

from engine import run_rules, RuleError, PlannedChange
from hooks import EntityHooks
from schema import validate_rules_data, RulesFileError, RuleValidationError, Rule

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------
# Rules file loading
# ------------------------------------------------------------
def load_rules(path: str) -> "list[Rule]":
    """
    Read, parse, and schema-validate the rules file at `path`.

    Three distinct failure levels are reported at three distinct log
    severities, so a plugin author (or, eventually, a config UI) can tell
    them apart:
      - Can't read/parse the file at all -> error, nothing loads.
      - File parses but fails schema-level checks (bad schema_version,
        wrong top-level shape) -> error, nothing loads.
      - Individual rule fails validation -> error for that rule only; the
        rest of the file still loads and runs.
    A rule whose *conditions* legitimately don't match a given entity is not
    an error at all -- that's an ordinary outcome handled later in
    run_rules(), not here.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        log.error(f"[CustomRules] Rules file not found: {path}")
        return []
    except json.JSONDecodeError as e:
        log.error(f"[CustomRules] Rules file is not valid JSON ({path}): {e}")
        return []
    except OSError as e:
        log.error(f"[CustomRules] Could not read rules file ({path}): {e}")
        return []

    try:
        rules, validation_errors = validate_rules_data(data)
    except RulesFileError as e:
        log.error(f"[CustomRules] Rules file failed validation ({path}): {e}")
        return []

    for err in validation_errors:
        log.error(f"[CustomRules] Skipping invalid rule in {path}: {err}")

    summary = f"[CustomRules] Loaded {len(rules)} valid rule(s) from {path}"
    if validation_errors:
        summary += f" ({len(validation_errors)} skipped due to validation errors)"
    log.info(summary)

    return rules


def resolve_rules_file(settings: dict) -> str:
    rules_file = settings.get("rules_file") or os.path.join(PLUGIN_DIR, "config.json")
    return rules_file.replace("{pluginDir}", PLUGIN_DIR)


# ------------------------------------------------------------
# Applying planned changes
# ------------------------------------------------------------
def apply_changes(stash, hook_config: EntityHooks, entity_id, changes: "list[PlannedChange]") -> None:
    """Apply a batch of PlannedChange objects to an entity via the Stash API."""
    if not changes:
        return

    update = {}
    for change in changes:
        update[change.field] = change.new_value
        log.info(f"[CustomRules] {hook_config.entity_type} {entity_id}: {change.reason}")

    hook_config.apply(stash, entity_id, update)


def _log_rule_error(rule: Rule, error: Exception) -> None:
    log.error(f"[CustomRules] Rule '{rule.name}' failed during evaluation: {error}")


# ------------------------------------------------------------
# Entity processing (generic across entity types)
# ------------------------------------------------------------
def process_entity(stash, hook_config: EntityHooks, entity: dict, settings: dict, hook_type: str) -> None:
    rules_file = resolve_rules_file(settings)
    rules = load_rules(rules_file)

    if not rules:
        log.debug(
            f"[CustomRules] {hook_config.entity_type} {entity['id']}: "
            f"no valid rules loaded; skipping"
        )
        return

    results = run_rules(entity, rules, hook_type=hook_type, on_error=_log_rule_error)

    for rule, changes in results:
        log.info(f"[CustomRules] {hook_config.entity_type} {entity['id']}: rule matched -> {rule.name}")
        apply_changes(stash, hook_config, entity["id"], changes)


def should_process_update(hook_config: EntityHooks, changed_fields: dict) -> bool:
    """Whether an update event touched a field this entity type's rules might care about."""
    if not changed_fields:
        return False
    return any(f in changed_fields for f in hook_config.relevant_update_fields)
