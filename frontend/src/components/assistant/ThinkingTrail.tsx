"use client";

import { useEffect, useState } from "react";
import { CaretDown, CaretUp, Check, CircleNotch, Sparkle, WarningCircle } from "@phosphor-icons/react";
import type { AssistantStep } from "@/types/assistant";

/** What each lookup is called once it has run (the live label comes from the server while it runs). */
const DONE: Record<string, string> = {
  list_companies: "Looked up the firm's companies",
  search: "Searched the documents",
  get_document: "Opened a document",
  report: "Read the books",
  aging: "Checked receivables and payables",
  company_health: "Checked what needs attention",
  filings: "Checked the filings",
  quarter_returns: "Opened the quarter's returns",
  tax_reference: "Checked the BIR notes",
  ask_clarification: "Needs one detail from you",
};

function seconds(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function StepRow({ step }: { step: AssistantStep }) {
  const running = step.ok === null;
  const icon = running ? (
    <CircleNotch size={14} className="animate-spin text-[var(--text-secondary)]" />
  ) : step.ok ? (
    <Check size={14} weight="bold" className="text-[var(--accent)]" />
  ) : (
    <WarningCircle size={14} className="text-[var(--alert-warning-text)]" />
  );
  if (step.kind === "thought") {
    return (
      <li className="flex gap-2.5 text-[13.5px] leading-snug text-[var(--text-secondary)]">
        <span className="mt-[3px] shrink-0"><Check size={14} weight="bold" className="text-[var(--accent)]" /></span>
        <span className="italic">{step.summary}</span>
      </li>
    );
  }
  const title = running ? step.summary || "Working" : DONE[step.tool] ?? (step.kind === "check" ? step.tool : "Looked something up");
  const detail = running ? "" : step.summary;
  return (
    <li className="flex gap-2.5 text-[13.5px] leading-snug">
      <span className="mt-[3px] shrink-0">{icon}</span>
      <span className="min-w-0">
        <span className={running ? "aa-shimmer text-[var(--text-primary)]" : "text-[var(--text-primary)]"}>{title}</span>
        {detail && detail !== title && <span className="ml-1.5 text-[var(--text-secondary)]">{detail}</span>}
      </span>
    </li>
  );
}

interface Props {
  steps: AssistantStep[];
  pending: boolean;
  startedAt?: number;
  finishedAt?: number;
}

/** The chain of steps behind an answer: open and ticking while it works, folded into "Ran N lookups" after. */
export default function ThinkingTrail({ steps, pending, startedAt, finishedAt }: Props) {
  const [open, setOpen] = useState(pending);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    setOpen(pending);
  }, [pending]);
  useEffect(() => {
    if (!pending) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [pending]);

  const lookups = steps.filter((s) => s.kind !== "thought" && s.kind !== "check").length;
  if (!pending && steps.length === 0) return null;

  const elapsed = startedAt ? seconds((pending ? now : finishedAt ?? now) - startedAt) : "";
  const stepNo = steps.filter((s) => s.kind !== "thought").length + (pending ? 1 : 0);
  const head = pending ? (
    <>
      <CircleNotch size={16} className="animate-spin text-[var(--text-secondary)]" />
      <span className="aa-shimmer font-medium text-[var(--text-primary)]">Thinking</span>
      <span className="text-[var(--text-secondary)]">({[elapsed, `step ${Math.max(stepNo, 1)}`].filter(Boolean).join(" · ")})</span>
    </>
  ) : (
    <>
      <Sparkle size={16} className="text-[var(--accent)]" />
      <span className="font-medium text-[var(--text-primary)]">
        {lookups ? `Ran ${lookups} lookup${lookups === 1 ? "" : "s"}` : "Thought it through"}
      </span>
      {elapsed && <span className="text-[var(--text-secondary)]">in {elapsed}</span>}
    </>
  );

  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="-ml-1 flex items-center gap-2 rounded-md px-1 py-0.5 text-sm hover:bg-[var(--bg-hover)]"
      >
        {head}
        {open ? <CaretUp size={13} className="text-[var(--text-secondary)]" /> : <CaretDown size={13} className="text-[var(--text-secondary)]" />}
      </button>
      {open && (
        <ol className="aa-trail mt-2 ml-[7px] space-y-2.5 border-l border-[var(--border)] pl-4">
          {steps.map((s, i) => <StepRow key={i} step={s} />)}
          {pending && steps.every((s) => s.ok !== null) && (
            <StepRow step={{ kind: "tool", tool: "", summary: steps.length ? "Putting the answer together" : "Reading your question", ok: null }} />
          )}
        </ol>
      )}
    </div>
  );
}
