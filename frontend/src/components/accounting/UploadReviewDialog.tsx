"use client";

import { useState } from "react";
import { CheckCircle, X } from "@phosphor-icons/react";
import CompanyForm from "@/components/accounting/CompanyForm";
import { apiErrorMessage, formatTin } from "@/lib/accounting-format";
import type { Company, ConfirmAssignment, Upload, UploadGroup } from "@/types/accounting";

type Decision = { kind: "company"; companyId: string } | { kind: "skip" };

interface Props {
  upload: Upload;
  companies: Company[];
  canManage: boolean;
  onCompanyCreated: (company: Company) => void;
  onConfirm: (assignments: ConfirmAssignment[]) => Promise<void>;
  onClose: () => void;
}

const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50";
const SELECT = "rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)]";

const tin9 = (tin: string) => tin.replace(/\D/g, "").slice(0, 9);

/** Unmatched groups whose TIN now belongs to a company (one added since the drop) start out filed to it. */
function initialDecisions(groups: UploadGroup[], companies: Company[]): Record<string, Decision> {
  const out: Record<string, Decision> = {};
  for (const g of groups) {
    const tin = tin9(g.detected_tin);
    const match = !g.company && tin.length === 9 ? companies.find((c) => tin9(c.tin) === tin) : undefined;
    if (match) out[g.key] = { kind: "company", companyId: match.id };
  }
  return out;
}

export default function UploadReviewDialog({ upload, companies, canManage, onCompanyCreated, onConfirm, onClose }: Props) {
  const [decisions, setDecisions] = useState<Record<string, Decision>>(() => initialDecisions(upload.groups, companies));
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [newCompanyFor, setNewCompanyFor] = useState<UploadGroup | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const duplicates = upload.files.filter((f) => f.status === "duplicate").length;
  const allDecided = upload.groups.every((g) => decisions[g.key]);
  const decide = (key: string, d: Decision) => setDecisions((prev) => ({ ...prev, [key]: d }));
  const nameOf = (id: string) => companies.find((c) => c.id === id)?.registered_name ?? "selected company";

  const toggleFile = (id: string) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  async function submit(current: Record<string, Decision> = decisions) {
    const assignments: ConfirmAssignment[] = [];
    const skipped = [...excluded];
    for (const g of upload.groups) {
      const ids = g.file_ids.filter((id) => !excluded.has(id));
      const d = current[g.key];
      if (!ids.length || !d) continue;
      if (d.kind === "skip") skipped.push(...ids);
      else assignments.push({ file_ids: ids, company_id: d.companyId });
    }
    if (skipped.length) assignments.push({ file_ids: skipped, skip: true });
    setSubmitting(true);
    setError("");
    try {
      await onConfirm(assignments);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't confirm the upload"));
      setSubmitting(false);
    }
  }

  const chooseOther = (g: UploadGroup) => (
    <select
      className={SELECT}
      value=""
      onChange={(e) => {
        if (e.target.value) decide(g.key, { kind: "company", companyId: e.target.value });
      }}
    >
      <option value="">{g.company ? "Choose another company…" : "Choose existing company…"}</option>
      {companies.map((c) => (
        <option key={c.id} value={c.id}>{c.registered_name}</option>
      ))}
    </select>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-6">
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">Which company are these for?</h2>
          <button onClick={onClose} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <p className="mb-5 text-sm text-[var(--text-secondary)]">
          Confirm each group before the documents are read and filed.
          {duplicates > 0 && ` ${duplicates} file${duplicates === 1 ? " was" : "s were"} already uploaded and skipped.`}
        </p>

        <div className="space-y-4">
          {upload.groups.map((g) => {
            const d = decisions[g.key];
            const company = g.company;
            const count = g.file_ids.filter((id) => !excluded.has(id)).length;
            return (
              <div key={g.key} className="rounded-xl border border-[var(--border)] p-4">
                {g.level === "unreadable" ? (
                  <p className="text-sm text-[var(--text-primary)]">
                    We couldn&apos;t read a company name or TIN from {count === 1 ? "this file" : `these ${count} files`}.
                    Choose the company {count === 1 ? "it belongs" : "they belong"} to, or skip{" "}
                    {count === 1 ? "it" : "them"} and drop {count === 1 ? "it" : "them"} again later.
                  </p>
                ) : g.company ? (
                  <p className="text-sm text-[var(--text-primary)]">
                    {count === 1 ? "This file looks like it belongs" : `These ${count} files look like they belong`} to{" "}
                    <strong>{g.company.registered_name}</strong> (TIN {formatTin(g.company.tin)})
                    {g.level === "likely" && <span className="text-[var(--text-secondary)]">, matched by name</span>}. Correct?
                  </p>
                ) : (
                  <p className="text-sm text-[var(--text-primary)]">
                    We couldn&apos;t find this company in your databank
                    {g.detected_name || g.detected_tin ? (
                      <>
                        : <strong>{g.detected_name || "Unnamed"}</strong>
                        {g.detected_tin && ` (TIN ${formatTin(g.detected_tin)})`}
                      </>
                    ) : null}
                    . Is this a new company? ({count} file{count === 1 ? "" : "s"})
                  </p>
                )}

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {company && (
                    <button className={BTN} onClick={() => decide(g.key, { kind: "company", companyId: company.id })}>
                      Yes, that&apos;s right
                    </button>
                  )}
                  <button
                    className={BTN}
                    disabled={!canManage}
                    title={canManage ? undefined : "Ask an owner or manager to add this company"}
                    onClick={() => setNewCompanyFor(g)}
                  >
                    {g.company ? "No, it's a new company" : g.level === "unreadable" ? "It's a new company" : "Add to databank"}
                  </button>
                  {chooseOther(g)}
                  <button className={BTN} onClick={() => decide(g.key, { kind: "skip" })}>
                    Skip these files
                  </button>
                  <button className="ml-auto text-xs text-[var(--text-secondary)] underline" onClick={() => setExpanded(expanded === g.key ? null : g.key)}>
                    {expanded === g.key ? "Hide files" : "Show files"}
                  </button>
                </div>

                {d && (
                  <p className="mt-2 flex items-center gap-1.5 text-sm font-medium text-[var(--accent)]">
                    <CheckCircle size={16} weight="fill" />
                    {d.kind === "skip" ? "Will be skipped" : `Filing to ${nameOf(d.companyId)}`}
                  </p>
                )}

                {expanded === g.key && (
                  <ul className="mt-3 space-y-1 border-t border-[var(--border)] pt-3">
                    {g.file_ids.map((id, i) => (
                      <li key={id}>
                        <label className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                          <input type="checkbox" checked={!excluded.has(id)} onChange={() => toggleFile(id)} />
                          {g.file_names[i]}
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>

        {error && <p className="mt-4 text-sm text-[var(--alert-error-text)]">{error}</p>}

        <div className="mt-6 flex justify-end gap-2">
          <button className={BTN} onClick={onClose}>Decide later</button>
          <button
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
            disabled={!allDecided || submitting}
            onClick={() => submit()}
          >
            {submitting ? "Starting…" : "Confirm and file"}
          </button>
        </div>
      </div>

      {newCompanyFor && (
        <CompanyForm
          initial={{
            registered_name: newCompanyFor.detected_name,
            // A TIN that matched an existing company can't be the new one's.
            tin: newCompanyFor.detected_tin === newCompanyFor.company?.tin ? "" : newCompanyFor.detected_tin,
            address: newCompanyFor.detected_address,
          }}
          onClose={() => setNewCompanyFor(null)}
          onSaved={(company) => {
            onCompanyCreated(company);
            const next: Record<string, Decision> = { ...decisions, [newCompanyFor.key]: { kind: "company", companyId: company.id } };
            setDecisions(next);
            setNewCompanyFor(null);
            // Nothing left to decide: carry on filing the drop instead of asking for another click.
            if (upload.groups.every((g) => next[g.key])) submit(next);
          }}
        />
      )}
    </div>
  );
}
