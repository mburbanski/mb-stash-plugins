# Internet Archive Toggle

**Internet Archive Toggle** is a lightweight UI enhancement for the Stash scene editor.  
It adds a small **IA** button next to each URL in a scene’s URL list, allowing you to quickly toggle a URL between:

- its **normal/original form**, and  
- its **Internet Archive (Wayback Machine)** snapshot form.

This makes it easy to retry scrapes against archived versions of dead or changed URLs using Stash’s **native scrape button**.

---

## Features

- Adds an **IA toggle button** next to each URL row in the Stash scene editor.
- Toggles between:
  - Normal URL → Archive.org snapshot  
  - Archive snapshot → Normal URL
- Integrates seamlessly with Stash’s **native scrape button**.
- Uses Stash’s **actual React state**, ensuring the scrape button always sees the correct URL.
- Automatically injects itself into dynamically loaded UI elements.
- Non-intrusive: does not override or replace any Stash functionality.

---

## How It Works

### High-Level Behavior

1. You attempt a normal scrape using Stash’s built-in scrape button.
2. If the URL is dead or the site has changed, click the **IA** button.
3. The URL instantly switches to its archive.org version.
4. Click the native scrape button again — Stash now scrapes the archived page.
5. Click **IA** again to toggle back to the original URL.

The IA button does **not** perform the scrape itself.  
It simply updates the URL that Stash’s native scrape button uses.

---

## Architecture Overview

### Stash’s URL Editor Is Built in React

Each URL row in the Stash scene editor is a **React component**.  
The input field you see on screen is a *controlled component*, meaning:

- The text you see is stored in React state.
- The DOM `<input>` value is just a reflection of that state.
- The native scrape button reads the URL from **React state**, not from the DOM.

This is why simply changing the DOM value (e.g., `input.value = ...`) does **not** affect what the scrape button uses.

### The Key Insight

Each URL row exposes a React prop:

```
setValue(newUrl)
```

This function updates the **actual React state** that the scrape button reads from.

The IA toggle button calls this function directly.

### Why This Works

- Updating React state causes the input field to update visually.
- The scrape button always reads the current React state.
- No need to trigger the scrape programmatically.
- No need to access React’s internal closures or fiber structures.
- No need to modify Stash’s backend or GraphQL layer.

---

## Code Structure

The script is organized into:

1. **Helpers**  
   - URL detection and conversion  
   - Archive URL construction  
   - React prop extraction  

2. **Core Logic**  
   - `toggleArchiveURL(inputEl)`  
     - Reads the current URL from React state  
     - Computes the toggled version  
     - Calls `setValue()` to update React state  

3. **UI Injection**  
   - Finds each URL row  
   - Creates the IA button  
   - Inserts it immediately after the native scrape button  

4. **MutationObserver**  
   - Ensures the IA button appears even when Stash re-renders parts of the UI  

---

## Example Toggle Behavior

| Current URL | After Clicking IA |
|-------------|-------------------|
| `https://example.com/video/123` | `https://web.archive.org/web/00000000000000/https://example.com/video/123` |
| `https://web.archive.org/web/20200101000000/https://example.com/video/123` | `https://example.com/video/123` |

---

## Limitations

- This script does **not** trigger the scrape automatically.  
  You still click the native scrape button.
- The script assumes Stash’s URL editor continues to use the same React structure.  
  If Stash changes its UI framework, the injection logic may need updating.

---

## Why This Approach Is Robust

Attempts to programmatically trigger the scrape or modify internal React closures are brittle and unreliable.  
This toggle-only approach avoids all of that by:

- Respecting Stash’s existing UI flow  
- Updating only the state that Stash already uses  
- Leveraging React’s public props rather than internal fibers  
- Keeping the user in control of when the scrape happens  

It’s simple, predictable, and maintainable.

---

## License

This script is provided as-is.  
Use, modify, or integrate it into your Stash setup however you like.
