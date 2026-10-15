"use client";

import { useEffect, useState } from "react";
import { DownloadSimple, FilePdf, FileZip } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { CHANGED_STYLE, apiErrorMessage, formatAmount, saveBlob } from "@/lib/accounting-format";
import type { Output } from "@/types/accounting";

const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";
const WHOLE = new Set(["1701Q", "1702Q", "1702RT", "1701", "1701A"]);

export default function OutputViewer({ outputId }: { outputId: string }) {
  const [output, setOutput] = useState<Output | null>(null);
  const [tab, setTab] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setOutput(null);
    setError("");
    accountingApi
      .output(outputId)
      .then((o) => {
        if (cancelled) return;
        setOutput(o);
        setTab(o.forms[0]?.form ?? null);
      })
      .catch((e) => {
        if (!cancelled) setError(apiErrorMessage(e, "Couldn't load this version"));
      });
    return () => {
      cancelled = true;
    };
  }, [outputId]);

  async function download(kind: "xlsx" | "pdf", clean: boolean, form?: string) {
    if (!output) return;
    const id = `${kind}-${clean}-${form ?? ""}`;
    setBusy(id);
    setError("");
    try {
      const blob = await accountingApi.outputFile(output.id, kind, { clean, form });
      const what = form ?? "workbook";
      saveBlob(blob, `${output.label} ${what} v${output.version}${clean ? " clean" : ""}.${kind}`);
    } catch (e) {
      setError(apiErrorMessage(e, "Download failed"));
    } finally {
      setBusy(null);
    }
  }

  async function download2307s() {
    if (!output) return;
    setBusy("2307s");
    setError("");
    try {
      saveBlob(await accountingApi.outgoing2307s(output.id), `${output.label} 2307s v${output.version}.zip`);
    } catch (e) {
      setError(apiErrorMessage(e, "Download failed"));
    } finally {
      setBusy(null);
    }
  }

  if (error && !output) return <p className="text-sm text-[var(--alert-error-text)]">{error}</p>;
  if (!output) return <div className="h-24 animate-pulse rounded-lg bg-[var(--bg-primary)]" />;
  const current = output.forms.find((f) => f.form === tab) ?? null;

  return (
    <div className="rounded-lg border border-[var(--border)] p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-[var(--text-primary)]">v{output.version}</span>
        {output.parent_version && (
          <span className="rounded px-1.5 text-xs" style={output.changes ? CHANGED_STYLE : undefined}>
            {output.changes} change{output.changes === 1 ? "" : "s"} since v{output.parent_version}
          </span>
        )}
        {output.review_open > 0 && (
          <span className="rounded-full bg-[var(--badge-yellow-bg)] px-2 py-0.5 text-xs font-medium text-[var(--badge-yellow-text)]">DRAFT</span>
        )}
        {output.amended && (
          <span className="rounded-full bg-[var(--badge-blue-bg)] px-2 py-0.5 text-xs font-medium text-[var(--badge-blue-text)]">Amended</span>
        )}
        <div className="ml-auto flex flex-wrap gap-2">
          <button className={BTN} disabled={busy !== null} onClick={() => download("xlsx", false)}>
            <DownloadSimple size={16} /> Workbook
          </button>
          <button className={BTN} disabled={busy !== null} onClick={() => download("xlsx", true)}>
            Clean copy
          </button>
          {(output.ledgers.QAP ?? 0) > 0 && (
            <button className={BTN} disabled={busy !== null} onClick={download2307s}>
              <FileZip size={16} /> Outgoing 2307s
            </button>
          )}
        </div>
      </div>

      {output.warnings.length > 0 && (
        <ul className="mb-3 space-y-1 rounded-lg border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] p-3 text-sm text-[var(--alert-warning-text)]">
          {output.warnings.map((w) => (
            <li key={w}>• {w}</li>
          ))}
        </ul>
      )}

      <div className="mb-2 flex flex-wrap gap-1.5">
        {output.forms.map((f) => (
          <button
            key={f.form}
            onClick={() => setTab(f.form)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium ${f.form === tab ? "bg-[var(--accent-subtle)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}
          >
            {f.form}
            {f.items.some((i) => i.changed) && <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full" style={{ backgroundColor: "#E5C200" }} />}
          </button>
        ))}
      </div>

      {current && (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-[var(--text-primary)]">{current.title}</p>
            {current.pdf && (
              <div className="ml-auto flex gap-2">
                <button className={BTN} disabled={busy !== null} onClick={() => download("pdf", false, current.form)}>
                  <FilePdf size={16} /> Generate PDF
                </button>
                <button className={BTN} disabled={busy !== null} onClick={() => download("pdf", true, current.form)}>
                  Clean PDF
                </button>
              </div>
            )}
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full text-sm">
              <tbody>
                {current.items.map((item) => (
                  <tr
                    key={item.key}
                    className="border-t border-[var(--border)] text-[var(--text-primary)]"
                    style={item.changed ? CHANGED_STYLE : undefined}
                    title={item.changed ? `Was ${item.before ? formatAmount(item.before, WHOLE.has(current.form)) : "blank"}` : undefined}
                  >
                    <td className={`py-1.5 pr-3 ${item.key === current.payable_item ? "font-semibold" : ""}`}>{item.label}</td>
                    <td className={`py-1.5 text-right tabular-nums ${item.key === current.payable_item ? "font-semibold" : ""}`}>
                      {item.key.endsWith("_YEAR") ? item.value : formatAmount(item.value, WHOLE.has(current.form))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="mt-3 text-xs text-[var(--text-secondary)]">
        In the workbook:{" "}
        {Object.entries(output.ledgers)
          .map(([name, n]) => `${name} (${n} row${n === 1 ? "" : "s"})`)
          .join(" · ")}
      </p>
      {error && <p className="mt-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
    </div>
  );
}
