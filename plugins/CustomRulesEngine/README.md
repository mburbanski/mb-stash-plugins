# Custom Rules Engine for Stash

A modular, extensible metadata-automation engine for the Stash media server.  
This plugin allows you to define rules that automatically update scene metadata based on:

- Events (e.g., Scene.Create.Post, Scene.Update.Post)
- Conditions (e.g., regex matches on file paths or metadata fields)
- Actions (e.g., set a field, add to an array, substitute capture groups)

The goal is to provide a flexible, declarative system for automating metadata cleanup, enrichment, and normalization — without writing custom code for each behavior.

---

## Current Capabilities

### 1. JSON-Based Rule Definitions

Rules are defined in a single JSON file (config.json) using a clean, extensible schema.

Example rule structure:

```json
{
  "name": "Rule Name",
  "events": ["Scene.Create.Post", "Scene.Update.Post"],
  "conditions": [
    {
      "type": "regex",
      "field": "code",
      "pattern": "FOO-(\\d{7})"
    }
  ],
  "actions": [
    {
      "type": "set",
      "field": "code",
      "template": "FOO-{1}",
      "mode": "always"
    }
  ]
}
```

This schema is designed to grow over time without breaking backward compatibility.

---

### 2. Event-Driven Execution

Rules can specify which Stash events they respond to:

- Scene.Create.Post  
- Scene.Update.Post  

The engine automatically filters rules based on the event type.

---

### 3. Condition Evaluation

Currently supported condition type:

#### Regex Condition

- Evaluates a regex against any scene field (e.g., code, title, details)
- Supports special field file.path for matching against the primary file path
- Capture groups are passed to actions for substitution

Example:

```json
{
  "type": "regex",
  "field": "file.path",
  "pattern": "[Ff][Ff][Oo].*?(\\d{7})"
}
```

---

### 4. Action Execution

Two action types are currently implemented:

#### A. set (scalar fields)

Updates a single metadata field.

- Supports mode: "always"
- Skips updates when the value is unchanged (prevents infinite loops)

Example:

```json
{
  "type": "set",
  "field": "code",
  "template": "FOO-{1}",
  "mode": "always"
}
```

#### B. add (array fields)

Adds a value to an array field (e.g., urls) if it’s not already present.

- Supports mode: "if_missing"

Example:

```json
{
  "type": "add",
  "field": "urls",
  "template": "https://example.com/foo-{1}",
  "mode": "if_missing"
}
```

---

### 5. Capture-Group Substitution

Actions can reference regex capture groups using {1}, {2}, etc.

Example:

- Regex: FOO-(\d{7})  
- Template: "https://example.com/foo-{1}"  

Result:

```
https://example.com/foo-1234567
```

---

### 6. Loop Prevention

The engine avoids infinite update loops by:

- Skipping updates when no actual metadata change would occur  
- Only running rules on Scene.Update.Post when relevant fields changed

This ensures stable, predictable behavior even when multiple rules interact.

---

## Example: Two Independent Rules Working Together

### Rule 1 — Extract Code from File Path

```json
{
  "name": "FOO extract Code from Path",
  "events": ["Scene.Create.Post", "Scene.Update.Post"],
  "conditions": [
    {
      "type": "regex",
      "field": "file.path",
      "pattern": "[Ff][Ff][Oo].*?(\\d{7})"
    }
  ],
  "actions": [
    {
      "type": "set",
      "field": "code",
      "template": "FOO-{1}",
      "mode": "always"
    }
  ]
}
```

### Rule 2 — Add URLs Based on Code

```json
{
  "name": "FOO add URLs from Code",
  "events": ["Scene.Create.Post", "Scene.Update.Post"],
  "conditions": [
    {
      "type": "regex",
      "field": "code",
      "pattern": "FOO-(\\d{7})"
    }
  ],
  "actions": [
    {
      "type": "add",
      "field": "urls",
      "template": "https://example.com/foo-{1}",
      "mode": "if_missing"
    },
    {
      "type": "add",
      "field": "urls",
      "template": "https://example.com/bar-{1}",
      "mode": "if_missing"
    }
  ]
}
```

These rules are independent — Rule 2 fires whether the code was extracted, manually entered, or set by another plugin.

---

## Future Enhancements (Planned Roadmap)

The architecture is intentionally modular so the engine can grow into a full metadata automation framework. Planned enhancements include:

---

### 1. Additional Condition Types

- equals — match exact values  
- contains — substring match  
- in — match against a list  
- not_regex — negative regex  
- metadata_exists — check for presence of a field  
- file.attribute conditions (resolution, size, duration)

---

### 2. Additional Action Types

- remove — remove from array fields  
- replace_all — overwrite entire arrays  
- set_if_missing — only set if field is empty  
- append_text — add to existing strings  
- set_studio — resolve studio by name  
- add_tag — resolve tag by name or create if missing  
- add_performer — resolve performer by name  

---

### 3. Action Modes

- if_not_equal  
- if_exists  
- if_condition (nested condition object)  
- dry_run mode for debugging  

---

### 4. Rule Priorities & Flow Control

- priority field for ordering  
- stop_on_match to halt further rule evaluation  

---

### 5. Rule Testing Tools

- A GraphQL endpoint to test rules against a sample filepath or metadata  
- A debug mode that logs:
  - which rules matched  
  - which actions would run  
  - what values would be set  

---

### 6. UI for Rule Management

Eventually, a full UI inside Stash:

- Create/edit rules visually  
- Test regex patterns  
- Preview capture groups  
- Drag-and-drop rule ordering  
- Enable/disable rules  
- Import/export rule sets  

---

### 7. Performance Optimizations

- Cache compiled regexes  
- Load rules once per plugin invocation  
- Lazy evaluation of expensive fields  

---

## Installation

1. Place the plugin folder in your Stash plugins directory  
2. Ensure `CustomRulesEngine.yml` and `CustomRulesEngine.py` are present  
3. Create or edit config.json to define your rules  
4. Restart Stash or reload plugins  

---
