"use client";

import { Crosshair } from "@phosphor-icons/react";

/** Next to a field's label, only when its value can be outlined on the page shown (field boxes): focuses the field,
 *  which outlines it and (with "Zoom to field" on) zooms to it. */
export default function ShowOnScan({ onShow }: { onShow: () => void }) {
  return (
    <button
      type="button"
      title="Show on scan"
      aria-label="Show on scan"
      onClick={(e) => {
        e.preventDefault();
        onShow();
      }}
      className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded text-[var(--text-tertiary)] align-middle hover:text-[var(--accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
    >
      <Crosshair size={12} weight="bold" aria-hidden />
    </button>
  );
}
