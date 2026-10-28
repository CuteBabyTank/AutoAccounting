"use client";

import { FILING_LOCKED_TITLE, useCanFile } from "@/lib/use-can-file";
import { useEffect, useState } from "react";
import { CheckCircle, FilePdf, Warning } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, saveBlob } from "@/lib/accounting-format";
import PdfPreview from "@/components/accounting/PdfPreview";
import type { Output, Period, PdfField, Prepare, Scope } from "@/types/accounting";

const FIGURE = /^-?\d+(\.\d+)?$/;

const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";
const SCOPES: Scope[] = ["M1", "M2", "M3", "Q"];
const INPUT = "rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";

/** Today in Manila as YYYY-MM-DD (the BIR's calendar, whatever the browser's time zone). */
function manilaToday(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Manila" });
}

function shortDate(iso: string): string {
  const day = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T00:00:00`) : new Date(iso);
  return day.toLocaleDateString("en-PH", { month: "short", day: "numeric" });
}

interface Props {
  outputId: string;
  companyId: string;
  year: number;
  quarter: number;
  onPeriod: (p: Period) => void;
  onEditCompany?: () => void;
  /** Hand edits made in the preview were saved as a new version. */
  onNewVersion?: (output: Output) => void;
}

export default function PrepareReturns({ outputId, companyId, year, quarter, onPeriod, onEditCompany, onNewVersion }: Props) {
  const [scope, setScope] = useState<Scope | null>(null);
  const [prep, setPrep] = useState<Prepare | null>(null);
  const [labels, setLabels] = useState<Partial<Record<Scope, string>>>({});
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<{ form: string; title: string; fields: PdfField[]; output: Output } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [filedOn, setFiledOn] = useState<Record<string, string>>({});
  const canFile = useCanFile();

  // Scope labels ("Month 1: Jan 2026") come from the server so fiscal years are right.
  useEffect(() => {
    let cancelled = false;
    setScope(null);
    setPrep(null);
    Promise.all(SCOPES.map((s) => accountingApi.prepare(outputId, s)))
      .then((all) => {
        if (!cancelled) setLabels(Object.fromEntries(all.map((p) => [p.scope, p.label])));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [outputId]);

  async function load(s: Scope) {
    setScope(s);
    setTicked(new Set());
    setError("");
    try {
      setPrep(await accountingApi.prepare(outputId, s));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't load the returns for this period"));
    }
  }

  async function generate() {
    if (!prep) return;
    setBusy(true);
    setError("");
    try {
      const forms = prep.forms.filter((f) => ticked.has(f.form)).map((f) => f.form);
      const { blob, zip } = await accountingApi.pdfs(outputId, forms, true);
      const what = forms.length === 1 ? forms[0] : "returns";
      saveBlob(blob, `${prep.label} ${what} v${prep.version}.${zip ? "zip" : "pdf"}`);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't generate the PDFs"));
    } finally {
      setBusy(false);
    }
  }

  async function openPreview(form: string, title: string) {
    setBusy(true);
    setError("");
    try {
      const output = await accountingApi.output(outputId);
      const items = output.forms.find((f) => f.form === form)?.items ?? [];
      const fields: PdfField[] = items.map((i) => ({
        key: i.key, label: i.label.startsWith(i.key) ? i.label : `${i.key} · ${i.label}`, value: i.value, kind: FIGURE.test(i.value) ? "amount" : "text",
      }));
      setPreview({ form, title, fields, output });
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't open the preview"));
    } finally {
      setBusy(false);
    }
  }

  async function exportPreview(form: string, values: Record<string, string>) {
    let target = preview!.output;
    if (Object.keys(values).length > 0) {
      target = await accountingApi.saveFormEdits(outputId, form, values);
      onNewVersion?.(target);
    }
    const { blob } = await accountingApi.pdfs(target.id, [form], true);
    saveBlob(blob, `${prep?.label ?? target.label} ${form} v${target.version}.pdf`);
  }

  async function toggleFiled(form: string, filed: boolean) {
    setBusy(true);
    setError("");
    try {
      onPeriod(
        await accountingApi.setFormFiled(
          companyId,
          year,
          quarter,
          form,
          !filed,
          filed ? undefined : outputId,
          filed ? undefined : filedOn[form] || manilaToday(),
        ),
      );
      if (scope) setPrep(await accountingApi.prepare(outputId, scope));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't update the filed status"));
    } finally {
      setBusy(false);
    }
  }

  const missing = prep
    ? Array.from(new Set(prep.forms.filter((f) => ticked.has(f.form)).flatMap((f) => f.missing)))
    : [];

  return (
    <div className="mt-3 rounded-lg border border-[var(--border)] p-3">
      <p className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Prepare returns</p>
      <p className="mb-2 text-xs text-[var(--text-secondary)]">
        The workbook is the source of truth. Pick what you&apos;re filing, tick the forms, then generate their PDFs.
      </p>
      <div className="mb-3 flex flex-wrap gap-2" role="radiogroup" aria-label="What do you want to file?">
        {SCOPES.map((s) => (
          <label key={s} className="flex items-center gap-1.5 text-sm text-[var(--text-primary)]">
            <input type="radio" name={`scope-${outputId}`} checked={scope === s} onChange={() => load(s)} />
            {labels[s] ?? (s === "Q" ? "Quarter" : `Month ${s[1]}`)}
          </label>
        ))}
      </div>

      {prep && scope && (
        <>
          {prep.stale && (
            <p className="mb-2 rounded-md bg-[var(--alert-warning-bg)] px-2 py-1 text-xs text-[var(--alert-warning-text)]">
              {prep.version < prep.latest_version
                ? `This is v${prep.version}; v${prep.latest_version} is newer.`
                : "Documents or inputs changed since this version."}{" "}
              Generate a new version first if the figures should include them.
            </p>
          )}
          {prep.note && <p className="mb-2 text-xs text-[var(--text-secondary)]">{prep.note}</p>}
          <ul className="space-y-2">
            {prep.forms.map((f) => (
              <li key={f.form} className="rounded-md border border-[var(--border)] p-2">
                <div className="flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-2 text-sm font-medium text-[var(--text-primary)]">
                    <input
                      type="checkbox"
                      checked={ticked.has(f.form)}
                      onChange={(e) => {
                        const next = new Set(ticked);
                        if (e.target.checked) next.add(f.form);
                        else next.delete(f.form);
                        setTicked(next);
                      }}
                    />
                    {f.title}
                  </label>
                  {f.due && <span className="text-xs text-[var(--text-secondary)]">Due {new Date(f.due).toLocaleDateString("en-PH", { month: "short", day: "numeric", year: "numeric" })}</span>}
                  {f.amended && <span className="rounded-full bg-[var(--badge-blue-bg)] px-2 py-0.5 text-xs text-[var(--badge-blue-text)]">Amended</span>}
                  <div className="ml-auto flex items-center gap-2">
                    <button className={BTN} disabled={busy} onClick={() => openPreview(f.form, f.title)}>
                      <FilePdf size={16} /> PDF
                    </button>
                    {f.filed && (
                      <span className="flex items-center gap-1 text-xs text-[var(--badge-green-text)]">
                        <CheckCircle size={14} /> Filed {shortDate(f.filed.paid_on ?? f.filed.filed_at)} from v{f.filed.version}
                      </span>
                    )}
                    {!f.filed && (
                      <input
                        type="date"
                        className={INPUT}
                        aria-label={`Date ${f.form} was filed and paid`}
                        title="Date filed and paid. The books post the payment on this day"
                        max={manilaToday()}
                        value={filedOn[f.form] ?? manilaToday()}
                        onChange={(e) => setFiledOn((d) => ({ ...d, [f.form]: e.target.value }))}
                      />
                    )}
                    <button className={BTN} disabled={busy || !canFile} title={canFile ? undefined : FILING_LOCKED_TITLE} onClick={() => toggleFiled(f.form, f.filed !== null)}>
                      {f.filed ? "Unmark" : "Mark filed"}
                    </button>
                  </div>
                </div>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">{f.guide}</p>
                {f.source && <p className="mt-0.5 text-xs text-[var(--text-secondary)]">{f.source}</p>}
              </li>
            ))}
          </ul>

          {missing.length > 0 && (
            <div className="mt-3 flex items-start gap-2 rounded-md border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] p-2 text-xs text-[var(--alert-warning-text)]">
              <Warning size={16} className="mt-0.5 shrink-0" />
              <div>
                Missing: {missing.join(", ")}. The PDFs will be stamped DRAFT.
                {onEditCompany && (
                  <button className="ml-1 underline" onClick={onEditCompany}>Edit company</button>
                )}
              </div>
            </div>
          )}

          <div className="mt-3 flex items-center gap-3">
            <button className={BTN} disabled={busy || ticked.size === 0} onClick={generate}>
              <FilePdf size={16} /> Download PDFs{ticked.size > 0 ? ` (${ticked.size})` : ""}
            </button>
          </div>
        </>
      )}
      {error && <p className="mt-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {preview && (() => {
        const isLatest = !prep || prep.version === prep.latest_version;
        const editable = isLatest && canFile;
        const v = preview.output.version;
        return (
          <PdfPreview
            title={`${preview.form} · ${prep?.label ?? preview.output.label} v${v}`}
            docs={editable ? [{ id: preview.form, label: preview.title, fields: preview.fields }] : undefined}
            render={(_, values) =>
              editable ? accountingApi.previewForm(outputId, preview.form, values)
                : accountingApi.pdfs(outputId, [preview.form], true).then((r) => r.blob)}
            note={editable
              ? `Edits are saved as v${v + 1}, so filing, amendments and the books use them. Totals aren't recalculated: change them too if needed. Fields edited by hand are highlighted in the preview only.`
              : isLatest ? "Your firm has managers approve filings, so only a manager can edit a return's figures."
                : "This is an older version. Edit the latest version instead."}
            exportLabel={(edited) => (edited ? `Save as v${v + 1} & download` : "Download PDF")}
            onExport={(edits) => exportPreview(preview.form, edits[preview.form] ?? {})}
            onClose={() => setPreview(null)}
          />
        );
      })()}
    </div>
  );
}
