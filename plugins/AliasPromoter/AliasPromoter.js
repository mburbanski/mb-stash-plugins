// =======================================================
// Alias Promoter – namespaced version (ap_ prefix)
// =======================================================

console.log("Alias Promoter plugin loaded");

// ---------------------------------------
// React helpers for alias rows
// ---------------------------------------
function ap_getRowReactProps(inputEl) {
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
// Generic helper: update a text input so React sees it
// ---------------------------------------
function ap_setReactInputValue(input, value) {
    const last = input.value;
    input.value = value;

    const event = new Event("input", { bubbles: true });

    const tracker = input._valueTracker;
    if (tracker) tracker.setValue(last);

    input.dispatchEvent(event);
}

// ---------------------------------------
// Core: swap alias with main name
// ---------------------------------------
function ap_promoteAlias(aliasInput, formEl) {
    const nameInput = formEl.querySelector(
        "div[data-field='name'] input#name, div[data-field='name'] input[name='name']"
    );

    if (!nameInput) {
        alert("Alias Promoter: Could not find the main name field.");
        return;
    }

    const aliasProps = ap_getRowReactProps(aliasInput);
    const aliasValue = aliasProps ? aliasProps.value : aliasInput.value;
    const nameValue = nameInput.value;

    if (!aliasValue) return;

    if (aliasProps && typeof aliasProps.setValue === "function") {
        aliasProps.setValue(nameValue);
    } else {
        aliasInput.value = nameValue;
    }

    ap_setReactInputValue(nameInput, aliasValue);

    console.log(`Alias Promoter: swapped "${nameValue}" with "${aliasValue}"`);
}

// ---------------------------------------
// Inject Promote buttons into alias list
// ---------------------------------------
function ap_injectButtonsInto(container) {
    const formEl = container.closest("form");
    if (!formEl) return;

    const rows = container.querySelectorAll(".input-group");

    rows.forEach((row) => {
        if (row.querySelector(".alias-promote-btn")) return;

        const input = row.querySelector("input.text-input.form-control");
        const append = row.querySelector(".input-group-append");
        if (!input || !append) return;

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "alias-promote-btn btn btn-primary btn-sm";
        btn.style.marginLeft = "4px";
        btn.textContent = "Promote";

        const ap_updateBtnState = () => {
            const isEmpty = !input.value.trim();
            btn.disabled = isEmpty;
            btn.style.opacity = isEmpty ? "0.5" : "1";
            btn.style.cursor = isEmpty ? "default" : "pointer";
        };

        ap_updateBtnState();
        input.addEventListener("input", ap_updateBtnState);

        btn.addEventListener("click", () => {
            ap_promoteAlias(input, formEl);
        });

        append.appendChild(btn);
    });
}

// ---------------------------------------
// Scan for alias lists on ANY edit page
// ---------------------------------------
function ap_scanAndInject() {
    const containers = document.querySelectorAll(
        'div[data-field="alias_list"] .string-list-input, ' +
        'div[data-field="aliases"] .string-list-input'
    );

    containers.forEach(ap_injectButtonsInto);
}

// ---------------------------------------
// Global observer on body
// ---------------------------------------
(function ap_startObserver() {
    queueMicrotask(ap_scanAndInject);

    const observer = new MutationObserver(() => {
        queueMicrotask(ap_scanAndInject);
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true,
    });
})();
