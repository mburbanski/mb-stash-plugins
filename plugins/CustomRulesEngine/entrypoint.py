"""
I/O and Stash-API glue.

This is where disk access, logging, and StashInterface calls live, so that
engine.py can stay pure and independently testable. CustomRulesEngine.py
(the plugin's actual exec target) is a thin script that parses stdin and
hands off to the functions here.
"""

import json
import os

import stashapi.log as log

from engine import run_rules, PlannedChange

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# Scene fields that, if changed, warrant re-running rules on
# Scene.Update.Post. Avoids reprocessing on unrelated field edits.
RELEVANT_UPDATE_FIELDS = ("code", "files", "path", "urls")


# ------------------------------------------------------------
# Rules file loading
# ------------------------------------------------------------
def load_rules(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rules = data.get("rules", [])
        log.info(f"[CustomRules] Loaded {len(rules)} rules from {path}")
        return rules
    except Exception as e:
        log.error(f"[CustomRules] ERROR loading rules from {path}: {e}")
        return []


def resolve_rules_file(settings: dict) -> str:
    rules_file = settings.get("rules_file") or os.path.join(PLUGIN_DIR, "config.json")
    return rules_file.replace("{pluginDir}", PLUGIN_DIR)


# ------------------------------------------------------------
# Applying planned changes
# ------------------------------------------------------------
def apply_changes(stash, entity_id, changes: list[PlannedChange]) -> None:
    """Apply a batch of PlannedChange objects to a scene via the Stash API."""
    if not changes:
        return

    update = {"id": entity_id}
    for change in changes:
        update[change.field] = change.new_value
        log.info(f"[CustomRules] Scene {entity_id}: {change.reason}")

    stash.update_scene(update)


def _log_rule_error(rule: dict, error: Exception) -> None:
    log.error(f"[CustomRules] Rule '{rule.get('name', '?')}': {error}")


# ------------------------------------------------------------
# Scene processing
# ------------------------------------------------------------
def process_scene(stash, scene: dict, settings: dict, hook_type: str) -> None:
    rules_file = resolve_rules_file(settings)
    rules = load_rules(rules_file)

    if not rules:
        log.debug(f"[CustomRules] Scene {scene['id']}: no rules loaded; skipping")
        return

    results = run_rules(scene, rules, hook_type=hook_type, on_error=_log_rule_error)

    for rule, changes in results:
        log.info(f"[CustomRules] Scene {scene['id']}: rule matched -> {rule.get('name')}")
        apply_changes(stash, scene["id"], changes)


def should_process_update(changed_fields: dict) -> bool:
    """Whether a Scene.Update.Post event touched a field rules might care about."""
    if not changed_fields:
        return False
    return any(f in changed_fields for f in RELEVANT_UPDATE_FIELDS)
