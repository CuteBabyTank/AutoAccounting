"use client";

import { useCallback, useEffect, useState } from "react";
import { UserPlus } from "@phosphor-icons/react";
import { useAuth } from "@/lib/auth";
import Hint from "@/components/guide/Hint";
import ChecklistTemplates from "@/components/work/ChecklistTemplates";
import FirmSettingsCard from "@/components/work/FirmSettingsCard";
import { GuideButton } from "@/components/guide/GuideTour";
import PageGuide from "@/components/guide/PageGuide";
import { TEAM_TOUR } from "@/components/guide/tours";
import { TEAM_SPOTS } from "@/components/guide/tours/spots";
import { useGuide } from "@/lib/guides";
import { teamApi } from "@/lib/api";
import { apiErrorMessage, formatPeso } from "@/lib/accounting-format";
import { roleLabel } from "@/lib/roles";
import type { FirmUsage, Member } from "@/types";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export default function TeamPage() {
  const { user } = useAuth();
  const isOwner = user?.role === "enterprise" || user?.role === "admin";
  const [members, setMembers] = useState<Member[]>([]);
  const [usage, setUsage] = useState<FirmUsage | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const guide = useGuide("team");

  const load = useCallback(async () => {
    try {
      const [m, u] = await Promise.all([teamApi.members(), teamApi.usage()]);
      setMembers(m);
      setUsage(u);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't load your team"));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(action: () => Promise<unknown>, fallback: string) {
    setError("");
    setBusy(true);
    try {
      await action();
      await load();
    } catch (e) {
      setError(apiErrorMessage(e, fallback));
    } finally {
      setBusy(false);
    }
  }

  async function addMember(e: React.FormEvent) {
    e.preventDefault();
    const value = email.trim();
    if (!value) return;
    await run(async () => {
      await teamApi.add(value);
      setEmail("");
    }, "Couldn't add that member");
  }

  // Managers can't act on other managers; only the owner promotes/demotes.
  const canEdit = (m: Member) => isOwner || m.role === "employee";

  return (
    <div className="lp relative min-h-screen">
      <div className="p-4 sm:p-8 max-w-5xl page-enter">
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <div className="mr-auto">
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">Team</h1>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              {usage?.organization_name ? `${usage.organization_name} · ` : ""}People who can work on your firm&apos;s clients.
            </p>
          </div>
          <GuideButton open={guide.open} onClick={guide.toggle} />
        </div>

        <PageGuide open={guide.open} onClose={guide.dismiss} label="Team" spots={TEAM_SPOTS} slides={TEAM_TOUR} />
        <FirmSettingsCard />
        <ChecklistTemplates />

        {usage && (
          <div data-tour="usage" className="mb-6 grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
              <p className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
                Pages extracted in {MONTHS[usage.month - 1]}
                <Hint align="right">Every page our AI reads counts once, across everyone in your firm. Duplicates you drop again aren&apos;t counted.</Hint>
              </p>
              <p className="mt-1 text-2xl font-semibold text-[var(--text-primary)]">{usage.pages_used.toLocaleString()}</p>
            </div>
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
              <p className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
                Prepaid budget
                <Hint align="right">
                  {usage.billing_enabled
                    ? "Each extracted page is paid from this balance. Uploads pause at ₱0 until it's topped up."
                    : "Uploads are free right now, so there's no budget to watch."}
                </Hint>
              </p>
              <p className="mt-1 text-2xl font-semibold text-[var(--text-primary)]">
                {usage.billing_enabled ? `₱${formatPeso(usage.budget)}` : "Not billed"}
              </p>
            </div>
          </div>
        )}

        <form onSubmit={addMember} data-tour="add-member" className="mb-4 flex flex-wrap items-center gap-2">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="colleague@firm.com"
            className="w-72 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
          />
          <button
            type="submit"
            disabled={busy || !email.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
          >
            <UserPlus size={16} /> Add member
          </button>
          <p className="w-full text-xs text-[var(--text-secondary)]">
            They need to sign in with Google once first, then you can add them by email.
          </p>
        </form>

        {error && (
          <div className="mb-4 rounded-lg border border-[var(--alert-error-border)] bg-[var(--alert-error-bg)] px-4 py-2 text-sm text-[var(--alert-error-text)]">
            {error}
          </div>
        )}

        <div data-tour="members" className="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-secondary)]">
                <th className="px-4 py-3 font-medium">Member</th>
                <th className="px-4 py-3 font-medium">
                  Role <Hint>Employees upload and review documents. Managers can also set up clients and add or deactivate staff. Deactivated members keep their account but can&apos;t sign in.</Hint>
                </th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id} className="border-t border-[var(--border)] text-[var(--text-primary)]">
                  <td className="px-4 py-3">
                    <div className="font-medium">{m.nickname || m.email}</div>
                    {m.nickname && <div className="text-xs text-[var(--text-secondary)]">{m.email}</div>}
                  </td>
                  <td className="px-4 py-3">{roleLabel(m.role)}</td>
                  <td className="px-4 py-3">{m.is_active ? "Active" : "Deactivated"}</td>
                  <td className="px-4 py-3">
                    {canEdit(m) && (
                      <div className="flex flex-wrap justify-end gap-3 text-xs">
                        {isOwner && m.role === "employee" && (
                          <button disabled={busy} onClick={() => run(() => teamApi.promote(m.id), "Couldn't promote")} className="text-[var(--accent)] hover:underline">
                            Make manager
                          </button>
                        )}
                        {isOwner && m.role === "manager" && (
                          <button disabled={busy} onClick={() => run(() => teamApi.demote(m.id), "Couldn't demote")} className="text-[var(--accent)] hover:underline">
                            Make employee
                          </button>
                        )}
                        <button disabled={busy} onClick={() => run(() => teamApi.setActive(m.id, !m.is_active), "Couldn't update")} className="text-[var(--accent)] hover:underline">
                          {m.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                        <button
                          disabled={busy}
                          onClick={() => {
                            if (window.confirm(`Remove ${m.email} from the firm? Their account stays and can be re-added.`)) {
                              run(() => teamApi.remove(m.id), "Couldn't remove");
                            }
                          }}
                          className="text-[var(--error)] hover:underline"
                        >
                          Remove
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {members.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-sm text-[var(--text-secondary)]">
                    Just you so far. Ask a colleague to sign in with Google once, then add their email above.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
