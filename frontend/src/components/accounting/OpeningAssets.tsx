"use client";

import { useEffect, useState } from "react";
import AmountInput from "@/components/AmountInput";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatPeso } from "@/lib/accounting-format";
import type { Asset } from "@/types/accounting";

const INPUT = "w-full px-2.5 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const LABEL = "block text-[11px] font-medium text-[var(--text-secondary)] mb-1";
const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";

interface Props {
  companyId: string;
  year: number;
  /** Net property and equipment in the opening balances (PPE less accumulated depreciation). */
  openingPpe: number;
  onChanged: () => void;
}

/** Assets owned before the books start: their net book value then, depreciated over the remaining life. */
export default function OpeningAssets({ companyId, year, openingPpe, onChanged }: Props) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [adding, setAdding] = useState(false);
  const [description, setDescription] = useState("");
  const [cost, setCost] = useState("");
  const [years, setYears] = useState("5");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    accountingApi
      .assets(companyId, year)
      .then((rows) => !cancelled && setAssets(rows.filter((a) => a.document_id === null)))
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the opening assets")));
    return () => {
      cancelled = true;
    };
  }, [companyId, year]);

  const registered = assets.reduce((s, a) => s + Number(a.cost), 0);
  const unregistered = Math.round((openingPpe - registered) * 100) / 100;
  const life = Math.round(Number(years) * 12);
  const valid = description.trim() !== "" && Number(cost.replace(/,/g, "")) > 0 && life >= 1 && life <= 600;

  function startAdding() {
    setAdding(true);
    setDescription("");
    setCost(unregistered > 0 ? unregistered.toFixed(2) : "");
    setYears("5");
  }

  async function add() {
    setBusy(true);
    setError("");
    try {
      const row = await accountingApi.addOpeningAsset(
        companyId, { description: description.trim(), cost: cost.replace(/,/g, ""), useful_life_months: life }, year,
      );
      setAssets((a) => [...a, row]);
      setAdding(false);
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't add the asset"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    setError("");
    try {
      await accountingApi.deleteOpeningAsset(id);
      setAssets((a) => a.filter((x) => x.id !== id));
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't remove the asset"));
    } finally {
      setBusy(false);
    }
  }

  if (openingPpe <= 0 && assets.length === 0) return null;

  return (
    <div className="mt-3 rounded-lg border border-[var(--border)] p-3">
      <div className="mb-1 flex items-center gap-2">
        <h4 className="text-xs font-semibold text-[var(--text-primary)]">Opening assets</h4>
        {!adding && <button className={`${BTN} ml-auto`} onClick={startAdding}>Add asset</button>}
      </div>
      <p className="text-[11px] text-[var(--text-secondary)]">
        Property and equipment owned before the books start, at its net book value then, depreciated over its remaining life.
        {unregistered > 0.005 && (
          <span className="text-[var(--alert-warning-text)]"> {formatPeso(unregistered)} of the opening balances&apos; property and equipment isn&apos;t in the register yet, so it isn&apos;t depreciated.</span>
        )}
      </p>
      {error && <p className="mt-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {assets.length > 0 && (
        <ul className="mt-2 divide-y divide-[var(--border)]">
          {assets.map((a) => (
            <li key={a.id} className="flex flex-wrap items-baseline gap-3 py-1.5 text-sm">
              <span className="flex-1 text-[var(--text-primary)]">{a.description}</span>
              <span className="tabular-nums text-[var(--text-secondary)]">{formatPeso(a.cost)} over {(a.useful_life_months / 12).toFixed(a.useful_life_months % 12 ? 1 : 0)} yrs</span>
              <span className="tabular-nums text-xs text-[var(--text-secondary)]">FY {year}: {formatPeso(a.this_year)}</span>
              <button className="text-[var(--alert-error-text)]" disabled={busy} onClick={() => remove(a.id)}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      {adding && (
        <div className="mt-2 grid gap-3 sm:grid-cols-3">
          <div>
            <label className={LABEL}>Description</label>
            <input className={INPUT} value={description} maxLength={255} placeholder="Store fixtures and equipment" onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div>
            <label className={LABEL}>Net book value at the books&apos; start</label>
            <AmountInput className={INPUT} value={cost} onValueChange={setCost} />
          </div>
          <div>
            <label className={LABEL}>Remaining life (years)</label>
            <input inputMode="decimal" className={INPUT} value={years} onChange={(e) => setYears(e.target.value)} />
          </div>
          <div className="flex gap-2 sm:col-span-3 sm:justify-end">
            <button className={BTN} onClick={() => setAdding(false)}>Cancel</button>
            <button className={BTN} disabled={busy || !valid} onClick={add}>Add to register</button>
          </div>
        </div>
      )}
    </div>
  );
}
