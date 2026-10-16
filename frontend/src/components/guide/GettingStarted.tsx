"use client";

import Link from "next/link";
import { CheckCircle, Circle, X } from "@phosphor-icons/react";
import { useGuide } from "@/lib/guides";
import type { TreeCompany, TreeQuarter } from "@/types/accounting";

interface Props {
  tree: TreeCompany[];
  canManage: boolean;
  /** Staff added to the firm (the owner isn't counted), or null when not loaded / not visible to this role. */
  memberCount: number | null;
  onAddCompany: () => void;
  onUpload: () => void;
  onOpenQuarter: (q: TreeQuarter, companyId: string) => void;
}

interface Step {
  id: string;
  title: string;
  body: string;
  done: boolean;
  action?: { label: string; run?: () => void; href?: string };
}

/** First-run checklist on Documents. Ticks itself off from the firm's real data and hides once everything is done. */
export default function GettingStarted({ tree, canManage, memberCount, onAddCompany, onUpload, onOpenQuarter }: Props) {
  const { open, dismiss } = useGuide("getting-started");

  const quarters = tree.flatMap((c) => c.years.flatMap((y) => y.quarters.map((q) => ({ q, companyId: c.id }))));
  const withDocs = quarters.find(({ q }) => q.document_count > 0);
  const toReview = quarters.find(({ q }) => q.review_count > 0);
  const generated = quarters.find(({ q }) => q.latest_version);
  const hasDocs = Boolean(withDocs) || tree.some((c) => c.undated_count > 0);

  const steps: Step[] = [
    {
      id: "company",
      title: "Add your first client",
      body: "Enter their TIN and tax registration so we know which returns to prepare. You can also skip this and add them when you drop their files.",
      done: tree.length > 0,
      action: canManage ? { label: "Add company", run: onAddCompany } : undefined,
    },
    {
      id: "upload",
      title: "Drop their documents",
      body: "Receipts, invoices, 2307s or payroll. We read them and file each one under the right quarter.",
      done: hasDocs,
      action: { label: "Upload files", run: onUpload },
    },
    {
      id: "review",
      title: "Check the flagged ones",
      body: "Anything we weren't sure about gets a yellow count in the folder list. Open it, fix what's wrong, mark it reviewed.",
      done: hasDocs && !toReview,
      action: toReview ? { label: "Open quarter", run: () => onOpenQuarter(toReview.q, toReview.companyId) } : undefined,
    },
    {
      id: "generate",
      title: "Generate a quarter's returns",
      body: "Open a quarter and click Generate to get filled BIR forms and an Excel workbook.",
      done: Boolean(generated),
      action: withDocs ? { label: "Open quarter", run: () => onOpenQuarter(withDocs.q, withDocs.companyId) } : undefined,
    },
  ];
  if (canManage && memberCount !== null) {
    steps.push({
      id: "team",
      title: "Invite your team",
      body: "Add colleagues by their Google email so they can upload and review too.",
      done: memberCount > 0,
      action: { label: "Go to Team", href: "/team" },
    });
  }

  const doneCount = steps.filter((s) => s.done).length;
  if (!open || doneCount === steps.length) return null;
  const next = steps.find((s) => !s.done);

  return (
    <section aria-label="Getting started" className="page-enter mb-6 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4 sm:p-5">
      <div className="mb-1 flex items-center gap-3">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">Getting started</h2>
        <span className="text-xs tabular-nums text-[var(--text-secondary)]">{doneCount} of {steps.length} done</span>
        <button
          onClick={dismiss}
          aria-label="Hide getting started"
          title="Hide"
          className="ml-auto rounded-md p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
        >
          <X size={14} />
        </button>
      </div>
      <div className="mb-4 h-1 overflow-hidden rounded-full bg-[var(--bg-primary)]">
        <div className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-500" style={{ width: `${(doneCount / steps.length) * 100}%` }} />
      </div>
      <ol className="space-y-1">
        {steps.map((s) => {
          const isNext = s.id === next?.id;
          return (
            <li key={s.id} className={`flex items-start gap-3 rounded-lg px-2 py-2 ${isNext ? "bg-[var(--accent-subtle)]" : ""}`}>
              {s.done ? (
                <CheckCircle size={20} weight="fill" className="mt-0.5 shrink-0 text-[var(--accent)]" />
              ) : (
                <Circle size={20} className={`mt-0.5 shrink-0 ${isNext ? "text-[var(--accent)]" : "text-[var(--text-tertiary)]"}`} />
              )}
              <div className="min-w-0 flex-1">
                <p className={`text-sm font-medium ${s.done ? "text-[var(--text-secondary)] line-through" : "text-[var(--text-primary)]"}`}>{s.title}</p>
                {isNext && <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">{s.body}</p>}
              </div>
              {isNext && s.action && (
                s.action.href ? (
                  <Link href={s.action.href} className="shrink-0 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:bg-[var(--accent-hover)]">
                    {s.action.label}
                  </Link>
                ) : (
                  <button onClick={s.action.run} className="shrink-0 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:bg-[var(--accent-hover)]">
                    {s.action.label}
                  </button>
                )
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
