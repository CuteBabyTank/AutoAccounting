"use client";

import type { BoardStatus } from "@/types/work";

export const BTN =
  "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";
export const BTN_PRIMARY =
  "inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60";
export const INPUT =
  "rounded-md border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
export const CHIP = "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap";

type Tone = "gray" | "blue" | "yellow" | "green" | "red";
const TONES: Record<Tone, string> = {
  gray: "bg-[var(--bg-hover)] text-[var(--text-secondary)]",
  blue: "bg-[var(--badge-blue-bg)] text-[var(--badge-blue-text)]",
  yellow: "bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]",
  green: "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]",
  red: "bg-[var(--badge-red-bg)] text-[var(--badge-red-text)]",
};

export function Chip({ tone = "gray", children, title }: { tone?: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span title={title} className={`${CHIP} ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export const STATUS_META: Record<BoardStatus, { label: string; tone: Tone }> = {
  no_docs: { label: "No documents", tone: "gray" },
  docs_in: { label: "Documents in", tone: "blue" },
  needs_review: { label: "Needs review", tone: "yellow" },
  generated: { label: "Generated", tone: "blue" },
  filed: { label: "Filed", tone: "green" },
};

export const STATUS_ORDER: BoardStatus[] = ["no_docs", "docs_in", "needs_review", "generated", "filed"];

export function shortDate(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-PH", { day: "numeric", month: "short", year: "numeric" });
}

/** Completion timestamps use the firm's Philippine calendar; board-only dates have no invented time. */
export function completionWhen(iso: string, dateOnly = false): string {
  if (iso.length <= 10) return shortDate(iso);
  if (dateOnly) return new Date(iso).toLocaleDateString("en-PH", { timeZone: "Asia/Manila", dateStyle: "medium" });
  return new Date(iso).toLocaleString("en-PH", {
    timeZone: "Asia/Manila", dateStyle: "medium", timeStyle: "short",
  });
}

export function monthLabel(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-PH", { month: "short", year: "numeric" });
}

export function dueText(daysLeft: number): string {
  if (daysLeft === 0) return "due today";
  if (daysLeft > 0) return `in ${daysLeft} day${daysLeft === 1 ? "" : "s"}`;
  const late = -daysLeft;
  return `${late} day${late === 1 ? "" : "s"} late`;
}

export function reasonName(reason: string): string {
  const text = reason.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function todayIso(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
