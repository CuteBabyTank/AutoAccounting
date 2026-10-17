// Report period presets (calendar months, fiscal quarters and fiscal years for any fiscal year end).

export type PresetKey = "this_month" | "last_month" | "this_quarter" | "last_quarter" | "this_year" | "last_year" | "custom";

export const PRESETS: { key: PresetKey; label: string }[] = [
  { key: "this_month", label: "This month" },
  { key: "last_month", label: "Last month" },
  { key: "this_quarter", label: "This quarter" },
  { key: "last_quarter", label: "Last quarter" },
  { key: "this_year", label: "This fiscal year" },
  { key: "last_year", label: "Last fiscal year" },
  { key: "custom", label: "Custom" },
];

const pad = (n: number) => String(n).padStart(2, "0");

/** [year, month 1–12] moved by n months. */
function shift(year: number, month: number, n: number): [number, number] {
  const k = year * 12 + (month - 1) + n;
  return [Math.floor(k / 12), (k % 12) + 1];
}

function first(year: number, month: number): string {
  return `${year}-${pad(month)}-01`;
}

function last(year: number, month: number): string {
  return `${year}-${pad(month)}-${pad(new Date(year, month, 0).getDate())}`;
}

/** Start and end (ISO dates) of a preset as of ``today``; fiscal quarters and years follow the fiscal year end month. */
export function presetRange(key: Exclude<PresetKey, "custom">, today: Date, fye: number): { start: string; end: string } {
  const y = today.getFullYear();
  const m = today.getMonth() + 1;
  const into = (m - ((fye % 12) + 1) + 12) % 12; // months since the fiscal year began
  let s: [number, number];
  let months: number;
  if (key === "this_month" || key === "last_month") {
    s = shift(y, m, key === "last_month" ? -1 : 0);
    months = 1;
  } else if (key === "this_quarter" || key === "last_quarter") {
    s = shift(y, m, -(into % 3) - (key === "last_quarter" ? 3 : 0));
    months = 3;
  } else {
    s = shift(y, m, -into - (key === "last_year" ? 12 : 0));
    months = 12;
  }
  const e = shift(s[0], s[1], months - 1);
  return { start: first(s[0], s[1]), end: last(e[0], e[1]) };
}

/** The fiscal year (the calendar year it ends in) and quarter 1–4 a date falls in. */
export function fiscalQuarter(today: Date, fye: number): { year: number; quarter: number } {
  const y = today.getFullYear();
  const m = today.getMonth() + 1;
  const into = (m - ((fye % 12) + 1) + 12) % 12;
  const end = shift(y, m, 11 - into);
  return { year: end[0], quarter: Math.floor(into / 3) + 1 };
}
