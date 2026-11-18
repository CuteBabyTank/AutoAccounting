"use client";

import { useEffect, useRef, useState } from "react";
import { Asterisk, Check, PencilSimple } from "@phosphor-icons/react";
import type { ExtractScope } from "@/types/extract";

/** One field as the builder holds it: the reader's label kept as `original` so an emptied rename falls back. */
export interface BuilderField {
  key: string;
  label: string;
  original: string;
  /** What the sample showed; null before any sample is read (editing). */
  value: string | null;
  scope: ExtractScope;
  picked: boolean;
  required: boolean;
}

export const LABEL_MAX = 60;
export const FOCUS =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-secondary)]";

const GROUPS: { scope: ExtractScope; title: string }[] = [
  { scope: "header", title: "On the document" },
  { scope: "row", title: "In the table rows" },
];

interface Props {
  fields: BuilderField[];
  /** Shown but not switchable yet (an unedited built-in before its sample is read). */
  locked: boolean;
  /** Keys just added by "Missing fields?", ringed for a moment. */
  fresh: ReadonlySet<string>;
  onToggle: (key: string) => void;
  onRename: (key: string, label: string) => void;
  onRequired: (key: string, required: boolean) => void;
  onPickAll: () => void;
  onClear: () => void;
}

/** Every field the reader found, as switchable chips grouped by where they sit on the document. */
export default function FieldChips({ fields, locked, fresh, onToggle, onRename, onRequired, onPickAll, onClear }: Props) {
  const picked = fields.filter((f) => f.picked).length;
  const link = `rounded text-xs font-medium text-[var(--accent)] hover:underline disabled:opacity-50 disabled:no-underline ${FOCUS}`;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="text-sm text-[var(--text-secondary)]" aria-live="polite">
          <span className="font-semibold text-[var(--text-primary)]">{picked}</span> of {fields.length} fields picked
        </p>
        <button type="button" className={link} onClick={onPickAll} disabled={locked || picked === fields.length}>
          Pick all
        </button>
        <button type="button" className={link} onClick={onClear} disabled={locked || picked === 0}>
          Clear
        </button>
      </div>
      {GROUPS.map(({ scope, title }) => {
        const group = fields.filter((f) => f.scope === scope);
        if (!group.length) return null;
        return (
          <section key={scope} className="mt-3" aria-label={title}>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--text-tertiary)]">{title}</h4>
            <div className="flex flex-wrap gap-2">
              {group.map((f) => (
                <Chip
                  key={f.key}
                  field={f}
                  locked={locked}
                  fresh={fresh.has(f.key)}
                  onToggle={() => onToggle(f.key)}
                  onRename={(label) => onRename(f.key, label)}
                  onRequired={() => onRequired(f.key, !f.required)}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function Chip({ field, locked, fresh, onToggle, onRename, onRequired }: {
  field: BuilderField;
  locked: boolean;
  fresh: boolean;
  onToggle: () => void;
  onRename: (label: string) => void;
  onRequired: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(field.label);
  const renameRef = useRef<HTMLButtonElement>(null);
  const refocus = useRef(false);
  const on = field.picked;

  // Focus goes back to the rename button when the inline input closes (it would otherwise drop to <body>).
  useEffect(() => {
    if (!editing && refocus.current) {
      refocus.current = false;
      renameRef.current?.focus();
    }
  }, [editing]);

  const finish = (label: string | null) => {
    refocus.current = true;
    setEditing(false);
    if (label !== null) onRename(label.trim() || field.original);
  };

  const shell = on
    ? "border-[var(--accent)] bg-[var(--accent)] text-white"
    : "border-[var(--border)] bg-transparent text-[var(--text-primary)] opacity-45 hover:opacity-80 focus-within:opacity-80";
  const ring = fresh ? "ring-2 ring-[var(--accent)] ring-offset-2 ring-offset-[var(--bg-secondary)] motion-safe:animate-[fadeInUp_400ms_ease-out]" : "";
  const control = `flex h-7 w-7 items-center justify-center rounded-md transition-colors hover:bg-white/20 ${FOCUS}`;

  return (
    <div
      className={`group inline-flex max-w-full items-stretch rounded-lg border transition-[opacity,box-shadow] duration-500 motion-reduce:transition-none sm:max-w-[18rem] ${shell} ${ring} ${locked ? "opacity-60" : ""}`}
    >
      {editing ? (
        <div className="flex min-w-0 items-center gap-1.5 px-2 py-1.5">
          <Check size={14} weight="bold" className="shrink-0" aria-hidden />
          <input
            autoFocus
            value={draft}
            maxLength={LABEL_MAX}
            aria-label={`Rename ${field.original}`}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => {
              if (refocus.current) return; // Enter / Escape already finished (the input may blur as it unmounts)
              setEditing(false);
              onRename(draft.trim() || field.original);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                finish(draft);
              } else if (e.key === "Escape") {
                e.preventDefault();
                e.stopPropagation(); // cancel the rename, not the dialog
                finish(null);
              }
            }}
            className="w-40 min-w-0 rounded bg-[var(--bg-card)] px-1.5 py-0.5 text-sm text-[var(--text-primary)] outline-none"
          />
        </div>
      ) : (
        <button
          type="button"
          aria-pressed={on}
          disabled={locked}
          onClick={onToggle}
          title={field.value ? `${field.label}: ${field.value}` : field.label}
          className={`flex min-w-0 items-start gap-1.5 rounded-lg px-2.5 py-1.5 text-left disabled:cursor-default ${FOCUS}`}
        >
          {on && <Check size={14} weight="bold" className="mt-0.5 shrink-0" aria-hidden />}
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium">
              {field.label}
              {field.required && on && <span className="sr-only"> (required)</span>}
            </span>
            {field.value !== null && (
              <span className={`block truncate text-xs ${on ? "text-white/80" : "text-[var(--text-secondary)]"}`}>
                {field.value || "Not on this sample"}
              </span>
            )}
          </span>
        </button>
      )}
      {on && !locked && !editing && (
        <span className="flex shrink-0 items-center gap-0.5 border-l border-white/25 px-1">
          <button
            ref={renameRef}
            type="button"
            className={`${control} opacity-75 group-hover:opacity-100 group-focus-within:opacity-100`}
            title="Rename"
            aria-label={`Rename ${field.label}`}
            onClick={() => {
              setDraft(field.label);
              setEditing(true);
            }}
          >
            <PencilSimple size={14} aria-hidden />
          </button>
          <button
            type="button"
            className={`${control} ${
              field.required
                ? "bg-white text-[var(--accent)] hover:bg-white/90"
                : "opacity-75 group-hover:opacity-100 group-focus-within:opacity-100"
            }`}
            title={field.required ? "Required: flagged when blank" : "Mark required"}
            aria-label={`Required: ${field.label}`}
            aria-pressed={field.required}
            onClick={onRequired}
          >
            <Asterisk size={14} weight="bold" aria-hidden />
          </button>
        </span>
      )}
    </div>
  );
}
