"use client";

import { ArrowLeft, CheckCircle, LockSimple, PencilSimple, Prohibit } from "@phosphor-icons/react";
import { shortName, type PageCompany } from "@/lib/page-context";

interface Section {
  title: string;
  what: string;
  examples: string[];
}

/** Everything Casper can answer (read) or prepare (write), with examples about the open company when there is one. */
function sections(company: PageCompany | null): { read: Section[]; write: Section[] } {
  const c = company ? shortName(company.name) : "a client";
  const cs = company ? `${shortName(company.name)}'s` : "a client's";
  return {
    read: [
      {
        title: "Your work",
        what: "Your open tasks and the filings assigned to you: what's overdue, due today and coming up.",
        examples: ["What do I need to do today?", "What's on my plate this week?", "What's the team working on this week?"],
      },
      {
        title: "Deadlines and filings",
        what: "BIR returns owed across the firm or for one client, due dates, who's on them and what's filed.",
        examples: [
          "What's due in the next two weeks?",
          "What's overdue across my clients?",
          `Which returns does ${c} file this quarter?`,
          `What are the figures on ${cs} latest 2550-Q?`,
        ],
      },
      {
        title: "Review and health",
        what: "Documents waiting for review, unreconciled bank months, months not closed, pending 2307s.",
        examples: [
          "Which clients have documents waiting for review?",
          `What needs attention at ${c}?`,
          `Which months aren't closed yet at ${c}?`,
        ],
      },
      {
        title: "Books and reports",
        what: "Profit and loss, balance sheet, trial balance and ledger detail from the books, for any period.",
        examples: [
          `What was ${cs} net income last quarter?`,
          `Show ${cs} balance sheet at the end of last month`,
          `How much did ${c} spend on rent this year?`,
          `Show ${cs} trial balance this year`,
        ],
      },
      {
        title: "Customers and suppliers",
        what: "Who owes the client money and who the client owes, with aging.",
        examples: [`Who owes ${c} money for over 90 days?`, `Which suppliers does ${c} still owe?`],
      },
      {
        title: "Find records",
        what: "Receipts, invoices, 2307s, bank lines, journal entries, tasks and contacts by number, name, TIN, amount or date.",
        examples: ["Find OR 12345", "Find Meralco bills from October", "Find documents for TIN 123-456-789", "Find receipts for ₱1,500"],
      },
      {
        title: "BIR notes",
        what: "What a return is for, when it's due, and withholding ATC codes with their rates.",
        examples: ["What ATC applies to office rent?", "When is the 1601-EQ due?", "What is the 0619-E for?"],
      },
    ],
    write: [
      {
        title: "Tasks",
        what: "Create, reschedule, reassign, finish or delete one task at a time.",
        examples: [
          company ? `Remind me to collect ${cs} October receipts by Friday` : "Remind me to follow up missing receipts next Friday",
          "Move my receipts follow-up task to next Monday",
          "Mark my bank statement task as done",
          "Give my receipts follow-up task to Ana",
          "Delete my task about the old client meeting",
        ],
      },
      {
        title: "Filings on the work board",
        what: "Who a filing is assigned to and how far along it is. Marking a return filed stays with you.",
        examples: [`Assign ${cs} 2550-Q for this quarter to me`, `Set ${cs} October 1601-C to documents in`],
      },
      {
        title: "Documents",
        what: "A document's account, category, quarter or notes, or delete one (managers and the owner).",
        examples: [
          `Move ${cs} latest receipt waiting for review to Office supplies`,
          "Put the October Meralco bill in Q4",
          "Add a note to OR 12345: paid in cash",
          "Delete the duplicate Meralco bill from October",
        ],
      },
    ],
  };
}

const NEVER = [
  "Change or delete companies, firms, people, roles or settings",
  "File a return, mark one filed, or close the books",
  "Change many records at once",
];

/** The "What else can I do?" view: every capability, grouped, with examples that drop into the composer. */
export default function CasperHelp({ company, canWrite, writeReason, onBack, onPick }: {
  company: PageCompany | null;
  canWrite: boolean;
  writeReason: string;
  onBack: () => void;
  /** Put an example in the composer; `write` = it needs write mode. */
  onPick: (text: string, write: boolean) => void;
}) {
  const { read, write } = sections(company);
  const example =
    "w-full rounded-lg px-2.5 py-1.5 text-left text-[13.5px] text-[var(--text-primary)] hover:bg-[var(--bg-hover)] hover:text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-[var(--text-primary)]";

  const block = (s: Section, isWrite: boolean) => (
    <li key={s.title} className="py-3">
      <p className="text-sm font-medium text-[var(--text-primary)]">{s.title}</p>
      <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">{s.what}</p>
      <ul className="-mx-2.5 mt-1.5">
        {s.examples.map((e) => (
          <li key={e}>
            <button type="button" className={example} disabled={isWrite && !canWrite} onClick={() => onPick(e, isWrite)}>
              “{e}”
            </button>
          </li>
        ))}
      </ul>
    </li>
  );

  return (
    <div>
      <button type="button" onClick={onBack} className="mb-4 flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
        <ArrowLeft size={14} />
        Back to the chat
      </button>
      <h3 className="text-[15px] font-medium text-[var(--text-primary)]">What Casper can do</h3>
      <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
        Tap an example to put it in the message box, change anything you like, then send.
        {company ? ` Examples are about ${company.name}, the company you have open.` : ""}
      </p>

      <h4 className="mt-5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
        <LockSimple size={12} /> Ask anything
      </h4>
      <ul className="divide-y divide-[var(--border-sidebar)]">{read.map((s) => block(s, false))}</ul>

      <h4 className="mt-5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
        <PencilSimple size={12} /> With write mode on
      </h4>
      {canWrite ? (
        <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
          Casper prepares the change on a card. Nothing happens until you press Confirm, and you can undo it, or restore
          anything deleted, for 7 days.
        </p>
      ) : (
        <p className="mt-1 rounded-lg bg-[var(--bg-hover)] px-3 py-2 text-xs leading-relaxed text-[var(--text-secondary)]">
          {writeReason || "Write mode isn't available for you."} You can still see what it covers below.
        </p>
      )}
      <ul className="divide-y divide-[var(--border-sidebar)]">{write.map((s) => block(s, true))}</ul>

      <h4 className="mt-5 text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">Always</h4>
      <ul className="mt-2 space-y-1.5 text-[13px] leading-relaxed text-[var(--text-secondary)]">
        <li className="flex gap-2"><CheckCircle size={15} className="mt-0.5 shrink-0 text-[var(--accent)]" />Reads only your firm&apos;s records, and only the areas you have access to</li>
        <li className="flex gap-2"><CheckCircle size={15} className="mt-0.5 shrink-0 text-[var(--accent)]" />Checks every figure in an answer against the books</li>
        {NEVER.map((n) => (
          <li key={n} className="flex gap-2"><Prohibit size={15} className="mt-0.5 shrink-0 text-[var(--alert-error-text)]" />Never: {n.charAt(0).toLowerCase() + n.slice(1)}</li>
        ))}
      </ul>
    </div>
  );
}
