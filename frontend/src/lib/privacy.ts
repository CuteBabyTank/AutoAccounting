// "Hide amounts" while screen-sharing: per viewer, kept in localStorage (best effort), shared by every toggle on the
// page. Elements with the class `aa-amount` blur while it is on (globals.css).
import { useSyncExternalStore } from "react";

const KEY = "autoaccounting_hide_amounts";
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return document.documentElement.dataset.privacy === "on";
  }
}

function apply(on: boolean): void {
  document.documentElement.dataset.privacy = on ? "on" : "off";
}

export function setPrivacy(on: boolean): void {
  try {
    window.localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    // storage blocked: still hide for this page view
  }
  apply(on);
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  apply(read());
  return () => listeners.delete(listener);
}

/** [amounts hidden?, toggle] */
export function usePrivacy(): [boolean, () => void] {
  const on = useSyncExternalStore(subscribe, read, () => false);
  return [on, () => setPrivacy(!on)];
}
