"use client";

import type { Company } from "@/types/accounting";

interface Props {
  companies: Company[];
  value: string; // "auto" or a company id
  onChange: (value: string) => void;
}

export default function CompanyPicker({ companies, value, onChange }: Props) {
  const pinned = companies.filter((c) => c.pinned);
  const rest = companies.filter((c) => !c.pinned);
  const current = companies.some((c) => c.id === value) ? value : "auto";

  return (
    <label className="flex items-center gap-2 rounded-lg border border-[var(--accent)] bg-[var(--accent-subtle)] px-3 py-1.5 text-sm">
      <span className="text-[var(--text-secondary)]">Drop files for:</span>
      <select
        value={current}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-[220px] bg-transparent font-medium text-[var(--text-primary)] focus:outline-none"
      >
        <option value="auto">Auto-detect</option>
        {pinned.length > 0 && (
          <optgroup label="Pinned">
            {pinned.map((c) => (
              <option key={c.id} value={c.id}>{c.registered_name}</option>
            ))}
          </optgroup>
        )}
        {rest.length > 0 && (
          <optgroup label="All companies">
            {rest.map((c) => (
              <option key={c.id} value={c.id}>{c.registered_name}</option>
            ))}
          </optgroup>
        )}
      </select>
    </label>
  );
}
