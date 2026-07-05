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
  const { useSettings } = PluginApi.hooks;

  const el = React.createElement;

  // Must match this plugin's manifest-derived id exactly, or the settings
  // patch below will never match and the default editor will keep
  // showing. Stash derives this from the plugin's .yml filename/folder,
  // not a declared field in the yml (there is no `id:` field in the
  // manifest schema) -- this should be "CustomRulesEngine" to match
  // CustomRulesEngine.yml, but the console.debug below confirms it.
  const PLUGIN_ID = "CustomRulesEngine";
  const CONFIG_ROUTE = "/plugin/custom-rules-engine";

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

  // Small wrapper around useSettings() scoped to this plugin's settings,
  // so components below don't need to know the plugins-map shape.
  function usePluginSettings() {
    const { plugins, savePluginSettings } = useSettings();
    const configuration = plugins[PLUGIN_ID] || {};
    function saveSetting(partial) {
      savePluginSettings(PLUGIN_ID, { ...configuration, ...partial });
    }
    return { configuration, saveSetting };
  }

  // ------------------------------------------------------------
  // Dedicated configuration page (registered as its own route)
  // ------------------------------------------------------------
  function RulesConfigPage() {
    const { configuration, saveSetting } = usePluginSettings();
    const [rulesFile, setRulesFile] = useState("");
    const [saved, setSaved] = useState(false);

    useEffect(() => {
      setRulesFile(configuration.rules_file || "");
    }, [configuration.rules_file]);

    function handleChange(event) {
      setRulesFile(event.target.value);
      setSaved(false);
    }

    function handleSave() {
      saveSetting({ rules_file: rulesFile });
      setSaved(true);
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
        style: { width: "100%", padding: "0.5rem", marginTop: "0.5rem" },
      }),
      el(
        "button",
        { onClick: handleSave, style: { marginTop: "1rem" }, className: "btn btn-primary" },
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