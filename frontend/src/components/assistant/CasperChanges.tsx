"use client";

import { useEffect, useState } from "react";
import { ArrowLeft } from "@phosphor-icons/react";
import ActionCard from "@/components/assistant/ActionCard";
import { listActions } from "@/lib/assistant-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { AssistantAction } from "@/types/assistant";

const stamp = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** Everything Casper changed in the last 7 days, with Undo / Restore while it's still open. */
export default function CasperChanges({ onBack, onChange }: {
  onBack: () => void;
  onChange: (next: AssistantAction) => void;
}) {
  const [rows, setRows] = useState<AssistantAction[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    listActions()
      // Only changes that happened (or were tried); a proposal is confirmed from its card in the chat.
      .then((list) => setRows(list.filter((a) => a.status !== "proposed" && a.status !== "cancelled" && a.status !== "expired")))
      .catch((e) => setError(apiErrorMessage(e, "Couldn't load Casper's changes")));
  }, []);

  const replace = (next: AssistantAction) => {
    setRows((list) => (list ?? []).map((a) => (a.id === next.id ? next : a)));
    onChange(next);
  };

  return (
    <div>
      <button type="button" onClick={onBack} className="mb-4 flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
        <ArrowLeft size={14} />
        Back to the chat
      </button>
      <h3 className="text-[15px] font-medium text-[var(--text-primary)]">Casper&apos;s changes</h3>
      <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
        The last 7 days. Anything Casper deleted can be restored until its 7 days are up.
      </p>
      {error && <p className="mt-4 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {rows === null && !error && <p className="mt-4 text-sm text-[var(--text-tertiary)]">Loading…</p>}
      {rows && rows.length === 0 && <p className="mt-4 text-sm text-[var(--text-secondary)]">No changes yet.</p>}
      {rows && rows.length > 0 && (
        <ul className="mt-4 space-y-3">
          {rows.map((a) => (
            <li key={a.id}>
              <p className="mb-1 text-[11.5px] text-[var(--text-tertiary)]">
                {stamp.format(new Date(a.applied_at ?? a.created_at)).replace(" at", ",")}
                {a.user_name ? `, asked by ${a.user_name}` : ""}
              </p>
              <ActionCard action={a} onChange={replace} compact />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
