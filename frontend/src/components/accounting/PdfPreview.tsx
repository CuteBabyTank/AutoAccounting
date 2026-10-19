"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowCounterClockwise, ArrowSquareOut, DownloadSimple, Eye, X } from "@phosphor-icons/react";
import { apiErrorMessage, saveBlob } from "@/lib/accounting-format";
import type { PdfField } from "@/types/accounting";

/** One document in the preview (a return, or one certificate of a set) and the fields people may change on it. */
export interface PreviewDoc {
  id: string;
  label: string;
  fields: PdfField[];
}

export type PreviewEdits = Record<string, Record<string, string>>;

interface Props {
  title: string;
  /** Editable documents. Leave out for a read-only file (reports, books, statements). */
  docs?: PreviewDoc[];
  /** The PDF for one document with its pending edits. */
  render: (docId: string, edits: Record<string, string>) => Promise<Blob>;
  /** Download (and for returns, save) with every document's pending edits. */
  onExport: (edits: PreviewEdits, current: Blob | null) => Promise<void>;
  exportLabel?: (edited: boolean) => string;
  /** One line under the title (what an edit does here). */
  note?: string;
  onClose: () => void;
}

const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";
const PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60";
const INPUT = "w-full rounded-md border bg-[var(--bg-primary)] px-2 py-1 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const REFRESH_MS = 700;

/** Preview a PDF before it's exported; for forms, edit their fields beside it (the preview follows the edits). */
export default function PdfPreview({ title, docs, render, onExport, exportLabel, note, onClose }: Props) {
  const editable = !!docs && docs.length > 0;
  const [docId, setDocId] = useState(docs?.[0]?.id ?? "");
  const [edits, setEdits] = useState<PreviewEdits>({});
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const blob = useRef<Blob | null>(null);
  const request = useRef(0);
  const shown = useRef<string | null>(null);
  // Callers pass inline functions; keep the latest without re-rendering the preview on every parent render.
  const renderRef = useRef(render);
  useEffect(() => {
    renderRef.current = render;
  }, [render]);

  const doc = docs?.find((d) => d.id === docId) ?? null;
  const pending = edits[docId] ?? {};
  const editedCount = Object.values(edits).reduce((n, e) => n + Object.keys(e).length, 0);

  const load = useCallback(async (id: string, values: Record<string, string>) => {
    const mine = ++request.current;
    setLoading(true);
    setError("");
    try {
      const next = await renderRef.current(id, values);
      if (mine !== request.current) return;
      blob.current = next;
      if (shown.current) URL.revokeObjectURL(shown.current);
      shown.current = URL.createObjectURL(next);
      setUrl(shown.current);
    } catch (e) {
      if (mine === request.current) setError(apiErrorMessage(e, "Couldn't build the preview"));
    } finally {
      if (mine === request.current) setLoading(false);
    }
  }, []);

  // Re-render shortly after typing stops, and straight away when switching documents.
  const pendingKey = JSON.stringify(pending);
  const lastDoc = useRef<string | null>(null);
  useEffect(() => {
    const switched = lastDoc.current !== docId;
    lastDoc.current = docId;
    const values = JSON.parse(pendingKey) as Record<string, string>;
    const timer = setTimeout(() => load(docId, values), switched ? 0 : REFRESH_MS);
    return () => clearTimeout(timer);
  }, [docId, pendingKey, load]);

  useEffect(
    () => () => {
      request.current += 1;
      if (shown.current) URL.revokeObjectURL(shown.current);
    },
    [],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  function setField(field: PdfField, value: string) {
    setEdits((all) => {
      const mine = { ...(all[docId] ?? {}) };
      if (value === field.value) delete mine[field.key];
      else mine[field.key] = value;
      const next = { ...all, [docId]: mine };
      if (Object.keys(mine).length === 0) delete next[docId];
      return next;
    });
  }

  async function exportNow() {
    setBusy(true);
    setError("");
    try {
      await onExport(edits, editedCount === 0 ? blob.current : null);
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't export"));
    } finally {
      setBusy(false);
    }
  }

  const docsEdited = useMemo(() => new Set(Object.keys(edits)), [edits]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-2 sm:p-4" onClick={() => !busy && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="pdf-preview-title"
        onClick={(e) => e.stopPropagation()}
        className="flex h-[94vh] w-full max-w-6xl flex-col rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4"
      >
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 id="pdf-preview-title" className="min-w-0 truncate text-lg font-semibold text-[var(--text-primary)]">{title}</h2>
          <div className="ml-auto flex items-center gap-2">
            {url && (
              <a className={BTN} href={url} target="_blank" rel="noopener noreferrer" title="Open the preview in a new tab">
                <ArrowSquareOut size={16} /> <span className="hidden sm:inline">Open</span>
              </a>
            )}
            <button className={PRIMARY} disabled={busy || !url} onClick={exportNow}>
              <DownloadSimple size={16} /> {exportLabel ? exportLabel(editedCount > 0) : "Download PDF"}
            </button>
            <button onClick={onClose} disabled={busy} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Close">
              <X size={18} />
            </button>
          </div>
        </div>
        {note && <p className="mb-2 text-xs text-[var(--text-secondary)]">{note}</p>}
        {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}

        <div className="flex min-h-0 flex-1 flex-col gap-3 md:flex-row">
          <div className="relative min-h-[45vh] flex-1 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]">
            {url && <iframe title={`${title} preview`} src={`${url}#view=FitH`} className="h-full w-full" />}
            {loading && (
              <div className="absolute right-2 top-2 rounded-md bg-[var(--bg-secondary)] px-2 py-1 text-xs text-[var(--text-secondary)] shadow">
                {url ? "Updating preview…" : "Building preview…"}
              </div>
            )}
          </div>

          {editable && (
            <div className="flex min-h-0 w-full flex-col md:w-80">
              {docs!.length > 1 && (
                <select
                  className={`${INPUT} mb-2 border-[var(--border)]`}
                  value={docId}
                  onChange={(e) => setDocId(e.target.value)}
                  aria-label="Certificate"
                >
                  {docs!.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.label}{docsEdited.has(d.id) ? " (edited)" : ""}
                    </option>
                  ))}
                </select>
              )}
              <div className="mb-1 flex items-center gap-2 text-xs text-[var(--text-secondary)]">
                <span>{editedCount === 0 ? "Change a field to update the preview." : `${editedCount} field${editedCount === 1 ? "" : "s"} edited`}</span>
                {pending && Object.keys(pending).length > 0 && (
                  <button
                    className="ml-auto inline-flex items-center gap-1 underline"
                    onClick={() => setEdits((all) => { const next = { ...all }; delete next[docId]; return next; })}
                  >
                    <ArrowCounterClockwise size={12} /> Reset
                  </button>
                )}
              </div>
              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
                {doc?.fields.map((f) => {
                  const value = pending[f.key] ?? f.value;
                  const changed = f.key in pending;
                  return (
                    <label key={f.key} className="block">
                      <span className="mb-0.5 block text-xs text-[var(--text-secondary)]">{f.label}</span>
                      <input
                        className={`${INPUT} ${f.kind === "amount" ? "text-right tabular-nums" : ""} ${changed ? "border-[var(--accent)] bg-[var(--accent-subtle)]" : "border-[var(--border)]"}`}
                        inputMode={f.kind === "amount" ? "decimal" : undefined}
                        value={value}
                        onChange={(e) => setField(f, e.target.value)}
                      />
                      {changed && (
                        <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">Was {f.value || "blank"}</span>
                      )}
                    </label>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** The "Preview" button that sits next to a download. ``compact`` shows just the eye (for crowded toolbars). */
export function PreviewButton({ onClick, disabled, compact, label = "Preview" }: {
  onClick: () => void;
  disabled?: boolean;
  compact?: boolean;
  label?: string;
}) {
  return (
    <button className={BTN} disabled={disabled} onClick={onClick} title={label} aria-label={label}>
      <Eye size={16} />
      {!compact && label}
    </button>
  );
}

/** Preview of a file that can't be edited here (reports, books, statements): ``open`` it, render ``node``. */
export function useFilePreview() {
  const [file, setFile] = useState<{ title: string; load: () => Promise<Blob>; name: string } | null>(null);
  const open = useCallback((title: string, load: () => Promise<Blob>, name: string) => setFile({ title, load, name }), []);
  const node = file && (
    <PdfPreview
      title={file.title}
      render={() => file.load()}
      onExport={async (_, current) => saveBlob(current ?? (await file.load()), file.name)}
      onClose={() => setFile(null)}
    />
  );
  return { open, node };
}
