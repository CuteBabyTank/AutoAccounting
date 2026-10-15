"use client";

import { useEffect, useState } from "react";
import { Copy } from "@phosphor-icons/react";
import DuplicateCompare from "@/components/accounting/DuplicateCompare";
import { accountingApi } from "@/lib/accounting-api";
import type { DuplicatePair, Folder } from "@/types/accounting";

interface Props {
  folder: Folder;
  onResolved: () => void;
}

/** The double-check over an open folder: possible duplicates (from any upload or quarter) to compare before filing. */
export default function DuplicateBanner({ folder, onResolved }: Props) {
  const [pairs, setPairs] = useState<DuplicatePair[]>([]);
  const [comparing, setComparing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    accountingApi
      .duplicates(folder.company.id, { year: folder.year, quarter: folder.quarter })
      .then((rows) => !cancelled && setPairs(rows))
      .catch(() => !cancelled && setPairs([]));
    return () => {
      cancelled = true;
    };
  }, [folder]);

  // The compare dialog keeps its own list, so it stays open while the folder reloads underneath it.
  if (!pairs.length && !comparing) return null;

  return (
    <>
      {pairs.length > 0 && <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] px-4 py-2.5 text-sm text-[var(--alert-warning-text)]">
        <Copy size={18} weight="duotone" />
        <span>
          {pairs.length === 1 ? "1 document looks like" : `${pairs.length} documents look like`} a copy of one already filed.
          Compare them before you generate, so nothing is counted twice.
        </span>
        <button className="ml-auto font-semibold underline" onClick={() => setComparing(true)}>
          Compare side by side
        </button>
      </div>}
      {comparing && (
        <DuplicateCompare pairs={pairs} onClose={() => setComparing(false)} onResolved={() => onResolved()} />
      )}
    </>
  );
}
