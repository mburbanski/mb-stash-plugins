// Custom Rules Engine - frontend UI
//
// Config UI, step 4: structured rule editing. The rule cards are now the
// primary editing surface -- the raw JSON view below them is generated
// live from the structured state and is read-only, purely a "here's
// exactly what will be written" preview. Saving always goes through the
// same write_rules_file_raw() path on the Python side, which validates
// with schema.py before writing anything -- nothing about that backend
// contract changed for this step.
//
// Written as plain JS (no build step): kept readable via named
// React.createElement calls and small helper functions rather than a
// deep nest, at the cost of being more verbose than JSX would be.
//
// Two things below were confirmed empirically against a real Stash
// instance rather than assumed, since guessing wrong would silently
// break this entirely:
//   - PluginApi.register.route(path, Component) argument order.
//   - Direct URL loads to a plugin route 404 at the SERVER level on this
//     Stash build -- so the config page is only reachable via in-app
//     client-side navigation (pushState + a manually dispatched
//     popstate event), never a plain <a href> or typed URL.

(function () {
  const PluginApi = window.PluginApi;
  const React = PluginApi.React;
  const { useState, useEffect, useMemo } = React;

  const el = React.createElement;

  // Must match this plugin's manifest-derived id exactly, or both the
  // settings patch below and the GraphQL calls will target the wrong
  // plugin's settings. Stash derives this from the plugin's .yml
  // filename/folder (there is no `id:` field in the manifest schema) --
  // this should be "CustomRulesEngine" to match CustomRulesEngine.yml,
  // confirmed via the console.debug further down.
  const PLUGIN_ID = "CustomRulesEngine";
  const CONFIG_ROUTE = "/plugin/custom-rules-engine";

  // Known condition/action types and event names. These mirror
  // schema.CONDITION_TYPE_FIELDS / schema.ACTION_TYPE_SPECS / hooks.py's
  // registered events on the Python side. Duplicated here rather than
  // fetched, to keep this step's scope contained -- worth replacing with
  // a read-only operation call (like read_rules_file) once new
  // condition/action types or entity types actually get added, so this
  // list can't silently drift out of sync with the Python side.
  const CONDITION_TYPES = ["regex"];
  const ACTION_TYPES = ["set", "add"];
  const ACTION_DEFAULT_MODE = { set: "always", add: "if_missing" };
  const KNOWN_EVENTS = ["Scene.Create.Post", "Scene.Update.Post"];

  // Suggestions only, not a restriction -- Stash scene fields are open
  // ended (any dotted path, including into files.N.*), so this feeds a
  // <datalist> for autocomplete rather than a hard <select>. Worth
  // fetching from the Python side (resolvers.FIELD_RESOLVERS +
  // whatever real Scene fields exist) instead of hardcoding, once that
  // becomes worth the extra round trip.
  const FIELD_SUGGESTIONS = [
    "file.path",
    "code",
    "title",
    "details",
    "url",
    "urls",
    "tags",
    "studio.name",
    "date",
    "rating100",
  ];
  const FIELD_SUGGESTIONS_ID = "cre-field-suggestions";

  // ------------------------------------------------------------
  // GraphQL helper
  // ------------------------------------------------------------
  // Plain fetch() rather than PluginApi's useSettings()/useConfiguration
  // hooks: those are tied to a React Context that only exists within the
  // Settings page's own component tree. A page registered via
  // PluginApi.register.route is a sibling route outside that tree, so
  // those hooks throw ("must be used within a SettingsContext") no
  // matter how they're called here. A raw GraphQL call has no such
  // restriction -- it works from anywhere in the app.
  async function graphqlRequest(query, variables) {
    const response = await fetch("/graphql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ query, variables }),
    });
    const result = await response.json();
    if (result.errors) {
      throw new Error(result.errors.map((e) => e.message).join("; "));
    }
    return result.data;
  }

  const CONFIGURATION_QUERY = `
    query Configuration {
      configuration {
        plugins
      }
    }
  `;

  const CONFIGURE_PLUGIN_MUTATION = `
    mutation ConfigurePlugin($plugin_id: ID!, $input: Map!) {
      configurePlugin(plugin_id: $plugin_id, input: $input)
    }
  `;

  const RUN_PLUGIN_OPERATION_MUTATION = `
    mutation RunPluginOperation($plugin_id: ID!, $args: Map!) {
      runPluginOperation(plugin_id: $plugin_id, args: $args)
    }
  `;

  // Invokes the Python side outside the normal hook path -- CustomRulesEngine.py
  // recognizes the "customRulesOperation" key in args and dispatches on it
  // (see handle_operation() in CustomRulesEngine.py), printing a
  // {"error": ..., "output": ...} line to stdout that becomes this
  // mutation's return value.
  async function runPluginOperation(operationArgs) {
    const data = await graphqlRequest(RUN_PLUGIN_OPERATION_MUTATION, {
      plugin_id: PLUGIN_ID,
      args: operationArgs,
    });
    return data.runPluginOperation;
  }

  async function fetchRawRulesFile() {
    return runPluginOperation({ customRulesOperation: "read_rules_file" });
  }

  async function saveRawRulesFile(contents) {
    return runPluginOperation({ customRulesOperation: "write_rules_file", contents });
  }

  async function fetchPluginSettings() {
    const data = await graphqlRequest(CONFIGURATION_QUERY);
    return (data.configuration.plugins && data.configuration.plugins[PLUGIN_ID]) || {};
  }

  // Merges `partial` into whatever settings this plugin currently has
  // rather than replacing them outright -- we haven't confirmed whether
  // configurePlugin merges or replaces server-side, and merging
  // client-side is safe either way (a no-op if the server already
  // merges, and correct if it doesn't).
  async function savePluginSetting(partial) {
    const current = await fetchPluginSettings();
    await graphqlRequest(CONFIGURE_PLUGIN_MUTATION, {
      plugin_id: PLUGIN_ID,
      input: { ...current, ...partial },
    });
  }

  // ------------------------------------------------------------
  // Navigation helper
  // ------------------------------------------------------------
  // Pushes a new URL and notifies the app's router without a full page
  // reload. A full reload (plain <a href>, typed URL, refresh) 404s at
  // the server for plugin routes on this Stash build -- see notes above.
  // Confirmed working: Stash's router picks up a manually dispatched
  // popstate event after pushState, even though the event wasn't
  // triggered by an actual back/forward navigation.
  function navigateTo(path) {
    window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  // ------------------------------------------------------------
  // Structured rule editing -- immutable update helpers
  // ------------------------------------------------------------
  // All operate on the {schema_version, rules: [...]} document shape.
  // Each returns a new document rather than mutating in place, so React
  // state updates behave predictably.

  function emptyCondition() {
    return { type: "regex", field: "", pattern: "" };
  }

  function emptyAction() {
    return { type: "set", field: "", template: "", mode: ACTION_DEFAULT_MODE.set };
  }

  function emptyRule() {
    return { name: "", events: [], conditions: [emptyCondition()], actions: [emptyAction()] };
  }

  function updateRuleAt(doc, ruleIndex, updater) {
    const rules = doc.rules.map((rule, i) => (i === ruleIndex ? updater(rule) : rule));
    return { ...doc, rules };
  }

  function updateItemAt(list, index, updater) {
    return list.map((item, i) => (i === index ? updater(item) : item));
  }

  function removeItemAt(list, index) {
    return list.filter((_, i) => i !== index);
  }

  // ------------------------------------------------------------
  // Structured rule editor (the primary editing surface)
  // ------------------------------------------------------------
  function ConditionEditor(props) {
    const { condition, onChange, onRemove } = props;
    return el(
      "div",
      { className: "cre-condition-row" },
      el(
        "select",
        {
          value: condition.type,
          onChange: (e) => onChange({ ...condition, type: e.target.value }),
        },
        CONDITION_TYPES.map((t) => el("option", { key: t, value: t }, t))
      ),
      el("input", {
        type: "text",
        list: FIELD_SUGGESTIONS_ID,
        placeholder: "field",
        value: condition.field,
        onChange: (e) => onChange({ ...condition, field: e.target.value }),
      }),
      el("input", {
        type: "text",
        placeholder: "regex pattern",
        value: condition.pattern,
        onChange: (e) => onChange({ ...condition, pattern: e.target.value }),
      }),
      el("button", { onClick: onRemove, className: "cre-remove-btn", title: "Remove condition" }, "\u2212")
    );
  }

  function ActionEditor(props) {
    const { action, onChange, onRemove } = props;
    function handleTypeChange(newType) {
      // Mode isn't a free choice -- schema.py only accepts one fixed mode
      // per action type today, so switching type re-derives it rather
      // than letting it drift to an invalid value. Rendered as a
      // (disabled, single-option) select rather than plain text so it
      // still reads visually as "this is a real field", not a label --
      // and it's already wired to grow into a real choice if/when
      // schema.py ever supports more than one mode per type.
      onChange({ ...action, type: newType, mode: ACTION_DEFAULT_MODE[newType] });
    }
    return el(
      "div",
      { className: "cre-action-row" },
      el(
        "select",
        { value: action.type, onChange: (e) => handleTypeChange(e.target.value) },
        ACTION_TYPES.map((t) => el("option", { key: t, value: t }, t))
      ),
      el(
        "select",
        { value: action.mode, disabled: true, title: "Only one mode is currently supported per action type" },
        el("option", { value: action.mode }, action.mode)
      ),
      el("input", {
        type: "text",
        list: FIELD_SUGGESTIONS_ID,
        placeholder: "field",
        value: action.field,
        onChange: (e) => onChange({ ...action, field: e.target.value }),
      }),
      el("input", {
        type: "text",
        placeholder: "template, e.g. FOO-{1}",
        value: action.template,
        onChange: (e) => onChange({ ...action, template: e.target.value }),
      }),
      el("button", { onClick: onRemove, className: "cre-remove-btn", title: "Remove action" }, "\u2212")
    );
  }

  function RuleEditor(props) {
    const { rule, onChange, onRemove } = props;

    function toggleEvent(eventName) {
      const events = rule.events || [];
      const next = events.includes(eventName)
        ? events.filter((e) => e !== eventName)
        : [...events, eventName];
      onChange({ ...rule, events: next });
    }

    function updateCondition(index, updated) {
      onChange({ ...rule, conditions: updateItemAt(rule.conditions, index, () => updated) });
    }
    function removeCondition(index) {
      onChange({ ...rule, conditions: removeItemAt(rule.conditions, index) });
    }
    function addCondition() {
      onChange({ ...rule, conditions: [...rule.conditions, emptyCondition()] });
    }

    function updateAction(index, updated) {
      onChange({ ...rule, actions: updateItemAt(rule.actions, index, () => updated) });
    }
    function removeAction(index) {
      onChange({ ...rule, actions: removeItemAt(rule.actions, index) });
    }
    function addAction() {
      onChange({ ...rule, actions: [...rule.actions, emptyAction()] });
    }

    return el(
      "div",
      { className: "cre-rule-card" },
      el(
        "div",
        { className: "cre-rule-layout" },

        // --- Left column: identity ---
        el(
          "div",
          null,
          el("p", { className: "cre-section-label", style: { marginTop: 0 } }, "Name"),
          el("textarea", {
            value: rule.name,
            onChange: (e) => onChange({ ...rule, name: e.target.value }),
            rows: 2,
            className: "cre-rule-name-input",
          }),

          el("p", { className: "cre-section-label" }, "Triggers"),
          el(
            "div",
            { className: "cre-trigger-list" },
            KNOWN_EVENTS.map((eventName) =>
              el(
                "label",
                { key: eventName, className: "cre-trigger-checkbox" },
                el("input", {
                  type: "checkbox",
                  checked: (rule.events || []).includes(eventName),
                  onChange: () => toggleEvent(eventName),
                }),
                eventName
              )
            )
          ),
          (rule.events || []).length === 0
            ? el("p", { className: "cre-hint" }, "(none checked = runs on any event)")
            : null,

          el(
            "button",
            { onClick: onRemove, className: "cre-remove-rule-btn", style: { marginTop: "1rem" } },
            "Remove rule"
          )
        ),

        // --- Right column: the actual rule logic ---
        el(
          "div",
          null,
          el("p", { className: "cre-section-label", style: { marginTop: 0 } }, "Conditions"),
          rule.conditions.map((cond, i) =>
            el(ConditionEditor, {
              key: i,
              condition: cond,
              onChange: (updated) => updateCondition(i, updated),
              onRemove: () => removeCondition(i),
            })
          ),
          el(
            "button",
            { onClick: addCondition, className: "btn btn-secondary cre-add-btn" },
            "+ Add condition"
          ),

          el("p", { className: "cre-section-label" }, "Actions"),
          rule.actions.map((action, i) =>
            el(ActionEditor, {
              key: i,
              action: action,
              onChange: (updated) => updateAction(i, updated),
              onRemove: () => removeAction(i),
            })
          ),
          el(
            "button",
            { onClick: addAction, className: "btn btn-secondary cre-add-btn" },
            "+ Add action"
          )
        )
      )
    );
  }

  // ------------------------------------------------------------
  // Dedicated configuration page (registered as its own route)
  // ------------------------------------------------------------
  function RulesConfigPage() {
    const [rulesFile, setRulesFile] = useState("");
    const [loaded, setLoaded] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState(null);

    // The structured document is the source of truth once loaded. `null`
    // means "not loaded yet"; loadError means "loaded, but couldn't be
    // parsed into a document the structured editor can work with" -- in
    // that case we fall back to showing the raw text read-only, since
    // there's nothing structured to edit until the underlying JSON is
    // fixed some other way.
    const [rulesPath, setRulesPath] = useState("");
    const [rulesDoc, setRulesDoc] = useState(null);
    const [loadError, setLoadError] = useState(null);
    const [rawFallback, setRawFallback] = useState("");

    const [saving, setSaving] = useState(false);
    const [docSaved, setDocSaved] = useState(false);
    const [saveErrors, setSaveErrors] = useState(null);

    useEffect(() => {
      fetchPluginSettings()
        .then((settings) => {
          setRulesFile(settings.rules_file || "");
          setLoaded(true);
        })
        .catch((err) => setError(String(err)));
    }, []);

    useEffect(() => {
      fetchRawRulesFile()
        .then((result) => {
          setRulesPath(result.path);
          try {
            const parsed = JSON.parse(result.contents);
            if (!parsed || !Array.isArray(parsed.rules)) {
              throw new Error("no top-level 'rules' array found");
            }
            setRulesDoc(parsed);
          } catch (err) {
            setLoadError(String(err.message || err));
            setRawFallback(result.contents);
          }
        })
        .catch((err) => setLoadError(String(err)));
    }, []);

    function handleChange(event) {
      setRulesFile(event.target.value);
      setSaved(false);
    }

    function handleSave() {
      setError(null);
      savePluginSetting({ rules_file: rulesFile })
        .then(() => setSaved(true))
        .catch((err) => setError(String(err)));
    }

    function updateRule(index, updated) {
      setRulesDoc(updateRuleAt(rulesDoc, index, () => updated));
      setDocSaved(false);
    }
    function removeRule(index) {
      setRulesDoc({ ...rulesDoc, rules: removeItemAt(rulesDoc.rules, index) });
      setDocSaved(false);
    }
    function addRule() {
      setRulesDoc({ ...rulesDoc, rules: [...rulesDoc.rules, emptyRule()] });
      setDocSaved(false);
    }

    const generatedJson = useMemo(() => (rulesDoc ? JSON.stringify(rulesDoc, null, 2) : ""), [rulesDoc]);

    function handleDocSave() {
      setSaving(true);
      setDocSaved(false);
      setSaveErrors(null);
      saveRawRulesFile(generatedJson)
        .then((result) => {
          setSaving(false);
          if (result.success) {
            setDocSaved(true);
          } else {
            setSaveErrors(result.errors && result.errors.length ? result.errors : ["Unknown error"]);
          }
        })
        .catch((err) => {
          setSaving(false);
          setSaveErrors([String(err)]);
        });
    }

    return el(
      "div",
      // Deliberately wide: this is a data-dense editing page, not prose --
      // the previous 640px cap was ours (not something Stash imposed) and
      // wasted the available screen width. Adjust freely to taste.
      { className: "custom-rules-engine-config-page", style: { padding: "2rem", maxWidth: "1400px" } },
      el(
        "datalist",
        { id: FIELD_SUGGESTIONS_ID },
        FIELD_SUGGESTIONS.map((f) => el("option", { key: f, value: f }))
      ),
      el("h2", null, "Custom Rules Engine — Configuration"),

      // --- Rules file location setting ---
      el("p", null, "This is the location of the rules file the engine reads at runtime."),
      error ? el("p", { style: { color: "red" } }, "Error: " + error) : null,
      el(
        "label",
        { htmlFor: "cre-rules-file", style: { display: "block", marginTop: "1rem", fontWeight: 600 } },
        "Rules file (JSON, supports {pluginDir})"
      ),
      el("input", {
        id: "cre-rules-file",
        type: "text",
        value: rulesFile,
        onChange: handleChange,
        disabled: !loaded,
        style: { width: "100%", maxWidth: "640px", padding: "0.5rem", marginTop: "0.5rem" },
      }),
      el(
        "button",
        { onClick: handleSave, disabled: !loaded, style: { marginTop: "1rem" }, className: "btn btn-primary" },
        "Save"
      ),
      saved ? el("span", { style: { marginLeft: "0.75rem", color: "green" } }, "Saved") : null,

      // --- Structured rule editor ---
      el("h3", { style: { marginTop: "2.5rem" } }, "Rules"),

      loadError
        ? el(
            "div",
            null,
            el("p", { style: { color: "red" } }, "Couldn't load the rules file as structured data: " + loadError),
            el(
              "p",
              null,
              "Showing the raw file contents below (read-only) until this is fixed some other way -- editing here isn't available for a file the structured editor can't parse."
            ),
            el("textarea", {
              readOnly: true,
              value: rawFallback,
              rows: 16,
              style: { width: "100%", fontFamily: "monospace", padding: "0.5rem" },
            })
          )
        : rulesDoc
        ? el(
            "div",
            null,
            rulesDoc.rules.map((rule, i) =>
              el(RuleEditor, {
                key: i,
                rule: rule,
                onChange: (updated) => updateRule(i, updated),
                onRemove: () => removeRule(i),
              })
            ),
            el(
              "button",
              { onClick: addRule, style: { marginTop: "1rem" }, className: "btn btn-secondary" },
              "+ Add rule"
            ),

            el(
              "div",
              { style: { marginTop: "1.5rem" } },
              el(
                "button",
                { onClick: handleDocSave, disabled: saving, className: "btn btn-primary" },
                saving ? "Saving..." : "Save rules"
              ),
              docSaved ? el("span", { style: { marginLeft: "0.75rem", color: "green" } }, "Saved") : null,
              saveErrors
                ? el(
                    "div",
                    { style: { marginTop: "0.75rem", color: "red" } },
                    el("p", null, "Not saved -- fix the following and try again:"),
                    el(
                      "ul",
                      null,
                      saveErrors.map((msg, i) => el("li", { key: i }, msg))
                    )
                  )
                : null
            ),

            // --- Generated JSON (read-only) ---
            // Derived live from the structured state above -- this is
            // exactly what "Save rules" sends to be validated and written.
            // Kept visible for transparency/debugging, not for direct
            // editing.
            el("h3", { style: { marginTop: "2rem" } }, "Generated JSON (read-only)"),
            el("p", { style: { fontFamily: "monospace", fontSize: "0.85rem" } }, rulesPath),
            el("textarea", {
              readOnly: true,
              value: generatedJson,
              rows: 16,
              style: { width: "100%", fontFamily: "monospace", padding: "0.5rem", opacity: 0.85 },
            })
          )
        : el("p", null, "Loading...")
    );
  }

  PluginApi.register.route(CONFIG_ROUTE, RulesConfigPage);

  // ------------------------------------------------------------
  // Settings-panel patch: for THIS plugin only, replace the default
  // per-setting field list with a link to the page above. Other plugins'
  // settings panels are returned unmodified (`result`) so this can't
  // affect anything else installed.
  // ------------------------------------------------------------
  function pluginSettingsHook(props, _context, result) {
    // TEMPORARY: confirms the assumed PLUGIN_ID actually matches what
    // Stash reports for this plugin. Remove once verified once.
    console.debug("[CustomRulesEngine] PluginSettings patch saw pluginID:", props.pluginID);

    if (props.pluginID !== PLUGIN_ID) {
      return result;
    }

    return el(
      "div",
      { className: "custom-rules-engine-settings-link" },
      el(
        "button",
        {
          className: "btn btn-secondary",
          onClick: (event) => {
            event.preventDefault();
            navigateTo(CONFIG_ROUTE);
          },
        },
        "Open Rules Configuration →"
      )
    );
  }

  PluginApi.patch.after("PluginSettings", pluginSettingsHook);
})();