"use client";

import { useEffect, useState } from "react";
import { Plus, X } from "@phosphor-icons/react";
import { loadPicks, removePick, savePick } from "@/lib/quick-picks";

interface Props {
  /** Storage key: one list per kind of field ("review-reason", "task-title"…). */
  kind: string;
  /** Built-in phrases shown after the person's own. */
  presets?: readonly string[];
  /** What's typed now: offered as "+ Save" when it isn't a pick yet. */
  value: string;
  onPick: (text: string) => void;
  maxLength?: number;
  /** Layout override, e.g. a full-width row inside a flex toolbar. */
  className?: string;
}

const CHIP =
  "inline-flex max-w-full items-center gap-1 rounded-full border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--text-primary)]";

/** One-click phrases under a text field, plus "+ Save" to keep what was just typed for next time. */
export default function QuickPicks({ kind, presets = [], value, onPick, maxLength = 120, className = "mt-1.5" }: Props) {
  const [saved, setSaved] = useState<string[]>([]);
  useEffect(() => setSaved(loadPicks(kind)), [kind]);

  const typed = value.trim();
  const seen = new Set(saved.map((p) => p.toLowerCase()));
  const builtIn = presets.filter((p) => !seen.has(p.toLowerCase()));
  const known = typed && (seen.has(typed.toLowerCase()) || builtIn.some((p) => p.toLowerCase() === typed.toLowerCase()));
  const canSave = typed.length >= 3 && typed.length <= maxLength && !known;
  if (!saved.length && !builtIn.length && !canSave) return null;

  return (
    <div className={`${className} flex flex-wrap gap-1.5`} aria-label="Quick picks">
      {saved.map((p) => (
        <span key={`s:${p}`} className={`${CHIP} pr-1`}>
          <button type="button" className="truncate" title={p} onClick={() => onPick(p)}>{p}</button>
          <button
            type="button"
            aria-label={`Forget "${p}"`}
            title="Forget this pick"
            className="rounded-full p-0.5 hover:bg-[var(--bg-hover)]"
            onClick={() => setSaved(removePick(kind, p))}
          >
            <X size={10} />
          </button>
        </span>
      ))}
      {builtIn.map((p) => (
        <button key={`p:${p}`} type="button" className={CHIP} title={p} onClick={() => onPick(p)}>
          <span className="truncate">{p}</span>
        </button>
      ))}
      {canSave && (
        <button
          type="button"
          className={`${CHIP} border-dashed text-[var(--accent)]`}
          title="Keep this as a quick pick on this browser"
          onClick={() => setSaved(savePick(kind, typed))}
        >
          <Plus size={11} /> Save &ldquo;<span className="max-w-[12rem] truncate">{typed}</span>&rdquo;
        </button>
      )}
    </div>
  );
}
