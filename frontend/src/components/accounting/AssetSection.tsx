"use client";

import { useEffect, useState } from "react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatAmount } from "@/lib/accounting-format";
import type { AADocument, Asset } from "@/types/accounting";

const INPUT = "w-full px-2.5 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const LABEL = "block text-[11px] font-medium text-[var(--text-secondary)] mb-1";
const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";

interface Draft {
  description: string;
  in_service: string;
  years: string;
  months: string;
  end_date: string;
}

function toDraft(a: Asset): Draft {
  return {
    description: a.description,
    in_service: a.in_service,
    years: String(Math.floor(a.useful_life_months / 12)),
    months: String(a.useful_life_months % 12),
    end_date: a.end_date ?? "",
  };
}

/** The asset-register row of a capital-goods document: useful life, in-service date, retirement. */
export default function AssetSection({ doc, onChanged }: { doc: AADocument; onChanged: () => void }) {
  const [asset, setAsset] = useState<Asset | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const year = doc.period_year ?? undefined;

  useEffect(() => {
    let cancelled = false;
    setError("");
    accountingApi
      .assets(doc.company_id, year)
      .then((rows) => {
        if (cancelled) return;
        const found = rows.find((a) => a.document_id === doc.id) ?? null;
        setAsset(found);
        setDraft(found ? toDraft(found) : null);
      })
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the asset")));
    return () => {
      cancelled = true;
    };
  }, [doc.company_id, doc.id, doc.doc_date, doc.gross_amount, doc.excluded, year]);

  if (error && !asset) return <p className="mt-4 text-sm text-[var(--alert-error-text)]">{error}</p>;
  if (!asset || !draft) {
    return (
      <p className="mt-4 rounded-lg border border-[var(--border)] p-3 text-xs text-[var(--text-secondary)]">
        Capital goods go to the asset register once the document has a date. Save the date to add it.
      </p>
    );
  }

  const life = Number(draft.years || 0) * 12 + Number(draft.months || 0);
  const lifeValid = Number.isInteger(life) && life >= 1 && life <= 600;

  async function save() {
    if (!asset || !draft) return;
    setBusy(true);
    setError("");
    try {
      const updated = await accountingApi.updateAsset(
        asset.id,
        {
          description: draft.description.trim() || asset.description,
          in_service: draft.in_service,
          useful_life_months: life,
          end_date: draft.end_date || null,
        },
        year,
      );
      setAsset(updated);
      setDraft(toDraft(updated));
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the asset"));
    } finally {
      setBusy(false);
    }
  }

  const set = (key: keyof Draft, value: string) => setDraft((d) => (d ? { ...d, [key]: value } : d));

  return (
    <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
      <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">
        Asset register (depreciated straight-line, not expensed)
      </p>
      {!asset.active && (
        <p className="mb-2 text-xs text-[var(--alert-warning-text)]">
          This document is excluded, deleted or no longer capital goods, so the asset isn&apos;t depreciated.
        </p>
      )}
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className={LABEL}>Description</label>
          <input className={INPUT} value={draft.description} maxLength={255} onChange={(e) => set("description", e.target.value)} />
        </div>
        <div>
          <label className={LABEL}>In service from</label>
          <input type="date" className={INPUT} value={draft.in_service} onChange={(e) => set("in_service", e.target.value)} />
        </div>
        <div>
          <label className={LABEL}>Retired or sold (optional)</label>
          <input type="date" className={INPUT} value={draft.end_date} onChange={(e) => set("end_date", e.target.value)} />
        </div>
        <div>
          <label className={LABEL}>Useful life in years</label>
          <input inputMode="numeric" className={INPUT} value={draft.years} onChange={(e) => set("years", e.target.value.replace(/\D/g, ""))} />
        </div>
        <div>
          <label className={LABEL}>and months</label>
          <input inputMode="numeric" className={INPUT} value={draft.months} onChange={(e) => set("months", e.target.value.replace(/\D/g, ""))} />
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt className="text-[var(--text-secondary)]">Cost</dt>
          <dd className="tabular-nums text-[var(--text-primary)]">₱{formatAmount(asset.cost)}</dd>
        </div>
        <div>
          <dt className="text-[var(--text-secondary)]">Depreciation{year ? ` FY ${year}` : " this year"}</dt>
          <dd className="tabular-nums text-[var(--text-primary)]">₱{formatAmount(asset.this_year)}</dd>
        </div>
        <div>
          <dt className="text-[var(--text-secondary)]">Net book value at year end</dt>
          <dd className="tabular-nums text-[var(--text-primary)]">₱{formatAmount(asset.net_book_value)}</dd>
        </div>
      </dl>
      {!lifeValid && <p className="mt-2 text-xs text-[var(--alert-error-text)]">Useful life must be 1 month to 50 years.</p>}
      {error && <p className="mt-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      <div className="mt-3 flex justify-end">
        <button className={BTN} disabled={busy || !lifeValid || !draft.in_service} onClick={save}>
          Save asset
        </button>
      </div>
    </div>
  );
}
