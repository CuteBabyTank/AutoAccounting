// What the person has open right now (for Casper): the company shown on the accounting page, if any.
import { useSyncExternalStore } from "react";

export interface PageCompany {
  id: string;
  name: string;
}

let current: PageCompany | null = null;
const listeners = new Set<() => void>();

/** The accounting page calls this when the open company changes (null when it closes / unmounts). */
export function setPageCompany(next: PageCompany | null): void {
  if (current?.id === next?.id && current?.name === next?.name) return;
  current = next;
  listeners.forEach((l) => l());
}

export function usePageCompany(): PageCompany | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
    () => null,
  );
}

const FIRM_WIDE = /\b(all|every|each|any|across|firm|firm-wide|companies|clients|which (company|client)|whole)\b/i;
const NOT_ABOUT_A_COMPANY = /\b(atc|what is|what's an?|what does|explain|how do i|how does|rate for|bir form)\b/i;
// The person's own to-do list spans every client.
const MY_WORK = /\b(what (do|should) i (need to )?do|my (tasks?|work|day|plate|to-?do( list)?)|on my plate|to-?do list)\b/i;
const THIS_ONE = /\b(this|that|the current|current) (company|client)\b|\bhere\b/i;

/** Words of a company name worth matching ("Bayanihan Hardware Trading Corp." → bayanihan, hardware, trading). */
function nameWords(name: string): string[] {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9ñ ]+/g, " ")
    .split(/\s+/)
    .filter((w) => w.length >= 4 && !["corp", "corporation", "incorporated", "company", "trading", "enterprises", "services"].includes(w));
}

/**
 * Should Casper first ask "Is this about <company>?": "ask", "yes" (they said "this company"), or "skip" (it names
 * the company already, is about the whole firm, or is a general BIR question).
 */
export function companyQuestion(question: string, company: PageCompany): "ask" | "yes" | "skip" {
  const q = question.toLowerCase();
  if (THIS_ONE.test(question)) return "yes";
  if (nameWords(company.name).some((w) => q.includes(w))) return "yes";
  if (FIRM_WIDE.test(question) || NOT_ABOUT_A_COMPANY.test(question) || MY_WORK.test(question)) return "skip";
  return "ask";
}

/** "Bayanihan Hardware Trading Corp." → "Bayanihan Hardware" for buttons and suggestions. */
export function shortName(name: string): string {
  const words = name.replace(/[.,]+$/g, "").split(/\s+/);
  return words.length <= 2 ? name : words.slice(0, 2).join(" ");
}
