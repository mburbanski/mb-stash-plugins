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

# --------------------------------------------------------------------
# NOTE ON METHOD NAMES BELOW: stashapi's public docs/examples only ever
# show StashInterface.find_scene()/update_scene() directly. The
# find_performer/update_performer/find_studio/update_studio/find_tag/
# update_tag/find_gallery/update_gallery/find_image/update_image names
# below follow that same naming convention and are very likely correct,
# but -- unlike find_scene, which we've been running against successfully
# this whole time -- these specific names haven't been confirmed against
# a real stashapi installation. Since stashapi is already installed and
# running on the machine this plugin runs on, the fastest way to confirm
# is to check it directly there, e.g.:
#
#   python3 -c "from stashapi.stashapp import StashInterface as S; \
#     print([m for m in dir(S) if 'performer' in m or 'studio' in m \
#     or 'tag' in m or 'gallery' in m or 'image' in m])"
#
# run from an environment where stashapi is installed (or grep the
# installed stashapp.py directly). If any name below doesn't match,
# it's a one-line fix in the corresponding lambda.
# --------------------------------------------------------------------

PERFORMER_HOOKS = EntityHooks(
    entity_type="Performer",
    create_events=("Performer.Create.Post",),
    update_events=("Performer.Update.Post",),
    relevant_update_fields=("name", "aliases", "urls", "details"),
    fetch=lambda stash, entity_id: stash.find_performer(entity_id),
    apply=lambda stash, entity_id, update: stash.update_performer({"id": entity_id, **update}),
)

STUDIO_HOOKS = EntityHooks(
    entity_type="Studio",
    create_events=("Studio.Create.Post",),
    update_events=("Studio.Update.Post",),
    relevant_update_fields=("name", "aliases", "urls", "details"),
    fetch=lambda stash, entity_id: stash.find_studio(entity_id),
    apply=lambda stash, entity_id, update: stash.update_studio({"id": entity_id, **update}),
)

TAG_HOOKS = EntityHooks(
    entity_type="Tag",
    create_events=("Tag.Create.Post",),
    # Tag.Merge.Post deliberately excluded for now -- "two tags became one"
    # doesn't have the same "the object changed" semantics as Update, and
    # deserves separate deliberate handling rather than being folded in
    # here.
    update_events=("Tag.Update.Post",),
    relevant_update_fields=("name", "aliases", "description"),
    fetch=lambda stash, entity_id: stash.find_tag(entity_id),
    apply=lambda stash, entity_id, update: stash.update_tag({"id": entity_id, **update}),
)

GALLERY_HOOKS = EntityHooks(
    entity_type="Gallery",
    create_events=("Gallery.Create.Post",),
    update_events=("Gallery.Update.Post",),
    relevant_update_fields=("title", "code", "urls", "details", "photographer"),
    fetch=lambda stash, entity_id: stash.find_gallery(entity_id),
    apply=lambda stash, entity_id, update: stash.update_gallery({"id": entity_id, **update}),
)

IMAGE_HOOKS = EntityHooks(
    entity_type="Image",
    create_events=("Image.Create.Post",),
    update_events=("Image.Update.Post",),
    relevant_update_fields=("title", "code", "urls", "details"),
    fetch=lambda stash, entity_id: stash.find_image(entity_id),
    apply=lambda stash, entity_id, update: stash.update_image({"id": entity_id, **update}),
)

# Deliberately deferred (see design discussion): Movie/Group (naming is
# mid-transition upstream), SceneMarker and GalleryChapter (sub-entities
# of Scene/Gallery, sparse and ID-relationship-heavy field sets, unclear
# value for this plugin's typical metadata-cleanup use case).
HOOK_REGISTRY: tuple = (
    SCENE_HOOKS,
    PERFORMER_HOOKS,
    STUDIO_HOOKS,
    TAG_HOOKS,
    GALLERY_HOOKS,
    IMAGE_HOOKS,
)


def resolve_hook_config(hook_type: str) -> Optional[EntityHooks]:
    """Find the EntityHooks config that owns this hookContext 'type' value, if any."""
    for cfg in HOOK_REGISTRY:
        if hook_type in cfg.all_events:
            return cfg
    return None