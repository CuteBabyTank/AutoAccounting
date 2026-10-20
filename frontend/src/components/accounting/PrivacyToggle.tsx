"use client";

import { Eye, EyeSlash } from "@phosphor-icons/react";
import { usePrivacy } from "@/lib/privacy";

/** Blur amounts on dashboards (for screen-sharing with a client). Remembered on this browser. */
export default function PrivacyToggle({ className = "" }: { className?: string }) {
  const [hidden, toggle] = usePrivacy();
  return (
    <button
      type="button"
      aria-pressed={hidden}
      data-tour="privacy"
      onClick={toggle}
      title={hidden ? "Show amounts" : "Hide amounts while you share your screen"}
      className={`inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] ${className}`}
    >
      {hidden ? <EyeSlash size={16} /> : <Eye size={16} />}
      {hidden ? "Amounts hidden" : "Hide amounts"}
    </button>
  );
}
