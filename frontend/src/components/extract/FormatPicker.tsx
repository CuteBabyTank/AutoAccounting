"use client";

import { PencilSimple } from "@phosphor-icons/react";
import type { ExtractFormat } from "@/types/extract";

export const AUTO = "auto";
const ADD = "__add__";

interface Props {
  formats: ExtractFormat[];
  value: string; // "auto" or a format key
  onChange: (value: string) => void;
  canManage: boolean;
  onAdd: () => void;
  onEdit: (format: ExtractFormat) => void;
}

/** Which format a drop is read with: Auto detect, the built-ins (an edited one in its place), the firm's own. */
export default function FormatPicker({ formats, value, onChange, canManage, onAdd, onEdit }: Props) {
  const builtins = formats.filter((f) => f.builtin || f.edited);
  const own = formats.filter((f) => !f.builtin && !f.edited);
  const selected = formats.find((f) => f.key === value) ?? null;
  const current = selected ? selected.key : AUTO;

  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <label className="flex min-w-0 items-center gap-2 rounded-lg border border-[var(--accent)] bg-[var(--accent-subtle)] px-3 py-1.5 text-sm">
        <span className="shrink-0 text-[var(--text-secondary)]">Read as:</span>
        <select
          value={current}
          onChange={(e) => (e.target.value === ADD ? onAdd() : onChange(e.target.value))}
          className="min-w-0 max-w-[220px] bg-transparent font-medium text-[var(--text-primary)] focus:outline-none"
        >
          <option value={AUTO}>Auto detect</option>
          {builtins.length > 0 && (
            <optgroup label="Built-in">
              {builtins.map((f) => (
                <option key={f.key} value={f.key}>{f.edited ? `${f.name} (edited)` : f.name}</option>
              ))}
            </optgroup>
          )}
          {own.length > 0 && (
            <optgroup label="Your firm's formats">
              {own.map((f) => (
                <option key={f.key} value={f.key}>{f.name}</option>
              ))}
            </optgroup>
          )}
          {canManage && <option value={ADD}>+ Add new</option>}
        </select>
      </label>
      {selected?.edited && (
        <span className="shrink-0 rounded-full border border-[var(--border)] px-2 py-0.5 text-xs font-medium text-[var(--text-secondary)]"
          title="Your firm changed this built-in format">
          Edited
        </span>
      )}
      {canManage && selected && (
        <button
          type="button"
          onClick={() => onEdit(selected)}
          title={`Edit ${selected.name}`}
          aria-label={`Edit ${selected.name}`}
          className="shrink-0 rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
        >
          <PencilSimple size={16} />
        </button>
      )}
    </div>
  );
}
