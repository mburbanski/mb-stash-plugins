// =======================================================
// Internet Archive Toggle – namespaced version (iat_ prefix)
// =======================================================

console.log("Internet Archive Toggle plugin loaded");

const iat_ARCHIVE_PREFIX = "https://web.archive.org/web/00000000000000/";
const iat_ARCHIVE_HOST = "https://web.archive.org/web/";

// ---------------------------------------
// Helpers
// ---------------------------------------
function iat_isArchiveUrl(url) {
  return url.startsWith(iat_ARCHIVE_HOST);
}

function iat_toArchiveUrl(url) {
  if (!url) return "";
  if (iat_isArchiveUrl(url)) return url;
  return iat_ARCHIVE_PREFIX + url;
}

function iat_fromArchiveUrl(url) {
  if (!iat_isArchiveUrl(url)) return url;
  return url.replace(/^https:\/\/web\.archive\.org\/web\/\d+\//, "");
}

// Extract the parent row's React props
function iat_getRowReactProps(inputEl) {
  const row = inputEl.closest(".input-group");
  if (!row) return null;

  for (const key of Object.getOwnPropertyNames(row)) {
    if (key.startsWith("__reactProps$")) {
      const props = row[key];
      const child = props.children?.[0];
      if (child?.props?.setValue) {
        return child.props;
      }
    }
  }

  return null;
}

// ---------------------------------------
// Toggle URL between normal and archive
// ---------------------------------------
function iat_toggleArchiveURL(inputEl) {
  const rowProps = iat_getRowReactProps(inputEl);
  if (!rowProps || typeof rowProps.setValue !== "function") {
    console.warn("IA: Could not find parent React props or setValue");
    alert("Unable to update React state. Stash UI may have changed.");
    return;
  }

  const current = rowProps.value;
  let next;

  if (iat_isArchiveUrl(current)) {
    next = iat_fromArchiveUrl(current);
  } else {
    next = iat_toArchiveUrl(current);
  }

  rowProps.setValue(next);
}

// ---------------------------------------
// Inject IA toggle buttons into each URL row
// ---------------------------------------
function iat_injectButtonsInto(container) {
  const rows = container.querySelectorAll(".input-group");

  rows.forEach(row => {
    const input = row.querySelector("input.form-control");
    const append = row.querySelector(".input-group-append");
    if (!input || !append) return;

    if (append.querySelector(".ia-toggle-btn")) return;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ia-toggle-btn btn btn-secondary btn-sm";
    btn.style.marginLeft = "4px";
    btn.textContent = "IA";
    btn.title = "Toggle between normal and archive.org URL";

    btn.addEventListener("click", () => {
      iat_toggleArchiveURL(input);
    });

    const scrapeBtn = append.querySelector(".scrape-url-button");

    if (scrapeBtn) {
      scrapeBtn.parentNode.insertBefore(btn, scrapeBtn.nextSibling);
    } else {
      append.appendChild(btn);
    }
  });
}

// ---------------------------------------
// Scan for all URL lists and inject
// ---------------------------------------
function iat_scanAndInject() {
  const containers = document.querySelectorAll(
    'div[data-field="urls"] .string-list-input'
  );
  containers.forEach(iat_injectButtonsInto);
}

// ---------------------------------------
// Global observer on body
// ---------------------------------------
(function iat_startObserver() {
  queueMicrotask(iat_scanAndInject);

  const observer = new MutationObserver(() => {
    queueMicrotask(iat_scanAndInject);
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true
  });
})();
