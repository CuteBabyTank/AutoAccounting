"use client";

import { useEffect, useState } from "react";
import { DownloadSimple, FilePdf, FileZip } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { useCanFile } from "@/lib/use-can-file";
import { CHANGED_STYLE, apiErrorMessage, formatAmount, saveBlob } from "@/lib/accounting-format";
import PdfPreview, { PreviewButton, useFilePreview, type PreviewEdits } from "@/components/accounting/PdfPreview";
import type { Certificate, Output, OutputForm, PdfField } from "@/types/accounting";

const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";
const WHOLE = new Set(["1701Q", "1702Q", "1702RT", "1701", "1701A"]);

const FIGURE = /^-?\d+(\.\d+)?$/;

/** A return's items as preview fields (figures edit as amounts, anything else as text). */
function formFields(form: OutputForm): PdfField[] {
  return form.items.map((i) => ({ key: i.key, label: i.label.startsWith(i.key) ? i.label : `${i.key} · ${i.label}`, value: i.value, kind: FIGURE.test(i.value) ? "amount" : "text" }));
}

interface Props {
  outputId: string;
  /** False for an older version: it previews but can't be edited (edits go on the latest). */
  latest?: boolean;
  /** Hand edits were saved as a new version. */
  onNewVersion?: (output: Output) => void;
}

export default function OutputViewer({ outputId, latest: isLatest = true, onNewVersion }: Props) {
  // Hand edits are gated like filing (approve-before-close: managers only); the API enforces it too.
  const canFile = useCanFile();
  const latest = isLatest && canFile;
  const [output, setOutput] = useState<Output | null>(null);
  const [tab, setTab] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [previewForm, setPreviewForm] = useState<OutputForm | null>(null);
  const [certificates, setCertificates] = useState<Certificate[] | null>(null);
  const file = useFilePreview();

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
      saveBlob(blob, `${output.label} ${form ?? "workbook"} v${output.version}.${kind}`);
    } catch (e) {
      setError(apiErrorMessage(e, "Download failed"));
    } finally {
      setBusy(null);
    }
  }

  async function downloadAging(kind: "ar" | "ap") {
    if (!output) return;
    setBusy(`aging-${kind}`);
    setError("");
    try {
      saveBlob(await accountingApi.outputAging(output.id, kind), `${output.label} ${kind === "ar" ? "AR" : "AP"} aging v${output.version}.pdf`);
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

  async function open2307s() {
    if (!output) return;
    setBusy("2307s");
    setError("");
    try {
      setCertificates(await accountingApi.certificates2307(output.id));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't load the 2307s"));
    } finally {
      setBusy(null);
    }
  }

  /** Download the form; hand edits are saved as the next version first, and the PDF comes from that version. */
  async function exportForm(form: string, edits: PreviewEdits) {
    if (!output) return;
    const values = edits[form] ?? {};
    let target = output;
    if (Object.keys(values).length > 0) {
      target = await accountingApi.saveFormEdits(output.id, form, values);
      onNewVersion?.(target);
    }
    const blob = await accountingApi.outputFile(target.id, "pdf", { clean: true, form });
    saveBlob(blob, `${target.label} ${form} v${target.version}.pdf`);
  }

  function previewAging(kind: "ar" | "ap") {
    if (!output) return;
    const what = kind === "ar" ? "A/R aging" : "A/P aging";
    file.open(`${output.label} ${what} v${output.version}`, () => accountingApi.outputAging(output.id, kind),
      `${output.label} ${kind === "ar" ? "AR" : "AP"} aging v${output.version}.pdf`);
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
          <button className={BTN} disabled={busy !== null} onClick={() => download("xlsx", false)} title="Changes since the last version are highlighted">
            <DownloadSimple size={16} /> Workbook
          </button>
          {(output.ledgers.ARAging ?? 0) > 0 && (
            <span className="inline-flex gap-1">
              <PreviewButton compact label="Preview A/R aging" disabled={busy !== null} onClick={() => previewAging("ar")} />
              <button className={BTN} disabled={busy !== null} onClick={() => downloadAging("ar")}>
                <FilePdf size={16} /> A/R aging
              </button>
            </span>
          )}
          {(output.ledgers.APAging ?? 0) > 0 && (
            <span className="inline-flex gap-1">
              <PreviewButton compact label="Preview A/P aging" disabled={busy !== null} onClick={() => previewAging("ap")} />
              <button className={BTN} disabled={busy !== null} onClick={() => downloadAging("ap")}>
                <FilePdf size={16} /> A/P aging
              </button>
            </span>
          )}
          {(output.ledgers.QAP ?? 0) > 0 && (
            <span className="inline-flex gap-1">
              <PreviewButton compact label="Preview and edit the 2307s" disabled={busy !== null} onClick={open2307s} />
              <button className={BTN} disabled={busy !== null} onClick={() => download2307s()}>
                <FileZip size={16} /> Outgoing 2307s
              </button>
            </span>
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
                <PreviewButton label={latest ? "Preview & edit" : "Preview"} disabled={busy !== null} onClick={() => setPreviewForm(current)} />
                <button className={BTN} disabled={busy !== null} onClick={() => download("pdf", true, current.form)}>
                  <FilePdf size={16} /> Download PDF
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
                    <td className={`py-1.5 pr-3 ${item.key === current.payable_item ? "font-semibold" : ""}`}>
                      {item.label}
                      {item.engine != null && (
                        <span
                          className="ml-1.5 rounded bg-[var(--badge-blue-bg)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--badge-blue-text)]"
                          title={`Edited by hand. The books give ${item.engine ? formatAmount(item.engine, WHOLE.has(current.form)) : "blank"}.`}
                        >
                          edited
                        </span>
                      )}
                    </td>
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

      {previewForm && (
        <PdfPreview
          title={`${previewForm.form} · ${output.label} v${output.version}`}
          docs={latest ? [{ id: previewForm.form, label: previewForm.title, fields: formFields(previewForm) }] : undefined}
          render={(form, values) =>
            latest ? accountingApi.previewForm(output.id, form || previewForm.form, values)
              : accountingApi.outputFile(output.id, "pdf", { clean: true, form: previewForm.form })}
          note={latest
            ? `Edits are saved as v${output.version + 1}, so filing, amendments and the books use them. Totals aren't recalculated: change them too if needed. Fields edited by hand are highlighted in the preview only.`
            : isLatest ? "Your firm has managers approve filings, so only a manager can edit a return's figures."
              : "This is an older version. Edit the latest version instead."}
          exportLabel={(edited) => (edited ? `Save as v${output.version + 1} & download` : "Download PDF")}
          onExport={(edits) => exportForm(previewForm.form, edits)}
          onClose={() => setPreviewForm(null)}
        />
      )}
      {certificates && (
        <PdfPreview
          title={`Outgoing 2307s · ${output.label} v${output.version}`}
          docs={certificates}
          render={(id, values) => accountingApi.preview2307(output.id, id, values)}
          note="Edits change only the certificates you download now, not the books or the return."
          exportLabel={(edited) => (edited ? "Download edited 2307s (zip)" : "Download 2307s (zip)")}
          onExport={async (edits) =>
            saveBlob(await accountingApi.outgoing2307s(output.id, edits), `${output.label} 2307s v${output.version}.zip`)}
          onClose={() => setCertificates(null)}
        />
      )}
      {file.node}
    </div>
  );
}
