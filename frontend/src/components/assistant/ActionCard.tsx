"use client";

import { useEffect, useState } from "react";
import { ArrowCounterClockwise, Check, PencilSimple, Trash, X } from "@phosphor-icons/react";
import { cancelAction, confirmAction, undoAction } from "@/lib/assistant-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { AssistantAction } from "@/types/assistant";

const DAY = 86_400_000;

/** "6 days left", "5 hours left", "a few minutes left". */
export function timeLeft(until: string | null, now: number): string {
  if (!until) return "";
  const ms = new Date(until).getTime() - now;
  if (ms <= 0) return "";
  if (ms >= DAY) return `${Math.floor(ms / DAY)} day${ms >= 2 * DAY ? "s" : ""} left`;
  const hours = Math.floor(ms / 3_600_000);
  return hours >= 1 ? `${hours} hour${hours > 1 ? "s" : ""} left` : "a few minutes left";
}

const undoLabel = (a: AssistantAction) => (a.kind.startsWith("delete") ? "Restore" : "Undo");

/** Shown as expired once its confirm window has passed, even before the server is asked. */
export function effectiveStatus(a: AssistantAction, now: number): AssistantAction["status"] {
  return a.status === "proposed" && new Date(a.expires_at).getTime() <= now ? "expired" : a.status;
}

/**
 * One change Casper proposed. Nothing happens until the person presses Confirm; the server runs the stored version
 * of exactly what is listed here. Once done, Undo (or Restore for a delete) stays open for 7 days.
 */
export default function ActionCard({ action, onChange, compact = false }: {
  action: AssistantAction;
  onChange: (next: AssistantAction) => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState<"" | "confirm" | "cancel" | "undo">("");
  const [error, setError] = useState("");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  const run = async (kind: "confirm" | "cancel" | "undo") => {
    setBusy(kind);
    setError("");
    try {
      const call = kind === "confirm" ? confirmAction : kind === "cancel" ? cancelAction : undoAction;
      onChange(await call(action.id));
    } catch (e) {
      setError(apiErrorMessage(e, kind === "undo" ? "Couldn't undo that change" : "Couldn't do that"));
    } finally {
      setBusy("");
    }
  };

  const status = effectiveStatus(action, now);
  const danger = action.destructive;
  const left = timeLeft(action.undo_until, now);
  const Icon = danger ? Trash : PencilSimple;
  const border =
    status === "proposed"
      ? danger ? "border-[var(--alert-error-text)]" : "border-[var(--accent)]"
      : "border-[var(--border)]";

  return (
    <div className={`rounded-xl border ${border} bg-[var(--bg-secondary)] ${compact ? "p-3" : "mt-3 p-3.5"}`}>
      <div className="flex items-start gap-2">
        <Icon size={16} className={`mt-0.5 shrink-0 ${danger ? "text-[var(--alert-error-text)]" : "text-[var(--accent)]"}`} />
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-medium leading-snug text-[var(--text-primary)]">{action.summary}</p>
          {action.company_name && <p className="mt-0.5 text-xs text-[var(--text-secondary)]">{action.company_name}</p>}
        </div>
      </div>

      {!compact && action.details.length > 0 && (
        <dl className="mt-2.5 space-y-1 border-t border-[var(--border-sidebar)] pt-2.5 text-[13px]">
          {action.details.map((d) => (
            <div key={d.label} className="flex gap-3">
              <dt className="w-24 shrink-0 text-[var(--text-secondary)]">{d.label}</dt>
              <dd className="min-w-0 break-words text-[var(--text-primary)]">{d.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {status === "proposed" && (
        <>
          {danger && (
            <p className="mt-2.5 text-xs text-[var(--alert-error-text)]">You can restore it for 7 days after it&apos;s deleted.</p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!!busy || !action.can_confirm}
              onClick={() => run("confirm")}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium text-white disabled:opacity-50 ${
                danger ? "bg-[var(--alert-error-text)]" : "bg-[var(--accent)]"
              }`}
            >
              <Check size={14} weight="bold" />
              {busy === "confirm" ? "Working…" : danger ? "Confirm delete" : "Confirm"}
            </button>
            <button
              type="button"
              disabled={!!busy}
              onClick={() => run("cancel")}
              className="flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[13px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-50"
            >
              <X size={14} />
              Cancel
            </button>
          </div>
          {!action.can_confirm && (
            <p className="mt-2 text-xs text-[var(--text-secondary)]">Only {action.user_name || "the person who asked"} can confirm this.</p>
          )}
        </>
      )}

      {status === "applied" && (
        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
          <span className="flex items-center gap-1 font-medium text-[var(--accent)]">
            <Check size={14} weight="bold" />
            Done
          </span>
          {action.can_undo && left && (
            <>
              <button
                type="button"
                disabled={!!busy}
                onClick={() => run("undo")}
                className="flex items-center gap-1 text-[var(--text-primary)] underline-offset-2 hover:underline disabled:opacity-50"
              >
                <ArrowCounterClockwise size={14} />
                {busy === "undo" ? "Working…" : undoLabel(action)}
              </button>
              <span className="text-xs text-[var(--text-tertiary)]">{left}</span>
            </>
          )}
        </div>
      )}

      {status === "undone" && (
        <p className="mt-2.5 text-[13px] text-[var(--text-secondary)]">{action.kind.startsWith("delete") ? "Restored." : "Undone."}</p>
      )}
      {status === "cancelled" && <p className="mt-2.5 text-[13px] text-[var(--text-secondary)]">Cancelled. Nothing changed.</p>}
      {status === "expired" && (
        <p className="mt-2.5 text-[13px] text-[var(--text-secondary)]">Not confirmed in time, so nothing changed. Ask again if you still want it.</p>
      )}
      {status === "failed" && (
        <p className="mt-2.5 text-[13px] text-[var(--alert-error-text)]">Didn&apos;t go through: {action.error || "something went wrong"}. Nothing changed.</p>
      )}
      {error && <p className="mt-2 text-[13px] text-[var(--alert-error-text)]">{error}</p>}
    </div>
  );
}
