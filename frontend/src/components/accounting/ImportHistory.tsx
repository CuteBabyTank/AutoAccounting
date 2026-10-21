"use client";

import { useCallback, useEffect, useState } from "react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { safeId } from "@/lib/work-api";
import { BTN, BTN_PRIMARY, Chip } from "@/components/work/ui";
import type { ImportBatch, ImportBatches, ImportKind } from "@/types/accounting";

interface Props {
  companyId: string;
  /** Bumped by the Import page after a confirmed import, so the list reloads. */
  version: number;
  onUndone: (kind: ImportKind) => void;
}

const KIND: Record<ImportKind, { label: string; unit: [string, string] }> = {
  "opening-tb": { label: "Opening balances", unit: ["line", "lines"] },
  "open-items": { label: "Open items", unit: ["open item", "open items"] },
  "journal-entries": { label: "Journal entries", unit: ["journal entry", "journal entries"] },
};
const TH = "px-2 py-1.5 text-left text-[11px] font-medium text-[var(--text-secondary)]";
const TD = "px-2 py-1.5 align-top";
const when = (iso: string) =>
  new Date(iso).toLocaleString("en-PH", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
const rows = (b: ImportBatch) => `${b.row_count} ${KIND[b.kind].unit[b.row_count === 1 ? 0 : 1]}`;

function effect(b: ImportBatch): string {
  if (b.kind === "opening-tb") return "This puts back the opening balances it replaced (or removes them if there were none before it).";
  return `This removes the ${rows(b)} it added${b.kind === "journal-entries" ? " to the books" : ""}.`;
}

/** Import page → Recent imports: every confirmed import of the company, with an in-page confirmed Undo. */
export default function ImportHistory({ companyId, version, onUndone }: Props) {
  const [data, setData] = useState<ImportBatches | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const [loadError, setLoadError] = useState("");

  const load = useCallback(() => {
    accountingApi
      .importBatches(companyId)
      .then((d) => {
        setData(d);
        setLoadError("");
      })
      .catch((e) => setLoadError(apiErrorMessage(e, "Couldn't load the recent imports")));
  }, [companyId]);
  useEffect(load, [load, version]);

  async function undo(b: ImportBatch) {
    const id = safeId(b.id);
    if (!id) return;
    setBusy(id);
    setErrors((all) => ({ ...all, [id]: "" }));
    setNotice("");
    try {
      const out = await accountingApi.undoImport(id);
      setAsking(null);
      setNotice(
        [
          out.restored ? `Undone: the earlier opening balances are back (${b.filename}).` : `Undone: removed ${out.removed} ${KIND[b.kind].unit[out.removed === 1 ? 0 : 1]} (${b.filename}).`,
          ...out.warnings,
        ].join(" "),
      );
      load();
      onUndone(b.kind);
    } catch (e) {
      setErrors((all) => ({ ...all, [id]: apiErrorMessage(e, "Couldn't undo the import") }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mt-6">
      <h3 className="mb-1 text-sm font-semibold text-[var(--text-primary)]">Recent imports</h3>
      <p className="mb-2 text-[11px] text-[var(--text-secondary)]">
        Imports made before Oct 19, 2026 aren&apos;t listed and can&apos;t be undone here: delete their entries or open items by hand.
      </p>
      {loadError && <p className="mb-2 text-sm text-[var(--badge-red-text)]">{loadError}</p>}
      {notice && <p className="mb-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)]">{notice}</p>}
      {data && data.batches.length === 0 && <p className="text-sm text-[var(--text-secondary)]">No imports yet.</p>}
      {data && data.batches.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className={TH}>When</th><th className={TH}>Import</th><th className={TH}>File</th><th className={TH}>Rows</th>
                <th className={TH}>By</th><th className={TH}>Status</th><th className={TH}></th>
              </tr>
            </thead>
            <tbody>
              {data.batches.map((b) => {
                const id = safeId(b.id) ?? b.id;
                const error = errors[id];
                return (
                  <tr key={id} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                    <td className={`${TD} whitespace-nowrap`}>{when(b.created_at)}</td>
                    <td className={TD}>{KIND[b.kind].label}</td>
                    <td className={`${TD} [overflow-wrap:anywhere]`}>{b.filename || "(no name)"}</td>
                    <td className={`${TD} whitespace-nowrap`}>{rows(b)}</td>
                    <td className={`${TD} [overflow-wrap:anywhere]`}>{b.created_by || "(removed user)"}</td>
                    <td className={TD}>
                      {b.status === "active" && <Chip tone="green">In the books</Chip>}
                      {b.status === "emptied" && <Chip title="Everything it wrote was deleted by hand since">Deleted by hand</Chip>}
                      {b.status === "replaced" && <Chip tone="yellow" title="A later import or an edit changed these opening balances">Replaced</Chip>}
                      {b.status === "undone" && (
                        <>
                          <Chip>Undone</Chip>
                          {b.undone_at && (
                            <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">
                              {when(b.undone_at)}{b.undone_by ? ` · ${b.undone_by}` : ""}
                            </span>
                          )}
                        </>
                      )}
                    </td>
                    <td className={TD}>
                      {data.can_undo && b.status === "active" && asking !== id && (
                        <button className={BTN} disabled={busy !== null} onClick={() => { setAsking(id); setNotice(""); }}>Undo</button>
                      )}
                      {asking === id && (
                        <div className="max-w-80 space-y-2">
                          <p className="text-[12px] text-[var(--text-secondary)]">{effect(b)}</p>
                          <div className="flex flex-wrap gap-2">
                            <button className={BTN_PRIMARY} disabled={busy !== null} onClick={() => undo(b)}>
                              {busy === id ? "Undoing…" : "Undo import"}
                            </button>
                            <button className={BTN} disabled={busy !== null} onClick={() => { setAsking(null); setErrors((all) => ({ ...all, [id]: "" })); }}>
                              Keep it
                            </button>
                          </div>
                        </div>
                      )}
                      {error && <p className="mt-1 max-w-80 text-[12px] text-[var(--badge-red-text)]">{error}</p>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
