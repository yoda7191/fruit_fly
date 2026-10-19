// apiKey.ts — the API key field, shown only when the server requires keys.
//
// The key is remembered in this browser (localStorage) as a convenience; storage
// can be unavailable (private windows, blocked site data), so every access is
// guarded and the field still works for the current page.

import type { ApiClient } from "../api";
import { byId } from "./dom";

const STORAGE_KEY = "fruit_fly.apiKey";

export function loadKey(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function saveKey(key: string): void {
  try {
    if (key) window.localStorage.setItem(STORAGE_KEY, key);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // not remembered; still used for this page
  }
}

/** Show the field when keys are required, and keep the client's key in sync with it. */
export function setupApiKey(api: ApiClient, required: boolean): void {
  const label = byId("api-key-label", HTMLLabelElement);
  const input = byId("api-key", HTMLInputElement);
  label.hidden = !required;
  if (!required) return;
  input.value = loadKey() ?? "";
  api.apiKey = input.value.trim() || null;
  input.addEventListener("change", () => {
    const key = input.value.trim();
    api.apiKey = key || null;
    saveKey(key);
  });
}
