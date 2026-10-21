"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Hint from "@/components/guide/Hint";
import CompanyHealth from "@/components/work/CompanyHealth";
import CashFlowTile from "@/components/accounting/CashFlowTile";
import KpiTiles from "@/components/accounting/KpiTiles";
import PrivacyToggle from "@/components/accounting/PrivacyToggle";
import ApplyChecklist from "@/components/work/ApplyChecklist";
import TaskList from "@/components/work/TaskList";
import { workApi } from "@/lib/work-api";
import { useFeatures } from "@/lib/features";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Board } from "@/types/work";
import { BTN, Chip, STATUS_META, dueText, shortDate } from "@/components/work/ui";

interface Props {
  companyId: string;
  companyName: string;
  companies: { id: string; registered_name: string }[];
}

/** Company → Overview: upcoming filings, the health check and the client's tasks on one page. */
export default function CompanyOverviewPanel({ companyId, companyName, companies }: Props) {
  const [board, setBoard] = useState<Board | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [taskKey, setTaskKey] = useState(0);
  const [error, setError] = useState("");
  const { on } = useFeatures();
  const reportsOn = on("reports");
  // The filings list and tasks come from the work board; they hide while it's switched off.
  const workOn = on("work");

  useEffect(() => {
    if (!workOn) return;
    let cancelled = false;
    workApi
      .board({ company_id: companyId })
      .then((b) => !cancelled && setBoard(b))
      .catch((e) => !cancelled && setError(apiErrorMessage(e, "Couldn't load the filings")));
    return () => {
      cancelled = true;
    };
  }, [companyId, refresh, workOn]);

  const open = (board?.cards ?? []).filter((c) => c.status !== "filed");
  return (
    <div className="mb-6 space-y-6">
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold text-[var(--text-primary)]">
            Overview · {companyName}{" "}
            <Hint align="right">
              What needs doing for this client: returns coming due, problems to fix before filing or closing a month, and
              the firm&apos;s tasks for them. The work board shows the same for every client.
            </Hint>
          </h2>
          <PrivacyToggle className="ml-auto" />
          {workOn && <Link href={`/accounting/work?company=${encodeURIComponent(companyId)}`} className={BTN}>Open on the work board</Link>}
        </div>
        {error && <p className="text-sm text-[var(--alert-error-text)]">{error}</p>}
        {workOn && board && (open.length === 0 ? (
          <p className="text-sm text-[var(--text-secondary)]">No returns open in the last 90 days or due in the next 45.</p>
        ) : (
          <ul className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]">
            {open.map((c) => (
              <li key={c.key} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                <span className="font-medium text-[var(--text-primary)]">{c.form_label}</span>
                <span className="text-[var(--text-secondary)]">{c.period_label}</span>
                <Chip tone={STATUS_META[c.status].tone}>{STATUS_META[c.status].label}</Chip>
                <span className={`ml-auto text-xs ${c.overdue ? "font-semibold text-[var(--badge-red-text)]" : "text-[var(--text-secondary)]"}`}>
                  Due {shortDate(c.due_date)} · {dueText(c.days_left)}
                </span>
                <span className="w-full text-xs text-[var(--text-secondary)] sm:w-auto">{c.assignee_name || "Nobody assigned"}</span>
              </li>
            ))}
          </ul>
        ))}
      </div>
      {reportsOn && (
        <>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Key figures this quarter</h3>
            <KpiTiles companyId={companyId} />
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Cash flow, next 8 weeks</h3>
            <CashFlowTile companyId={companyId} />
          </div>
        </>
      )}
      <div>
        <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Health check</h3>
        <CompanyHealth companyId={companyId} refreshKey={refresh} />
      </div>
      {workOn && <div>
        <h3 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Tasks</h3>
        <ApplyChecklist companyId={companyId} people={board?.people ?? []} onApplied={() => setTaskKey((n) => n + 1)} />
        <TaskList
          key={taskKey}
          companies={companies}
          people={board?.people ?? []}
          fixed={{ company_id: companyId }}
          onChanged={() => setRefresh((n) => n + 1)}
        />
      </div>}
    </div>
  );
}
