// Settings page — fetches /api/settings on load, sends PATCH on save,
// hits /api/settings/test-llm for the probe button.

import { apiFetch, ApiError } from "../api.js";

const form = document.getElementById("settings-form");
const status = document.getElementById("settings-status");
const testButton = document.getElementById("test-llm");

const personalityForm = document.getElementById("personality-form");
const personalityCurrent = document.getElementById("personality-current");
const personalityStyle = document.getElementById("personality-style");
const personalityStatus = document.getElementById("personality-status");
const presetsList = document.getElementById("presets");

// Track baseline values so PATCH only sends what actually changed.
// Secret fields are always left empty in the input — we read their
// state from `secretState` instead, and submit them only when the
// user types into them or clicks the Clear button.
const baseline = new Map(); // key -> string value (the rendered placeholder text or "")
const secretState = new Map(); // key -> { set: bool, preview: string, clearRequested: bool }

function setStatus(el, kind, text) {
  el.dataset.kind = kind; // "ok" | "error" | "loading" | ""
  el.textContent = text || "";
}

function syncProviderVisibility() {
  const provider = (form.elements["LLM_PROVIDER"].value || "anthropic").toLowerCase();
  for (const fs of form.querySelectorAll("fieldset[data-provider]")) {
    fs.hidden = fs.dataset.provider !== provider;
  }
}

function applySettingsSnapshot(snapshot, editableKeys, secretKeys) {
  for (const key of editableKeys) {
    const field = form.elements[key];
    if (!field) continue;
    const value = snapshot[key];
    if (secretKeys.includes(key)) {
      const info = value && typeof value === "object" ? value : { set: false, preview: "" };
      secretState.set(key, { ...info, clearRequested: false });
      // Show placeholder, never the actual value
      field.value = "";
      field.placeholder = info.set ? `set · ${info.preview}` : "(unset)";
      // Update the visible hint
      const hint = form.querySelector(`[data-secret-state="${key}"]`);
      if (hint) hint.textContent = info.set ? `set · ${info.preview}` : "not set";
      baseline.set(key, "");
    } else if (field.type === "radio" || field.tagName === "FIELDSET") {
      // Provider radios are a group — handled below.
      continue;
    } else {
      field.value = value || "";
      baseline.set(key, field.value);
    }
  }
  // Provider radio
  const providerRadios = form.elements["LLM_PROVIDER"];
  if (providerRadios) {
    const current = (snapshot.LLM_PROVIDER || "anthropic").toLowerCase();
    for (const radio of providerRadios) {
      radio.checked = radio.value === current;
    }
    baseline.set("LLM_PROVIDER", current);
  }
  syncProviderVisibility();
}

function applyPersonalitySnapshot(info) {
  if (!info) return;
  personalityCurrent.textContent = info.current || "default (friendly assistant)";
  presetsList.innerHTML = "";
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "default";
  presetsList.appendChild(defaultOpt);
  for (const preset of info.presets || []) {
    const opt = document.createElement("option");
    opt.value = preset;
    presetsList.appendChild(opt);
  }
}

async function loadSettings() {
  setStatus(status, "loading", "Loading…");
  try {
    const data = await apiFetch("/api/settings");
    applySettingsSnapshot(data.settings, data.editable_keys, data.secret_keys);
    applyPersonalitySnapshot(data.personality);
    setStatus(status, "", "");
  } catch (err) {
    setStatus(status, "error", `Could not load: ${err.message}`);
  }
}

function collectChanges() {
  const changes = {};
  for (const [key, base] of baseline.entries()) {
    if (secretState.has(key)) continue; // handled below
    const field = form.elements[key];
    if (!field) continue;
    const value = field.value;
    if (value !== base) changes[key] = value;
  }
  for (const [key, info] of secretState.entries()) {
    const field = form.elements[key];
    if (!field) continue;
    if (info.clearRequested) {
      changes[key] = "";
    } else if (field.value !== "") {
      changes[key] = field.value;
    }
  }
  return changes;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const changes = collectChanges();
  if (Object.keys(changes).length === 0) {
    setStatus(status, "", "Nothing to save.");
    return;
  }
  setStatus(status, "loading", "Saving…");
  try {
    const data = await apiFetch("/api/settings", { method: "PATCH", body: changes });
    applySettingsSnapshot(data.settings, Object.keys(data.settings), Array.from(secretState.keys()));
    const restart = data.restart_required || [];
    const summary =
      `Saved ${data.applied.length} change(s)` +
      (data.llm_reloaded ? " · LLM reloaded" : "") +
      (restart.length ? ` · restart Sidekick to apply ${restart.join(", ")}` : "");
    setStatus(status, "ok", summary);
  } catch (err) {
    setStatus(status, "error", `Save failed: ${err.message}`);
  }
});

// Provider radio toggles visibility immediately
form.elements["LLM_PROVIDER"].forEach?.((radio) => {
  radio.addEventListener("change", syncProviderVisibility);
});
for (const radio of form.querySelectorAll('input[name="LLM_PROVIDER"]')) {
  radio.addEventListener("change", syncProviderVisibility);
}

// Clear buttons next to secret fields
for (const button of form.querySelectorAll("button[data-clear]")) {
  button.addEventListener("click", () => {
    const key = button.dataset.clear;
    const info = secretState.get(key);
    if (!info) return;
    info.clearRequested = true;
    secretState.set(key, info);
    const field = form.elements[key];
    if (field) {
      field.value = "";
      field.placeholder = "(will be cleared on save)";
    }
    setStatus(status, "", `${key} will be cleared on save.`);
  });
}

testButton.addEventListener("click", async () => {
  setStatus(status, "loading", "Probing LLM…");
  try {
    const data = await apiFetch("/api/settings/test-llm", { method: "POST", body: {} });
    setStatus(status, "ok", `OK · ${data.provider} · ${data.model} · reply: ${data.reply}`);
  } catch (err) {
    setStatus(status, "error", `Probe failed: ${err.message}`);
  }
});

personalityForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const style = personalityStyle.value.trim();
  setStatus(personalityStatus, "loading", "Saving…");
  try {
    const data = await apiFetch("/api/personality", { method: "PATCH", body: { style } });
    personalityCurrent.textContent = data.current || "default (friendly assistant)";
    setStatus(personalityStatus, "ok", `Applied (${data.label}).`);
    personalityStyle.value = "";
  } catch (err) {
    setStatus(personalityStatus, "error", err.message);
  }
});

loadSettings();
