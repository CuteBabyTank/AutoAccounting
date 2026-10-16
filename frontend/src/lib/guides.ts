"use client";

import { useCallback, useEffect, useState } from "react";

/** Dismissed guides are remembered per browser; "Show guides again" in the sidebar clears them. */
const PREFIX = "aa:guide:";
const RESET_EVENT = "aa:guides-reset";

function isDismissed(id: string): boolean {
  try {
    return localStorage.getItem(PREFIX + id) === "1";
  } catch {
    return false;
  }
}

/**
 * Whether a guide is showing. It opens on its own until the user dismisses it once,
 * unless autoOpen is false (then only its button opens it).
 */
export function useGuide(id: string, { autoOpen = true }: { autoOpen?: boolean } = {}) {
  // Closed for the first render so server and client markup match; the effect opens it.
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(autoOpen && !isDismissed(id));
    const reset = () => setOpen(autoOpen);
    window.addEventListener(RESET_EVENT, reset);
    return () => window.removeEventListener(RESET_EVENT, reset);
  }, [id, autoOpen]);

  const dismiss = useCallback(() => {
    setOpen(false);
    try {
      localStorage.setItem(PREFIX + id, "1");
    } catch {
      // not persisted; it comes back next visit
    }
  }, [id]);

  const toggle = useCallback(() => {
    if (open) dismiss();
    else setOpen(true);
  }, [open, dismiss]);

  return { open, dismiss, toggle };
}

/** Bring back every dismissed guide on every page. */
export function resetGuides() {
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(PREFIX)) localStorage.removeItem(key);
    }
  } catch {
    // storage unavailable; open guides still reopen below
  }
  window.dispatchEvent(new Event(RESET_EVENT));
}
