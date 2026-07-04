import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stashapi.log as log
from stashapi.stashapp import StashInterface

from entrypoint import process_scene, should_process_update, PLUGIN_DIR, RELEVANT_UPDATE_FIELDS


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

    scene_id = hook_ctx["id"]
    hook_type = hook_ctx["type"]
    changed_fields = hook_ctx.get("inputFields", {}) or {}

    log.debug(f"[CustomRules] Hook invoked: {hook_type} on scene {scene_id}")

    if hook_type == "Scene.Update.Post" and not should_process_update(changed_fields):
        log.debug(
            f"[CustomRules] No relevant fields changed ({RELEVANT_UPDATE_FIELDS}); "
            f"skipping Scene.Update.Post"
        )
        return

    if hook_type in ("Scene.Create.Post", "Scene.Update.Post"):
        scene = stash.find_scene(scene_id)
        if scene:
            process_scene(stash, scene, settings, hook_type)
        else:
            log.debug(f"[CustomRules] Scene {scene_id} not found; skipping")


if __name__ == "__main__":
    main()
