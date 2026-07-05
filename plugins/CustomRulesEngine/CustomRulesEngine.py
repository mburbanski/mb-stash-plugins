import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stashapi.log as log
from stashapi.stashapp import StashInterface

from entrypoint import process_entity, should_process_update, PLUGIN_DIR
from hooks import resolve_hook_config


def main():
    json_input = json.loads(sys.stdin.read())
    server_connection = json_input["server_connection"]
    stash = StashInterface(server_connection)
    config = stash.get_configuration()

    settings = {"rules_file": f"{PLUGIN_DIR}/config.json"}
    if "CustomRulesEngine" in config.get("plugins", {}):
        settings.update(config["plugins"]["CustomRulesEngine"])

    args = json_input.get("args", {})
    hook_ctx = args.get("hookContext")
    if not hook_ctx:
        return

    entity_id = hook_ctx["id"]
    hook_type = hook_ctx["type"]
    changed_fields = hook_ctx.get("inputFields", {}) or {}

    log.debug(f"[CustomRules] Hook invoked: {hook_type} on entity {entity_id}")

    hook_config = resolve_hook_config(hook_type)
    if hook_config is None:
        # Not necessarily an error: could be a hook type nothing is
        # registered for yet.
        log.debug(f"[CustomRules] No entity hook config registered for '{hook_type}'; skipping")
        return

    if hook_type in hook_config.update_events and not should_process_update(hook_config, changed_fields):
        log.debug(
            f"[CustomRules] No relevant fields changed "
            f"({hook_config.relevant_update_fields}); skipping {hook_type}"
        )
        return

    entity = hook_config.fetch(stash, entity_id)
    if entity:
        process_entity(stash, hook_config, entity, settings, hook_type)
    else:
        log.debug(f"[CustomRules] {hook_config.entity_type} {entity_id} not found; skipping")


if __name__ == "__main__":
    main()
