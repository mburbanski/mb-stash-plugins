# Custom Rules Engine for Stash

A modular, extensible metadata-automation engine for the Stash media server.
Define rules — as JSON, no code — that watch for scene events, check
conditions against scene metadata, and automatically apply changes.

This document has two parts:

- **[User Guide](#user-guide)** — how to install the plugin and write rules.
- **[Architecture Guide](#architecture-guide)** — how the plugin is built
  internally, for future development.

---

## User Guide

### Installation

1. Place the plugin folder (containing `CustomRulesEngine.yml`,
   `CustomRulesEngine.py`, `hooks.py`, `entrypoint.py`, `engine.py`,
   `schema.py`, `resolvers.py`) in your Stash plugins directory.
2. Create a `config.json` in the same folder to define your rules (see
   below), or point the plugin's `rules_file` setting at a file elsewhere.
3. Restart Stash or reload plugins.

### How it works, in one paragraph

When a scene is created or updated, Stash invokes this plugin. The plugin
loads your rules file, and for each rule checks whether its **conditions**
match the scene. If they do, it runs the rule's **actions**, which update
scene fields. Rules that don't apply to a given scene are silently skipped;
rules that are *malformed* (bad regex, missing fields, etc.) are reported as
errors in the Stash logs and skipped, so a typo in one rule doesn't stop the
rest of your rules file from working.

### Rules file format

Rules live in a JSON file with this top-level shape:

```json
{
  "schema_version": 1,
  "rules": [
    { "...": "one rule object per entry" }
  ]
}
```

`schema_version` is optional (files without it are treated as version 1) —
it exists so the plugin can tell you clearly if a rules file was written for
a newer format than it understands, rather than failing in a confusing way.

Each rule looks like:

```json
{
  "name": "Rule Name",
  "events": ["Scene.Create.Post", "Scene.Update.Post"],
  "conditions": [
    { "type": "regex", "field": "code", "pattern": "FOO-(\\d{7})" }
  ],
  "actions": [
    { "type": "set", "field": "code", "template": "FOO-{1}", "mode": "always" }
  ]
}
```

- **`name`** — shown in logs when the rule matches or fails validation.
  Optional; defaults to `rule #<index>`.
- **`events`** — which hook events this rule should run on. Optional; if
  omitted, the rule is considered for every event the plugin is invoked on.
- **`conditions`** — a list of checks that must **all** pass for the rule's
  actions to run. A rule must have at least one condition (a rule with zero
  conditions can never match, and is rejected as invalid rather than
  silently never firing).
- **`actions`** — what to do when conditions pass. A rule must have at least
  one action (a rule with zero actions would match and do nothing, which is
  almost certainly a mistake, so it's also rejected as invalid).

### Conditions

Currently supported condition type:

#### `regex`

Evaluates a regex against a scene field. Required: `field`, `pattern`.

- `field` can be any scene field (`code`, `title`, `details`, ...), or the
  special value `file.path`, which matches against the scene's *primary*
  file's path.
- If `field` resolves to a list (e.g. `urls`, `tags`), each string element
  is tested and the first match wins.
- Capture groups from the match are available to that rule's actions as
  `{1}`, `{2}`, etc.

```json
{ "type": "regex", "field": "file.path", "pattern": "[Ff][Ff][Oo].*?(\\d{7})" }
```

Nested/indexed fields can be reached with dot notation, e.g. `files.0.path`.

### Actions

Two action types are currently supported:

#### `set` — scalar fields

Sets a single field to a computed value. Only `mode: "always"` is
supported. Skips the update if the field already holds that exact value
(this is what prevents update-triggered infinite loops).

```json
{ "type": "set", "field": "code", "template": "FOO-{1}", "mode": "always" }
```

#### `add` — array fields

Appends a computed value to a list field (e.g. `urls`) if not already
present. Only `mode: "if_missing"` is supported.

```json
{ "type": "add", "field": "urls", "template": "https://example.com/foo-{1}", "mode": "if_missing" }
```

> **Known quirk:** "already present" is currently checked with a
> *substring* match, not an exact match — adding `"12345"` is considered
> already-present if any existing entry merely *contains* `"12345"`
> anywhere. This is a known rough edge, not a deliberate design choice; see
> [Known Limitations](#known-limitations) below.

### Capture-group substitution

Any action `template` can reference the matched regex's capture groups:

- Regex: `FOO-(\d{7})` against `FOO-1234567`
- Template: `"https://example.com/foo-{1}"`
- Result: `"https://example.com/foo-1234567"`

> **Known quirk:** if a rule has *multiple* regex conditions on the same
> list field, only the capture groups from the **last** condition evaluated
> are available to actions — earlier matches' groups are overwritten. See
> [Known Limitations](#known-limitations).

### Example: two rules working together

```json
{
  "schema_version": 1,
  "rules": [
    {
      "name": "FOO extract Code from Path",
      "events": ["Scene.Create.Post", "Scene.Update.Post"],
      "conditions": [
        { "type": "regex", "field": "file.path", "pattern": "[Ff][Ff][Oo].*?(\\d{7})" }
      ],
      "actions": [
        { "type": "set", "field": "code", "template": "FOO-{1}", "mode": "always" }
      ]
    },
    {
      "name": "FOO add URLs from Code",
      "events": ["Scene.Create.Post", "Scene.Update.Post"],
      "conditions": [
        { "type": "regex", "field": "code", "pattern": "FOO-(\\d{7})" }
      ],
      "actions": [
        { "type": "add", "field": "urls", "template": "https://example.com/foo-{1}", "mode": "if_missing" },
        { "type": "add", "field": "urls", "template": "https://example.com/bar-{1}", "mode": "if_missing" }
      ]
    }
  ]
}
```

These rules are independent: the second fires whether `code` was set by the
first rule, entered manually, or set by another plugin entirely.

### Troubleshooting

Check the Stash plugin log for lines prefixed `[CustomRules]`:

- `Loaded N valid rule(s) from ...` — confirms the file was found and
  parsed; a trailing `(M skipped due to validation errors)` means some
  rules in the file are malformed (see the accompanying error lines for
  which ones and why).
- `Rules file not found` / `not valid JSON` / `failed validation` — the
  whole file failed to load; no rules will run until this is fixed.
- `Rule 'X' failed during evaluation` — a rule passed load-time validation
  but hit a problem against a specific scene (e.g. an `add` action targeting
  a field that turned out not to be a list).
- `No relevant fields changed; skipping Scene.Update.Post` — normal, not an
  error: an update happened but didn't touch a field any rule cares about.

---

## Architecture Guide

This section is for whoever (probably future-you) needs to extend the
plugin later. The codebase is split so that new condition types, action
types, metadata fields, and entity triggers can each be added by adding
code in one place, without touching the others.

### Module map

```
CustomRulesEngine.yml   Plugin manifest: name, exec command, hook registration, settings.
CustomRulesEngine.py    Thin entry script: reads stdin, resolves the hook, calls entrypoint.
hooks.py                Registry of entity types (Scene, ...) and how to fetch/update each.
entrypoint.py           I/O glue: loads + validates the rules file, applies changes via Stash API.
schema.py               Rule/Condition/Action dataclasses + load-time validation.
engine.py               Pure rule evaluation. No I/O, no Stash API, fully unit-testable.
resolvers.py            Field access: dotted-path lookups + "virtual" fields like file.path.
```

### Data flow for one hook invocation

1. Stash invokes `CustomRulesEngine.py` with a JSON payload on stdin,
   including a `hookContext` (event type + entity id + changed fields).
2. `CustomRulesEngine.py` asks `hooks.resolve_hook_config()` which
   `EntityHooks` config (if any) owns this event type.
3. For update events, it checks whether any of that entity type's
   `relevant_update_fields` actually changed — if not, it exits early
   without touching the rules file at all.
4. It fetches the full entity via the resolved config's `fetch` callable
   (e.g. `stash.find_scene`) and hands off to `entrypoint.process_entity()`.
5. `process_entity()` loads the rules file: `entrypoint.load_rules()` reads
   the JSON and passes it to `schema.validate_rules_data()`, which returns
   validated `Rule` objects (bad rules are dropped and logged individually).
6. `engine.run_rules()` evaluates each valid `Rule` against the entity —
   pure computation, no side effects — and returns a list of
   `(rule, planned_changes)` for rules that matched.
7. `process_entity()` walks that list and calls
   `entrypoint.apply_changes()`, which uses the resolved config's `apply`
   callable (e.g. `stash.update_scene`) to persist each rule's changes.

### Extension points

**Add a new condition type** (e.g. `equals`, `contains`):
- Add required fields to `schema.CONDITION_TYPE_FIELDS`.
- Add validation logic to `schema._validate_condition()` if the type needs
  more than a required-fields check (regex compilation is the existing
  example).
- Add a handler function to `engine.py` and register it in
  `engine.CONDITION_HANDLERS`.

**Add a new action type** (e.g. `remove`, `add_tag`):
- Add required fields + supported mode(s) to `schema.ACTION_TYPE_SPECS`.
- Add a handler function to `engine.py` and register it in
  `engine.ACTION_HANDLERS`. Handlers return a `PlannedChange` or `None`
  (no-op) — they must not call the Stash API directly, to keep `engine.py`
  pure and dry-run-able.

**Expose a new metadata field to conditions/actions:**
- If it's a plain nested field, no change needed — `resolvers.resolve_field`
  already handles dotted paths.
- If it needs custom logic (like `file.path` picking the primary file), add
  a resolver function to `resolvers.FIELD_RESOLVERS`.

**Add a new entity type** (Performer, Studio, Tag, Image, ...):
- Add an `EntityHooks` entry to `hooks.HOOK_REGISTRY` (a commented example
  for `Performer` is already in `hooks.py`).
- Register the new `triggeredBy` events in `CustomRulesEngine.yml`.
- Nothing in `entrypoint.py` or `CustomRulesEngine.py` needs to change.
- Note: `resolvers.FIELD_RESOLVERS` is currently a single flat namespace
  shared across all entity types. `file.path` only makes sense for
  entities with a `files` list. This hasn't caused a collision yet because
  only Scene hooks exist — worth revisiting (e.g. namespacing resolvers by
  entity type) once a second entity type is actually added.

### Known limitations

Carried over from earlier versions and not yet addressed, listed here so
they aren't rediscovered by accident:

- **Capture-group overwrite:** if a rule has multiple `regex` conditions
  targeting the same list field, only the last condition's match is kept
  for `{1}`/`{2}` substitution in actions — earlier conditions' capture
  groups are lost.
- **`add` dedup is substring-based, not exact-match:** `already_present`
  in `engine._action_add` uses `in`, so adding `"12345"` is skipped if any
  existing entry merely contains that substring anywhere.
- **No rule ordering/priority control** beyond file order, and no
  `stop_on_match` to short-circuit remaining rules.
- **Rules file is reloaded from disk on every hook invocation** — fine at
  small scale, wasteful on bulk imports/updates.
- **No dry-run mode yet** — `engine.py` is already structured to support
  one (`plan_actions()` never touches the Stash API), it just isn't wired
  up to an entrypoint yet.

### Roadmap

Roughly in priority order, building on the structure above:

1. **Operational quality-of-life** — cache the parsed rules file with an
   mtime check instead of reloading every event; add a CLI/dry-run mode
   that evaluates `engine.py` against a sample entity dict and prints what
   would change, without calling Stash; add structured "why did/didn't this
   rule match" trace output.
2. **New condition types** — `equals`, `contains`, `in`, `not_regex`,
   `metadata_exists`, file-attribute conditions (resolution, size,
   duration).
3. **New action types** — `remove`, `replace_all`, `set_if_missing`,
   `append_text`, `set_studio`, `add_tag`, `add_performer` (the last three
   implying a lookup/resolve-or-create step against the Stash API, which
   `engine.py`'s current "pure, no I/O" boundary will need to account for).
4. **Rule-level flow control** — `priority` for ordering, `stop_on_match`
   to halt further rule evaluation once one fires.
5. **New entity types** — Performer, Studio, Tag, Image hooks, using the
   `hooks.py` registry seam described above.
6. **Rule management UI** — a GraphQL endpoint / in-app UI to create, edit,
   test, and reorder rules visually, built on the validated schema in
   `schema.py` rather than hand-edited JSON.
