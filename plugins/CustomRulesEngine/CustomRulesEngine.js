// Custom Rules Engine - frontend UI
//
// Step 1 of the config-UI rollout: replace the default settings-panel
// editor for the `rules_file` setting with a link to a dedicated
// configuration page. The dedicated page (for now) just re-implements
// that same text field -- later steps will grow it into the full rule
// builder, backed by the same schema.py validation the Python side uses.
//
// Written as plain JS (no build step): the markup here is small enough
// that named React.createElement calls stay readable without adding a
// compiler to the toolchain. Worth revisiting once the rule-builder UI
// itself lands and the markup grows.
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
  const { useState, useEffect } = React;

  const el = React.createElement;

  // Must match this plugin's manifest-derived id exactly, or both the
  // settings patch below and the GraphQL calls will target the wrong
  // plugin's settings. Stash derives this from the plugin's .yml
  // filename/folder (there is no `id:` field in the manifest schema) --
  // this should be "CustomRulesEngine" to match CustomRulesEngine.yml,
  // confirmed via the console.debug further down.
  const PLUGIN_ID = "CustomRulesEngine";
  const CONFIG_ROUTE = "/plugin/custom-rules-engine";

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
  // Dedicated configuration page (registered as its own route)
  // ------------------------------------------------------------
  function RulesConfigPage() {
    const [rulesFile, setRulesFile] = useState("");
    const [loaded, setLoaded] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
      fetchPluginSettings()
        .then((settings) => {
          setRulesFile(settings.rules_file || "");
          setLoaded(true);
        })
        .catch((err) => setError(String(err)));
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

    return el(
      "div",
      { className: "custom-rules-engine-config-page", style: { padding: "2rem", maxWidth: "640px" } },
      el("h2", null, "Custom Rules Engine — Configuration"),
      el(
        "p",
        null,
        "This is where the plugin's rules file location is set. Rule creation and editing will move here in a later step."
      ),
      error ? el("p", { style: { color: "red" } }, "Error: " + error) : null,
      el(
        "label",
        { htmlFor: "cre-rules-file", style: { display: "block", marginTop: "1.5rem", fontWeight: 600 } },
        "Rules file (JSON, supports {pluginDir})"
      ),
      el("input", {
        id: "cre-rules-file",
        type: "text",
        value: rulesFile,
        onChange: handleChange,
        disabled: !loaded,
        style: { width: "100%", padding: "0.5rem", marginTop: "0.5rem" },
      }),
      el(
        "button",
        { onClick: handleSave, disabled: !loaded, style: { marginTop: "1rem" }, className: "btn btn-primary" },
        "Save"
      ),
      saved ? el("span", { style: { marginLeft: "0.75rem", color: "green" } }, "Saved") : null
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