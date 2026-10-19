"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { DownloadSimple, X } from "@phosphor-icons/react";
import { apiErrorMessage, saveBlob } from "@/lib/accounting-format";
import type { WorkbookSheet } from "@/types/accounting";

const PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60";

interface Props {
  title: string;
  load: () => Promise<WorkbookSheet[]>;
  onDownload: () => Promise<void>;
  /** One line under the title. */
  note?: string;
  onClose: () => void;
}

/** A workbook shown in the app (one tab per sheet, highlighted cells kept) with the download inside. */
export default function WorkbookPreview({ title, load, onDownload, note, onClose }: Props) {
  const [sheets, setSheets] = useState<WorkbookSheet[] | null>(null);
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    load()
      .then((s) => !cancelled && setSheets(s))
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't open the workbook")));
    return () => {
      cancelled = true;
    };
    // load once per open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  async function download() {
    setBusy(true);
    setError("");
    try {
      await onDownload();
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, "Download failed"));
    } finally {
      setBusy(false);
    }
  }

  const sheet = sheets?.[active] ?? null;
  const width = sheet ? Math.max(0, ...sheet.rows.map((r) => r.length)) : 0;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-2 sm:p-4" onClick={() => !busy && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="workbook-preview-title"
        onClick={(e) => e.stopPropagation()}
        className="flex h-[94vh] w-full max-w-6xl flex-col rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4"
      >
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 id="workbook-preview-title" className="min-w-0 truncate text-lg font-semibold text-[var(--text-primary)]">{title}</h2>
          <div className="ml-auto flex items-center gap-2">
            <button className={PRIMARY} disabled={busy || !sheets} onClick={download}>
              <DownloadSimple size={16} /> Download workbook
            </button>
            <button onClick={onClose} disabled={busy} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Close">
              <X size={18} />
            </button>
          </div>
        </div>
        {note && <p className="mb-2 text-xs text-[var(--text-secondary)]">{note}</p>}
        {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}

        {sheets && (
          <div className="mb-2 flex gap-1 overflow-x-auto pb-1" role="tablist" aria-label="Sheets">
            {sheets.map((s, i) => (
              <button
                key={s.name}
                role="tab"
                aria-selected={i === active}
                onClick={() => setActive(i)}
                className={`shrink-0 rounded-md px-2.5 py-1 text-xs font-medium ${i === active ? "bg-[var(--accent-subtle)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}
              >
                {s.name}
                {s.rows.some((r) => r.some((c) => c.fill)) && (
                  <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full align-middle" style={{ backgroundColor: "#E5C200" }} />
                )}
              </button>
            ))}
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]">
          {!sheets && !error && <p className="p-4 text-sm text-[var(--text-secondary)]">Opening the workbook…</p>}
          {sheet && (
            sheet.rows.length === 0 ? (
              <p className="p-4 text-sm text-[var(--text-secondary)]">This sheet is empty.</p>
            ) : (
              <table className="border-collapse text-xs">
                <tbody>
                  {sheet.rows.map((row, r) => (
                    <tr key={r}>
                      <td className="sticky left-0 border border-[var(--border)] bg-[var(--bg-secondary)] px-1.5 py-1 text-right text-[10px] text-[var(--text-secondary)] tabular-nums">{r + 1}</td>
                      {Array.from({ length: width }, (_, c) => {
                        const cell = row[c];
                        return (
                          <td
                            key={c}
                            className={`max-w-[28rem] whitespace-nowrap border border-[var(--border)] px-2 py-1 text-[var(--text-primary)] ${cell?.num ? "text-right tabular-nums" : ""} ${cell?.bold ? "font-semibold" : ""} ${cell?.strike ? "line-through" : ""}`}
                            style={cell?.fill ? { backgroundColor: cell.fill, color: "#1F1F1F" } : undefined}
                            title={cell && cell.v.length > 60 ? cell.v : undefined}
                          >
                            <span className="block overflow-hidden text-ellipsis">{cell?.v ?? ""}</span>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          )}
        </div>
        {sheet?.truncated && (
          <p className="mt-2 text-xs text-[var(--text-secondary)]">Only the first rows and columns of this sheet are shown. Download the workbook to see all of it.</p>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** An Excel export that opens in the preview first (download inside): ``open`` it, render ``node``. */
export function useWorkbookPreview() {
  const [file, setFile] = useState<{
    title: string; load: () => Promise<WorkbookSheet[]>; download: () => Promise<Blob>; name: string;
  } | null>(null);
  const open = useCallback(
    (title: string, load: () => Promise<WorkbookSheet[]>, download: () => Promise<Blob>, name: string) =>
      setFile({ title, load, download, name }),
    [],
  );
  const node = file && (
    <WorkbookPreview
      title={file.title}
      load={file.load}
      onDownload={async () => saveBlob(await file.download(), file.name)}
      onClose={() => setFile(null)}
    />
  );
  return { open, node };
}
