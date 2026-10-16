"use client";

import { Question, X } from "@phosphor-icons/react";
import type { GuideStep } from "@/lib/guides";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  steps: GuideStep[];
  /** Smaller variant for panels inside a page. */
  compact?: boolean;
}

/** Numbered "how this works" card. Closing it remembers the choice (see useGuide). */
export default function PageGuide({ open, onClose, title, steps, compact }: Props) {
  if (!open) return null;
  return (
    <section
      aria-label={title}
      className={`page-enter relative rounded-xl border border-[var(--border)] bg-[var(--accent-subtle)] ${compact ? "mb-4 p-3" : "mb-6 p-4 sm:p-5"}`}
    >
      <div className="mb-3 flex items-center gap-2 pr-8">
        <Question size={compact ? 16 : 18} className="shrink-0 text-[var(--accent)]" />
        <h2 className={`font-semibold text-[var(--text-primary)] ${compact ? "text-sm" : "text-base"}`}>{title}</h2>
      </div>
      <button
        onClick={onClose}
        aria-label="Hide guide"
        title="Hide guide"
        className="absolute right-2 top-2 rounded-md p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
      >
        <X size={14} />
      </button>
      <ol className={`grid gap-3 ${steps.length >= 4 ? "sm:grid-cols-2 xl:grid-cols-4" : "sm:grid-cols-3"}`}>
        {steps.map((s, i) => (
          <li key={s.title} className="flex gap-2.5">
            <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[var(--accent)] text-[11px] font-semibold text-white">
              {i + 1}
            </span>
            <div className="min-w-0">
              <p className="text-sm font-medium text-[var(--text-primary)]">{s.title}</p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">{s.body}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-3 flex justify-end">
        <button onClick={onClose} className="text-xs font-semibold text-[var(--accent)] hover:underline">
          Got it
        </button>
      </div>
    </section>
  );
}

/** Header button that reopens (or hides) a page's guide. */
export function GuideButton({ open, onClick, label = "How this works" }: { open: boolean; onClick: () => void; label?: string }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={open}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm ${
        open
          ? "border-[var(--accent)] bg-[var(--accent-subtle)] text-[var(--text-primary)]"
          : "border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
      }`}
    >
      <Question size={15} /> {label}
    </button>
  );
}
