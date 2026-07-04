# Alias Promoter

Alias Promoter is a lightweight Stash UI extension that adds a **Promote** button next to each alias on Performer, Studio, and Tag edit pages. Clicking the button instantly swaps the alias with the main name — exactly as if you manually cut and pasted the values yourself.

No database writes are performed directly. The plugin simply updates the form fields in the browser, and Stash saves the changes normally when you click **Save**.

This makes it fast and painless to correct mis-assigned names, promote a commonly-used alias, or clean up inconsistent naming.

---

## ✨ Features

- Adds a **Promote** button next to each alias on:
    - Performer edit pages
    - Studio edit pages
    - Tag edit pages
- Swaps the alias with the main name instantly
- Uses React-aware updates so Stash recognizes the form as modified
- Disabled button on the empty “new alias” row
- No page reloads
- No direct DB writes
- Automatically adapts to Stash UI structure
- Future-proof: if Groups ever gain multi-alias support, the plugin will pick it up automatically

---

## 🚀 Installation

1. Create a folder in your Stash `plugins/` directory, e.g.: `plugins/AliasPromoter/

2. Add the following files:

- `plugin.yml`
- `alias-promoter.js`

3. Restart Stash or reload the UI.

The Promote buttons will appear automatically on supported edit pages.

---

## 🧑‍💻 How to Use

1. Open any Performer, Studio, or Tag edit page.
2. Scroll to the **Aliases** section.
3. Click **Promote** next to the alias you want to make the primary name.
4. The alias and the main name will instantly swap.
5. Click **Save** to commit the change.

The last empty alias row always shows a disabled Promote button — this is intentional, since it’s the “add new alias” field.

---

## 🛠 Developer Notes

This section explains how the plugin works internally, so you can extend it or adapt it for other Stash UI elements.

### Overview

Stash’s edit pages are built in React. Simply changing the DOM input values does **not** update React’s internal state, which means:

- The Save button won’t activate
- Stash won’t save the changes

To handle this correctly, the plugin uses two different mechanisms:

1. **Aliases (string-list-input fields)**
   These are React components with a `setValue()` function attached to their parent `.input-group`.
   The plugin extracts that function and calls it directly.

2. **Main name field (simple text input)**
   This is not a string-list-input, so it doesn’t expose `setValue()`.
   Instead, the plugin:

- Sets the input’s `.value`
- Fires a synthetic `input` event
- Updates React’s internal value tracker

This convinces React that the user typed the new value manually.

### Alias Detection

The plugin does not rely on specific form IDs (e.g., `#performer-edit`).
Instead, it scans for any alias list using:

```css
div[data-field="alias_list"] .string-list-input,
div[data-field="aliases"] .string-list-input
```

This makes it work across:

- Performers
- Studios
- Tags
- Any future entity that uses the same alias list structure

### Form Detection

Once an alias list is found, the plugin determines the correct form by walking up the DOM:

```js
const formEl = container.closest("form");
```

This ensures the correct name field is targeted, regardless of entity type.

### Swapping Logic

The swap is simple:

- Read alias value
- Read name value
- Write name → alias
- Write alias → name

But the important part is how the values are written:

- Aliases use setValue() when available
- Name uses synthetic input events

This guarantees React marks the form as dirty and enables the Save button.

### Disabled Button on Empty Row

The last alias row is always an empty input used to add a new alias.
The plugin detects this and disables the Promote button:

```js
if (!input.value.trim()) {
  btn.disabled = true;
  btn.style.opacity = "0.5";
  btn.style.cursor = "default";
}
```

This matches Stash’s own disabled button styling.

### Extending the Plugin

You can easily extend the plugin to:

- Add a Demote button next to the main name
- Add a Swap button between any two aliases
- Add bulk actions
- Add plugin settings
- Support custom fields or schema extensions

The core logic is modular and can be reused anywhere Stash uses React-controlled inputs.

## 📄 License

This plugin is provided under the MIT License.
Feel free to fork, modify, and extend it.

## 🙌 Contributions

PRs and suggestions are welcome.
If Stash adds new alias-capable entity types in the future, this plugin can be extended to support them with minimal changes.
