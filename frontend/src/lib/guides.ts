"use client";

import { useCallback, useEffect, useState } from "react";

/** Seen / dismissed guides are remembered per browser; "Show guides" in the sidebar clears them. */
const PREFIX = "aa:guide:";
const RESET_EVENT = "aa:guides-reset";

function isDismissed(id: string): boolean {
  try {
    return localStorage.getItem(PREFIX + id) === "1";
  } catch {
    return false;
  }
}

// When each guide first opened on its own in this page load. The page can mount more than once while it settles
// (sign-in, React dev re-running effects); a remount this soon is still the first visit, so the guide stays open.
const autoShownAt = new Map<string, number>();
const REMOUNT_MS = 5000;

function markSeen(id: string) {
  try {
    localStorage.setItem(PREFIX + id, "1");
  } catch {
    // not persisted; it comes back next visit
  }
}

/**
 * Whether a guide is showing. A page's "How this works" guide opens on its own only the first time the page is
 * visited in this browser; after that only its button opens it. ``once: false`` keeps opening it on each visit
 * until it's dismissed (the getting-started checklist); ``autoOpen: false`` never opens it on its own.
 */
export function useGuide(id: string, { autoOpen = true, once = true }: { autoOpen?: boolean; once?: boolean } = {}) {
  // Closed for the first render so server and client markup match; the effect opens it.
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const shownAt = autoShownAt.get(id);
    const first = autoOpen && (!isDismissed(id) || (shownAt !== undefined && Date.now() - shownAt < REMOUNT_MS));
    setOpen(first);
    if (first && once) {
      if (shownAt === undefined) autoShownAt.set(id, Date.now());
      markSeen(id);
    }
    const reset = () => setOpen(autoOpen);
    window.addEventListener(RESET_EVENT, reset);
    return () => window.removeEventListener(RESET_EVENT, reset);
  }, [id, autoOpen, once]);

  const dismiss = useCallback(() => {
    setOpen(false);
    autoShownAt.delete(id);
    markSeen(id);
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
