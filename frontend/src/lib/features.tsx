"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import api from "@/lib/api";
import { useAuth } from "@/lib/auth";

/** Maintenance switches the platform admin flips (backend `services/features.py` is the source of the list). */
export type FeatureKey =
  | "documents" | "work" | "companies" | "team" | "upload" | "search" | "notifications"
  | "filing" | "annual" | "employees" | "books" | "close" | "recurring" | "bank" | "subledgers"
  | "reports" | "reclassify" | "imports" | "atc" | "audit" | "assistant";

/** Ask every open screen to re-read the switches (the admin panel after a change, a 503 from a switched-off route). */
export const FEATURES_STALE = "aa:features-stale";
export const markFeaturesStale = () => {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(FEATURES_STALE));
};

interface State {
  /** False until the first load (pages that are switched off wait for it, so they never flash). */
  ready: boolean;
  enabled: Partial<Record<FeatureKey, boolean>>;
  /** Keys off for every firm; only the admin's screens use it (to mark what firms can't see). */
  off: FeatureKey[];
}

const Ctx = createContext<State>({ ready: false, enabled: {}, off: [] });
const REFRESH_MS = 60_000;

export function FeaturesProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [state, setState] = useState<State>({ ready: false, enabled: {}, off: [] });
  const signedIn = !!user && user.role !== "unverified";

  const load = useCallback(() => {
    api.get<{ enabled: Record<FeatureKey, boolean>; off: FeatureKey[] }>("/features")
      .then((r) => setState({ ready: true, enabled: r.data.enabled, off: r.data.off }))
      // Can't tell: leave everything on (the server still refuses what's off).
      .catch(() => setState((s) => ({ ...s, ready: true })));
  }, []);

  useEffect(() => {
    if (!signedIn) {
      setState({ ready: false, enabled: {}, off: [] });
      return;
    }
    load();
    const timer = setInterval(load, REFRESH_MS);
    const onFocus = () => document.visibilityState === "visible" && load();
    window.addEventListener(FEATURES_STALE, load);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener(FEATURES_STALE, load);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [signedIn, user?.id, load]);

  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}

export function useFeatures(): State & { on: (key: FeatureKey) => boolean } {
  const state = useContext(Ctx);
  const on = useCallback((key: FeatureKey) => state.enabled[key] !== false, [state.enabled]);
  return { ...state, on };
}

/** Shown in place of a page or panel whose feature is switched off. */
export function FeatureOff({ label, compact = false }: { label: string; compact?: boolean }) {
  if (compact) {
    return (
      <p className="rounded-lg border border-dashed border-[var(--border)] px-3 py-2 text-xs text-[var(--text-secondary)]">
        {label} is turned off for maintenance. It&apos;ll be back shortly.
      </p>
    );
  }
  return (
    <div className="grid min-h-[50vh] place-items-center px-6">
      <div className="max-w-sm text-center">
        <h1 className="text-lg font-semibold text-[var(--text-primary)]">{label} is down for maintenance</h1>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          We&apos;re updating it right now. Your work is safe; please check back shortly.
        </p>
      </div>
    </div>
  );
}
