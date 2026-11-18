"use client";

import type { ExtractCheck } from "@/types/extract";
import { FOCUS, type BuilderField } from "@/components/extract/FieldChips";

const FIELD_PARAMS = ["field", "target", "base", "row_field", "a", "b", "first", "last", "limit_field"] as const;

/** Every field key a check refers to (mirrors backend extract/spec.check_fields). */
export function checkFields(check: ExtractCheck): string[] {
  const keys = (check.terms ?? []).map((t) => t.field);
  for (const name of FIELD_PARAMS) {
    const value = check[name];
    if (typeof value === "string") keys.push(value);
  }
  return keys;
}

interface Props {
  checks: ExtractCheck[];
  fields: BuilderField[];
  /** Switched-off check ids (every check starts on). */
  off: ReadonlySet<string>;
  locked: boolean;
  onToggle: (id: string) => void;
  onRequired: (key: string, required: boolean) => void;
}

/** The proposed checks as plain sentences with a switch each. A "required" check is its field's Required flag. */
export default function CheckList({ checks, fields, off, locked, onToggle, onRequired }: Props) {
  if (!checks.length) return null;
  const byKey = new Map(fields.map((f) => [f.key, f]));

  return (
    <section aria-labelledby="extract-checks-title">
      <h3 id="extract-checks-title" className="text-sm font-semibold text-[var(--text-primary)]">
        Checks we&apos;ll run
      </h3>
      <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
        Anything that fails is highlighted yellow or red for review.
      </p>
      <ul className={`mt-2 divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] ${locked ? "opacity-60" : ""}`}>
        {checks.map((check) => {
          const keys = checkFields(check);
          const missing = keys.filter((k) => !byKey.get(k)?.picked);
          const blocked = missing.length > 0;
          const requiredField = check.kind === "required" && check.field ? byKey.get(check.field) : undefined;
          const on = requiredField ? requiredField.required : !off.has(check.id);
          const disabled = locked || blocked;
          const toggle = () =>
            requiredField ? onRequired(requiredField.key, !requiredField.required) : onToggle(check.id);
          const needs = [...new Set(missing)].map((k) => byKey.get(k)?.label ?? k).join(", ");
          return (
            <li key={check.id} className={`flex items-center gap-3 px-3 py-2 ${blocked ? "opacity-55" : ""}`}>
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{
                  background: check.level === "red" ? "var(--alert-error-icon)" : "var(--alert-warning-icon)",
                }}
                title={check.level === "red" ? "Flags red" : "Flags yellow"}
                aria-hidden
              />
              <span className="min-w-0 flex-1 text-sm text-[var(--text-primary)]">
                {check.sentence}
                <span className="sr-only">{check.level === "red" ? " (flags red)" : " (flags yellow)"}</span>
                {blocked && <span className="block text-xs text-[var(--text-secondary)]">needs: {needs}</span>}
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={on && !blocked}
                aria-label={check.sentence}
                disabled={disabled}
                onClick={toggle}
                className={`relative h-5 w-9 shrink-0 rounded-full transition-colors motion-reduce:transition-none disabled:cursor-not-allowed ${
                  on && !blocked ? "bg-[var(--accent)]" : "bg-[var(--border)]"
                } ${FOCUS}`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform motion-reduce:transition-none ${
                    on && !blocked ? "translate-x-4" : ""
                  }`}
                />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
