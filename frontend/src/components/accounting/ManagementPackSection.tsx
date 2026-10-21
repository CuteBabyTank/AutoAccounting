"use client";

import { useEffect, useState } from "react";
import { DownloadSimple } from "@phosphor-icons/react";
import Hint from "@/components/guide/Hint";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, saveBlob } from "@/lib/accounting-format";
import { useFilePreview } from "@/components/accounting/PdfPreview";
import { fiscalQuarter } from "@/lib/report-periods";
import { BTN, BTN_PRIMARY, INPUT } from "@/components/work/ui";
import type { ManagementPack } from "@/types/accounting";

interface Props {
  companyId: string;
  companyName: string;
  fiscalYearEndMonth: number;
}

/** Management report pack per quarter: notes, Generate (PDF + DOCX saved with the quarter's outputs), downloads. */
export default function ManagementPackSection({ companyId, companyName, fiscalYearEndMonth }: Props) {
  const now = fiscalQuarter(new Date(), fiscalYearEndMonth);
  const [year, setYear] = useState(now.year);
  const [quarter, setQuarter] = useState(now.quarter);
  const [pack, setPack] = useState<ManagementPack | null>(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const file = useFilePreview();

  useEffect(() => {
    let cancelled = false;
    setError("");
    setSaved("");
    accountingApi
      .pack(companyId, year, quarter)
      .then((p) => {
        if (cancelled) return;
        setPack(p);
        setNotes(p.notes);
      })
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the pack")));
    return () => {
      cancelled = true;
    };
  }, [companyId, year, quarter]);

  async function run(action: () => Promise<ManagementPack>, done: string) {
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const p = await action();
      setPack(p);
      setNotes(p.notes);
      setSaved(done);
    } catch (e) {
      setError(apiErrorMessage(e, "That didn't work"));
    } finally {
      setBusy(false);
    }
  }

  const download = async (format: "pdf" | "docx") => {
    try {
      const blob = await accountingApi.packFile(companyId, year, quarter, format);
      saveBlob(blob, `${companyName} ${year} Q${quarter} management report.${format}`);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't download the pack"));
    }
  };

  const dirty = pack !== null && notes.trim() !== pack.notes;
  return (
    <section className="mt-8">
      <h3 className="mb-2 flex items-center gap-1 text-sm font-semibold text-[var(--text-primary)]">
        Management report pack
        <Hint>
          A quarter&apos;s pack for the client: cover, contents, P&amp;L (quarter and year to date), balance sheet against
          the previous quarter, cash flow, A/R and A/P aging, key ratios and your notes. Generate saves a PDF and a Word
          file next to the quarter&apos;s returns; generate again after the books change.
        </Hint>
      </h3>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-[var(--text-secondary)]">
          Fiscal year
          <input type="number" className={`${INPUT} ml-1 w-24`} value={year} min={2000} max={2100}
            onChange={(e) => setYear(Number(e.target.value) || now.year)} />
        </label>
        <select className={INPUT} value={quarter} onChange={(e) => setQuarter(Number(e.target.value))} aria-label="Quarter">
          {[1, 2, 3, 4].map((q) => <option key={q} value={q}>Q{q}</option>)}
        </select>
        {pack && <span className="text-xs text-[var(--text-secondary)]">{pack.period}</span>}
      </div>
      <textarea
        className={`${INPUT} mt-2 h-28 w-full`}
        maxLength={20000}
        placeholder="Notes for the client (printed as the last section): what changed, what to send, what to watch."
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button className={BTN} disabled={busy || !dirty}
          onClick={() => run(() => accountingApi.savePackNotes(companyId, year, quarter, notes), "Notes saved")}>
          Save notes
        </button>
        <button className={BTN_PRIMARY} disabled={busy || !pack?.books_on}
          onClick={() => run(async () => {
            if (dirty) await accountingApi.savePackNotes(companyId, year, quarter, notes);
            return accountingApi.generatePack(companyId, year, quarter);
          }, "Pack generated")}>
          {busy ? "Working…" : "Generate pack"}
        </button>
        {pack?.pdf && (
          <button className={BTN} onClick={() =>
            file.open(`Management pack · ${year} Q${quarter}`, () => accountingApi.packFile(companyId, year, quarter, "pdf"),
              `${companyName} ${year} Q${quarter} management report.pdf`)}>
            <DownloadSimple size={14} /> PDF
          </button>
        )}
        {file.node}
        {pack?.docx && <button className={BTN} onClick={() => download("docx")}><DownloadSimple size={14} /> Word</button>}
        {pack?.generated_at && (
          <span className="text-xs text-[var(--text-secondary)]">
            Generated {new Date(pack.generated_at).toLocaleString("en-PH")}{pack.generated_by && ` by ${pack.generated_by}`}
          </span>
        )}
        {saved && <span className="text-xs text-[var(--badge-green-text)]">{saved}</span>}
      </div>
      {error && <p className="mt-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
    </section>
  );
}
