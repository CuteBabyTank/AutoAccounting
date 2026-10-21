"use client";

import { useLayoutEffect, useRef, type InputHTMLAttributes } from "react";

/** "-118004.32" → "-118,004.32". Anything that isn't a plain number (a typo, "Not provided") is shown as is,
 *  and part-typed numbers keep their shape ("1000." → "1,000."). */
export function groupDigits(raw: string): string {
  const m = /^(-?)(\d+)(\.\d*)?$/.exec(raw);
  if (!m) return raw;
  return m[1] + m[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (m[3] ?? "");
}

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type" | "inputMode"> & {
  /** The amount without separators ("118004.32"), as the rest of the app keeps it. */
  value: string;
  /** Called with what was typed, commas removed. */
  onValueChange: (raw: string) => void;
};

/** A text input for pesos that shows thousands separators as you type (and on paste) while the value it hands
 *  back stays plain, so saving and comparing are unchanged. The caret stays after the same digit. */
export default function AmountInput({ value, onValueChange, ...rest }: Props) {
  const ref = useRef<HTMLInputElement>(null);
  // Characters (not counting commas) before the caret at the last keystroke; restored after re-formatting.
  const caret = useRef<number | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    const n = caret.current;
    if (!el || n === null || document.activeElement !== el) return;
    caret.current = null;
    let pos = 0;
    for (let seen = 0; pos < el.value.length && seen < n; pos++) if (el.value[pos] !== ",") seen++;
    el.setSelectionRange(pos, pos);
  });  // every render: a keystroke that leaves the value unchanged (deleting a comma) re-renders too

  return (
    <input
      {...rest}
      ref={ref}
      type="text"
      inputMode="decimal"
      value={groupDigits(value)}
      onChange={(e) => {
        const typed = e.target.value;
        const at = e.target.selectionStart ?? typed.length;
        caret.current = typed.slice(0, at).replace(/,/g, "").length;
        onValueChange(typed.replace(/,/g, ""));
      }}
    />
  );
}
