export interface CasperLine { text: string; question?: string }

/** Greeting first; keep tips aligned with the assistant's real, read-only tools. */
export const CASPER_LINES: CasperLine[] = [
  { text: "Howdy! I'm Casper. Ask me anything about your clients, filings or books." },
  { text: "Try: What's overdue this month?", question: "What's overdue this month?" },
  // https://www.nls.uk/collections/rare-books/collections/icas/pacioli/
  { text: "Fun fact: Luca Pacioli published the first printed description of double-entry bookkeeping in 1494." },
  { text: "Drag me anywhere if I'm in the way. Hold Alt and use the arrow keys to move me, too." },
  { text: "Try: Which companies have documents waiting for review?", question: "Which companies have documents waiting for review?" },
  { text: "I only read your firm's data, never another firm's." },
  { text: "Press Ctrl J (or Cmd J on Mac) to open me anytime." },
];

export type CasperOutcome = "done" | "clarify" | "error";
export interface CasperNotice { id: string; kind: CasperOutcome }

const DONE_LINES = ["I'm done! Come take a look.", "Found it! Tap me to see.", "Ta-da, your answer's ready."];
export function casperDoneLine(kind: CasperOutcome): string {
  if (kind === "clarify") return "Quick question for you, tap me.";
  if (kind === "error") return "Hmm, I hit a snag. Tap to see.";
  return DONE_LINES[Math.floor(Math.random() * DONE_LINES.length)];
}
