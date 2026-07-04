import sys
import os
import json
import re

import stashapi.log as log
from stashapi.stashapp import StashInterface

PLUGIN_DIR = os.path.dirname(__file__)


# ------------------------------------------------------------
# Utility: Load rules from JSON
# ------------------------------------------------------------
def load_rules(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rules = data.get("rules", [])
        log.info(f"[CustomRules] Loaded {len(rules)} rules from {path}")
        return rules
    except Exception as e:
        log.error(f"[CustomRules] ERROR loading rules from {path}: {e}")
        return []


# ------------------------------------------------------------
# Utility: Resolve nested fields like "files.0.path"
# ------------------------------------------------------------
def resolve_field(obj: dict, field_path: str):
    parts = field_path.split(".")
    cur = obj
    for p in parts:
        if isinstance(cur, list):
            try:
                idx = int(p)
                cur = cur[idx]
            except Exception:
                return None
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
            if cur is None:
                return None
    return cur


# ------------------------------------------------------------
# Utility: Substitute capture groups {1}, {2}, etc.
# ------------------------------------------------------------
def substitute(template: str, match: re.Match) -> str:
    out = template
    if match:
        for i, g in enumerate(match.groups(), start=1):
            out = out.replace(f"{{{i}}}", g)
    return out


# ------------------------------------------------------------
# Condition Evaluation
# ------------------------------------------------------------
def get_primary_file(scene: dict):
    files = scene.get("files", []) or []
    if not files:
        return None
    primary = next(
        (f for f in files if f["id"] == scene.get("primary_file_id")),
        files[0],
    )
    return primary


def evaluate_conditions(scene: dict, rule: dict):
    """
    Supported:
      - type = "regex"
        - field can be "file.path" (special)
        - or any scene field (scalar or list)
    Returns:
      - match object (for capture groups) if all conditions pass
      - None if any condition fails
    """
    conditions = rule.get("conditions", [])
    if not conditions:
        return None

    last_match = None

    for cond in conditions:
        ctype = cond.get("type")
        field = cond.get("field")
        pattern = cond.get("pattern")

        if ctype != "regex":
            log.error(f"[CustomRules] Unsupported condition type: {ctype}")
            return None

        # --- Special case: file.path ---
        if field == "file.path":
            primary = get_primary_file(scene)
            value = primary.get("path") if primary else None
        else:
            value = resolve_field(scene, field)

        if value is None:
            return None

        # --- NEW: If the field is a list, test each element ---
        if isinstance(value, list):
            match = None
            for item in value:
                if isinstance(item, str):
                    try:
                        m = re.search(pattern, item)
                    except re.error as e:
                        log.error(f"[CustomRules] Invalid regex '{pattern}': {e}")
                        return None

                    if m:
                        match = m
                        break

            if not match:
                return None

            last_match = match
            continue

        # --- Scalar field (string) ---
        if not isinstance(value, str):
            # Can't regex match non-string scalars
            return None

        try:
            m = re.search(pattern, value)
        except re.error as e:
            log.error(f"[CustomRules] Invalid regex '{pattern}': {e}")
            return None

        if not m:
            return None

        last_match = m

    return last_match



# ------------------------------------------------------------
# Action Execution
# ------------------------------------------------------------
def apply_actions(stash: StashInterface, scene: dict, rule: dict, match: re.Match):
    """
    Implemented:
      - type = "set" (scalar fields, e.g. code)
          modes: "always"
      - type = "add" (array fields, e.g. urls)
          modes: "if_missing"
    """
    scene_id = scene["id"]
    actions = rule.get("actions", [])

    for action in actions:
        atype = action.get("type")
        field = action.get("field")
        template = action.get("template", "")
        mode = action.get("mode", "always")

        new_value = substitute(template, match)

        # --- SET (scalar) ---
        if atype == "set":
            current_value = scene.get(field)

            if mode == "always":
                if current_value == new_value:
                    log.debug(
                        f"[CustomRules] Scene {scene_id}: {field} already = {new_value}; skipping"
                    )
                    continue

                log.info(f"[CustomRules] Scene {scene_id}: setting {field} -> {new_value}")
                stash.update_scene({"id": scene_id, field: new_value})
                scene[field] = new_value
            else:
                log.error(f"[CustomRules] Unsupported mode for 'set': {mode}")

        # --- ADD (array) ---
        elif atype == "add":
            existing = scene.get(field)

            if existing is None:
                existing = []
            if not isinstance(existing, list):
                log.error(f"[CustomRules] Field '{field}' is not a list; cannot 'add'")
                continue

            if mode == "if_missing":
                # NEW LOGIC: substring match instead of exact match
                already_present = any(new_value in url for url in existing)

                if not already_present:
                    log.info(f"[CustomRules] Scene {scene_id}: adding to {field} -> {new_value}")
                    updated = existing + [new_value]
                    stash.update_scene({"id": scene_id, field: updated})
                    scene[field] = updated
                else:
                    log.debug(
                        f"[CustomRules] Scene {scene_id}: substring match found in {field}; skipping add"
                    )
            else:
                log.error(f"[CustomRules] Unsupported mode for 'add': {mode}")

        else:
            log.error(f"[CustomRules] Unsupported action type: {atype}")


# ------------------------------------------------------------
# Main Scene Processing
# ------------------------------------------------------------
def process_scene(stash: StashInterface, scene: dict, settings: dict, hook_type: str):
    rules_file = settings.get("rules_file") or os.path.join(PLUGIN_DIR, "config.json")
    rules_file = rules_file.replace("{pluginDir}", PLUGIN_DIR)

    rules = load_rules(rules_file)
    if not rules:
        log.debug(f"[CustomRules] Scene {scene['id']}: no rules loaded; skipping")
        return

    for rule in rules:
        events = rule.get("events")
        if events and hook_type not in events:
            continue

        match = evaluate_conditions(scene, rule)
        if not match:
            continue

        log.info(f"[CustomRules] Scene {scene['id']}: rule matched -> {rule.get('name')}")
        apply_actions(stash, scene, rule, match)


# ------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------
json_input = json.loads(sys.stdin.read())
FRAGMENT_SERVER = json_input["server_connection"]
stash = StashInterface(FRAGMENT_SERVER)
config = stash.get_configuration()

settings = {
    "rules_file": f"{PLUGIN_DIR}/config.json"
}

if "CustomRulesEngine" in config.get("plugins", {}):
    settings.update(config["plugins"]["CustomRulesEngine"])

args = json_input.get("args", {})
hook_ctx = args.get("hookContext")

if hook_ctx:
    scene_id = hook_ctx["id"]
    hook_type = hook_ctx["type"]
    changed_fields = hook_ctx.get("inputFields", {}) or {}

    log.debug(f"[CustomRules] Hook invoked: {hook_type} on scene {scene_id}")

    if hook_type == "Scene.Update.Post":
        # If nothing changed, skip
        if not changed_fields:
            log.debug("[CustomRules] No fields changed; skipping Scene.Update.Post")
            sys.exit(0)

        # Only run rules if relevant fields changed
        relevant = ("code", "files", "path", "urls")
        if not any(f in changed_fields for f in relevant):
            log.debug(
                f"[CustomRules] No relevant fields changed ({relevant}); skipping Scene.Update.Post"
            )
            sys.exit(0)

    if hook_type in ("Scene.Create.Post", "Scene.Update.Post"):
        scene = stash.find_scene(scene_id)
        if scene:
            process_scene(stash, scene, settings, hook_type)
        else:
            log.debug(f"[CustomRules] Scene {scene_id} not found; skipping")
