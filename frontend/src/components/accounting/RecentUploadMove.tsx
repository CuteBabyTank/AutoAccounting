"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowsLeftRight, ClockCounterClockwise, X } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Company, RecentUpload, UploadMoveResult } from "@/types/accounting";

const SHOW_FOR_MS = 7 * 24 * 3600 * 1000;   // a week-old drop isn't "the one I just did"
const dismissKey = (id: string) => `aa:upload-strip-dismissed:${id}`;

function dismissed(id: string): boolean {
  try {
    return localStorage.getItem(dismissKey(id)) === "1";
  } catch {
    return false;
  }
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "Last upload · 51 documents in Bayanihan … · Move to another company": the quick fix for a drop filed under
 *  the wrong company. ``reloadKey`` changes when an upload finishes, so the strip follows the newest one. */
export default function RecentUploadMove({ reloadKey, onMoved }: { reloadKey: number; onMoved: () => void }) {
  const [recent, setRecent] = useState<RecentUpload | null>(null);
  const [open, setOpen] = useState(false);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    accountingApi
      .latestUpload()
      .then((r) => {
        if (cancelled) return;
        setRecent(r);
        setHidden(r ? dismissed(r.id) : false);
      })
      .catch(() => undefined);   // a convenience: no strip if it can't load
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  if (!recent || hidden || Date.now() - new Date(recent.created_at).getTime() > SHOW_FOR_MS) return null;
  const documents = recent.files.reduce((n, f) => n + f.documents, 0);
  const companies = [...new Map(recent.files.flatMap((f) => f.companies).map((c) => [c.id, c])).values()];
  const where = companies.length === 1 ? companies[0].registered_name : `${companies.length} companies`;
  const when = new Date(recent.created_at).toLocaleString("en-PH", { dateStyle: "medium", timeStyle: "short" });

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-2 text-sm text-[var(--text-primary)]">
        <ClockCounterClockwise size={16} className="shrink-0 text-[var(--text-secondary)]" />
        <span className="min-w-0 flex-1">
          <span className="font-medium">Last upload</span>
          <span className="text-[var(--text-secondary)]"> · {plural(documents, "document")} in {where} · {when}</span>
        </span>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs font-medium hover:bg-[var(--bg-hover)]"
        >
          <ArrowsLeftRight size={13} />
          Wrong company? Move them
        </button>
        <button
          type="button"
          aria-label="Hide"
          title="Hide"
          onClick={() => {
            try {
              localStorage.setItem(dismissKey(recent.id), "1");
            } catch {
              /* hidden for this visit only */
            }
            setHidden(true);
          }}
          className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
        >
          <X size={14} />
        </button>
      </div>
      {open && (
        <MoveUploadDialog
          recent={recent}
          onClose={() => setOpen(false)}
          onMoved={(result) => {
            setRecent(result.upload);
            onMoved();
          }}
        />
      )}
    </>
  );
}

function MoveUploadDialog({ recent, onClose, onMoved }: {
  recent: RecentUpload;
  onClose: () => void;
  onMoved: (result: UploadMoveResult) => void;
}) {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [companyId, setCompanyId] = useState("");
  const [picked, setPicked] = useState<Set<string>>(() => new Set(recent.files.map((f) => f.id)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<UploadMoveResult | null>(null);

  useEffect(() => {
    accountingApi
      .listCompanies()
      .then((list) => {
        setCompanies(list);
        // Default to a company the drop isn't in: the usual fix is "these belong to the other client".
        const current = new Set(recent.files.flatMap((f) => f.companies.map((c) => c.id)));
        setCompanyId(list.find((c) => !current.has(c.id))?.id ?? list[0]?.id ?? "");
      })
      .catch((e) => setError(apiErrorMessage(e, "Couldn't load the companies")));
  }, [recent]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  // Documents that would actually move: the picked files' documents not already in the chosen company.
  const moving = recent.files
    .filter((f) => picked.has(f.id) && f.companies.some((c) => c.id !== companyId))
    .reduce((n, f) => n + f.documents, 0);
  const toggle = (id: string) =>
    setPicked((p) => {
      const next = new Set(p);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  async function move() {
    if (!companyId || picked.size === 0 || busy) return;
    setBusy(true);
    setError("");
    try {
      const r = await accountingApi.moveUpload(recent.id, companyId, [...picked]);
      onMoved(r);
      if (r.refused.length === 0) onClose();
      else setResult(r);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't move the documents"));
    } finally {
      setBusy(false);
    }
  }

  return createPortal(
    <div
      className="lp-skin overlay-enter fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => e.target === e.currentTarget && !busy && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="move-upload-title"
        className="modal-enter flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-6 shadow-xl"
      >
        <div className="mb-1 flex items-center justify-between">
          <h3 id="move-upload-title" className="text-lg font-semibold text-[var(--text-primary)]">Move the last upload</h3>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
            className="-mr-1.5 rounded-lg p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-primary)]"
          >
            <X size={18} />
          </button>
        </div>
        <p className="mb-4 text-sm text-[var(--text-secondary)]">
          Each document is sorted again for the new company: a sale here can be a purchase there.
        </p>

        {result ? (
          <div className="min-h-0 overflow-y-auto text-sm text-[var(--text-primary)]">
            <p className="mb-2">
              {plural(result.moved, "document")} moved. {plural(result.refused.length, "document")} stayed where{" "}
              {result.refused.length === 1 ? "it was" : "they were"}:
            </p>
            <ul className="space-y-1.5">
              {result.refused.map((r, i) => (
                <li key={i} className="rounded-md border border-[var(--border)] px-3 py-2">
                  <span className="font-medium">{r.document}</span>
                  <span className="block text-xs text-[var(--text-secondary)]">{r.reason}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <>
            <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]" htmlFor="move-upload-company">
              Move to
            </label>
            <select
              id="move-upload-company"
              className="mb-4 w-full rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2.5 py-1.5 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
              value={companyId}
              disabled={busy || companies === null}
              onChange={(e) => setCompanyId(e.target.value)}
            >
              {companies === null && <option value="">Loading…</option>}
              {companies?.map((c) => (
                <option key={c.id} value={c.id}>{c.registered_name}</option>
              ))}
            </select>

            <div className="mb-1 flex items-center justify-between text-[11px] font-medium text-[var(--text-secondary)]">
              <span>Files</span>
              {recent.files.length > 1 && (
                <button
                  type="button"
                  className="underline"
                  onClick={() => setPicked(picked.size === recent.files.length ? new Set() : new Set(recent.files.map((f) => f.id)))}
                >
                  {picked.size === recent.files.length ? "None" : "All"}
                </button>
              )}
            </div>
            <ul className="min-h-0 space-y-1 overflow-y-auto">
              {recent.files.map((f) => (
                <li key={f.id}>
                  <label className="flex cursor-pointer items-start gap-2.5 rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--bg-hover)]">
                    <input type="checkbox" className="mt-0.5" checked={picked.has(f.id)} disabled={busy} onChange={() => toggle(f.id)} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[var(--text-primary)]">{f.original_filename}</span>
                      <span className="block truncate text-xs text-[var(--text-secondary)]">
                        {plural(f.documents, "document")} · {f.companies.map((c) => c.registered_name).join(", ")}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </>
        )}

        {error && <p role="alert" className="mt-3 text-sm text-[var(--alert-error-text)]">{error}</p>}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-primary)]"
          >
            {result ? "Done" : "Cancel"}
          </button>
          {!result && (
            <button
              type="button"
              onClick={move}
              disabled={busy || !companyId || moving === 0}
              className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60"
            >
              {busy ? "Moving…" : moving === 0 ? "Already there" : `Move ${plural(moving, "document")}`}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
