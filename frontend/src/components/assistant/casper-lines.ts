/** Shown once per browser session after sign-in. */
export const CASPER_LINES = [
  { text: "Howdy! I'm Casper. Ask me anything about your clients, filings or books." },
];

export type CasperOutcome = "done" | "clarify" | "error";
export interface CasperNotice { id: string; kind: CasperOutcome }

const DONE_LINES = ["I'm done! Come take a look.", "Found it! Tap me to see.", "Ta-da, your answer's ready."];
export function casperDoneLine(kind: CasperOutcome): string {
  if (kind === "clarify") return "Quick question for you, tap me.";
  if (kind === "error") return "Hmm, I hit a snag. Tap to see.";
  return DONE_LINES[Math.floor(Math.random() * DONE_LINES.length)];
}
