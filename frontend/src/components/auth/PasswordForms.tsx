"use client";

import { useState } from "react";
import { Eye, EyeSlash } from "@phosphor-icons/react";

export const FIELD =
  "w-full rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/20";
export const PRIMARY =
  "w-full rounded-lg bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60";
export const LINK = "font-medium text-[var(--accent)] hover:underline underline-offset-2";

export const MIN_PASSWORD = 10;

/** A password box with a show / hide eye. `autoComplete` tells password managers what it is. */
export function PasswordField({ id, label, value, onChange, autoComplete, hint }: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete: "current-password" | "new-password";
  hint?: React.ReactNode;
}) {
  const [shown, setShown] = useState(false);
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-[var(--text-primary)]">{label}</label>
      <div className="relative">
        <input
          id={id}
          type={shown ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          required
          maxLength={128}
          className={`${FIELD} pr-10`}
        />
        <button
          type="button"
          onClick={() => setShown((s) => !s)}
          aria-label={shown ? "Hide password" : "Show password"}
          aria-pressed={shown}
          className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
        >
          {shown ? <EyeSlash size={18} /> : <Eye size={18} />}
        </button>
      </div>
      {hint}
    </div>
  );
}

/** Live guidance for a new password: length first, since that's what matters most. */
export function NewPasswordHint({ value }: { value: string }) {
  const n = [...value].length;
  const ok = n >= MIN_PASSWORD;
  return (
    <p className={`mt-1 text-xs ${ok ? "text-[var(--accent)]" : "text-[var(--text-secondary)]"}`} aria-live="polite">
      {ok
        ? "Good length. A phrase only you would know is hard to guess."
        : `At least ${MIN_PASSWORD} characters (${n}/${MIN_PASSWORD}). A short phrase works well, e.g. "mga resibo ni lola".`}
    </p>
  );
}

export function EmailField({ value, onChange, autoFocus }: { value: string; onChange: (v: string) => void; autoFocus?: boolean }) {
  return (
    <div>
      <label htmlFor="email" className="mb-1 block text-sm font-medium text-[var(--text-primary)]">Email</label>
      <input
        id="email"
        type="email"
        inputMode="email"
        autoComplete="email"
        autoFocus={autoFocus}
        required
        maxLength={254}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="you@firm.com"
        className={FIELD}
      />
    </div>
  );
}

export function Divider({ label }: { label: string }) {
  return (
    <div className="my-5 flex items-center gap-3 text-xs text-[var(--text-tertiary)]">
      <span className="h-px flex-1 bg-[var(--border)]" />
      {label}
      <span className="h-px flex-1 bg-[var(--border)]" />
    </div>
  );
}
