"""
Entity hook registry.

Everything the entrypoint needs to know about a *kind* of Stash entity
(Scene today; Performer/Studio/Tag/Image later) lives in one EntityHooks
record: which hookContext "type" values mean create vs. update, which
fields on an update are worth reprocessing for, how to fetch the full
entity, and how to persist a set of field changes back to Stash.

Adding support for a new entity type is meant to be additive: define a new
EntityHooks instance, add it to HOOK_REGISTRY, and register the new
triggeredBy events in CustomRulesEngine.yml. Nothing in entrypoint.py or
CustomRulesEngine.py should need to change.
"""

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class EntityHooks:
    """
    entity_type            - label used in log messages (e.g. "Scene")
    create_events          - hookContext "type" values that always trigger
                              a rule run (e.g. ("Scene.Create.Post",))
    update_events           - hookContext "type" values that trigger a run
                              only if a relevant field changed
                              (e.g. ("Scene.Update.Post",))
    relevant_update_fields  - field names whose change on an update event is
                              worth re-running rules for; avoids
                              reprocessing on unrelated edits
    fetch                   - (stash, entity_id) -> entity dict or None
    apply                   - (stash, entity_id, field_updates: dict) -> None;
                              persists planned changes back to Stash
    """
    entity_type: str
    create_events: tuple
    update_events: tuple
    relevant_update_fields: tuple
    fetch: Callable
    apply: Callable

    @property
    def all_events(self) -> tuple:
        return self.create_events + self.update_events


SCENE_HOOKS = EntityHooks(
    entity_type="Scene",
    create_events=("Scene.Create.Post",),
    update_events=("Scene.Update.Post",),
    relevant_update_fields=("code", "files", "path", "urls"),
    fetch=lambda stash, entity_id: stash.find_scene(entity_id),
    apply=lambda stash, entity_id, update: stash.update_scene({"id": entity_id, **update}),
)

# Register additional entity types here as they're supported, e.g.:
#
# PERFORMER_HOOKS = EntityHooks(
#     entity_type="Performer",
#     create_events=("Performer.Create.Post",),
#     update_events=("Performer.Update.Post",),
#     relevant_update_fields=("name", "aliases", "urls"),
#     fetch=lambda stash, entity_id: stash.find_performer(entity_id),
#     apply=lambda stash, entity_id, update: stash.update_performer({"id": entity_id, **update}),
# )
#
# ...and add it to HOOK_REGISTRY below. Remember to also add the new
# triggeredBy events to CustomRulesEngine.yml, and Rule "events" lists that
# should fire for the new entity type.
HOOK_REGISTRY: tuple = (SCENE_HOOKS,)


def resolve_hook_config(hook_type: str) -> Optional[EntityHooks]:
    """Find the EntityHooks config that owns this hookContext 'type' value, if any."""
    for cfg in HOOK_REGISTRY:
        if hook_type in cfg.all_events:
            return cfg
    return None
