"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { usePathname, useRouter } from "next/navigation";
import { Bell, X } from "@phosphor-icons/react";
import { OPEN_COMPANY_EVENT, workApi } from "@/lib/work-api";
import type { AppNotification, Notifications } from "@/types/work";

const POLL_MS = 120_000;
const KIND_LABEL: Record<AppNotification["kind"], string> = {
  deadline: "Deadline",
  review: "Review",
  bank: "Bank",
  cwt: "2307",
  task_assigned: "Task",
  task_due: "Task",
};

interface Props {
  /** "rail": a sidebar row (label fades in with the rail); "bar": the mobile top bar icon. */
  variant: "rail" | "bar";
  fadeStyle?: CSSProperties;
}

/** The bell in the app shell: deadlines, documents to review, unreconciled bank months, missing 2307s and tasks. */
export default function NotificationBell({ variant, fadeStyle }: Props) {
  const [data, setData] = useState<Notifications | null>(null);
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const pathname = usePathname();
  const panel = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    workApi.notifications().then(setData).catch(() => undefined);
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!open) return;
    load();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    panel.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, load]);

  const unread = data?.unread ?? 0;

  async function go(n: AppNotification) {
    setOpen(false);
    if (!n.read) workApi.readNotifications([n.key]).then(setData).catch(() => undefined);
    if (n.kind === "deadline") router.push(n.company_id ? `/accounting/work?company=${n.company_id}` : "/accounting/work");
    else if (n.kind === "task_assigned" || n.kind === "task_due") router.push("/accounting/work?tab=tasks");
    else if (n.company_id) {
      if (pathname === "/accounting") window.dispatchEvent(new CustomEvent(OPEN_COMPANY_EVENT, { detail: n.company_id }));
      else router.push(`/accounting?company=${n.company_id}`);
    }
  }

  const button =
    variant === "rail" ? (
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        className="aa-item nav-press relative flex items-center gap-3 w-full h-10 px-3 rounded-xl text-sm whitespace-nowrap overflow-hidden text-[var(--text-sidebar-muted)] hover:text-[var(--text-sidebar)]"
      >
        <Bell size={20} weight="light" className="shrink-0" />
        {unread > 0 && (
          <span className="absolute left-[26px] top-1 min-w-[16px] rounded-full bg-[var(--badge-red-text)] px-1 text-center text-[10px] font-semibold leading-4 text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
        <span style={fadeStyle} className="aa-fade">Notifications</span>
      </button>
    ) : (
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        className="nav-press relative ml-auto flex items-center justify-center w-11 h-11 rounded-lg text-[var(--text-sidebar)] hover:bg-[var(--bg-sidebar-hover)]"
      >
        <Bell size={22} />
        {unread > 0 && (
          <span className="absolute right-1.5 top-1.5 min-w-[16px] rounded-full bg-[var(--badge-red-text)] px-1 text-center text-[10px] font-semibold leading-4 text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
    );

  return (
    <>
      {button}
      {open &&
        createPortal(
          <div className="lp-skin fixed inset-0 z-[60]" onClick={() => setOpen(false)}>
            <div
              ref={panel}
              tabIndex={-1}
              role="dialog"
              aria-label="Notifications"
              onClick={(e) => e.stopPropagation()}
              className="modal-enter fixed inset-x-3 top-16 flex max-h-[70vh] flex-col rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] shadow-xl outline-none md:inset-x-auto md:left-[88px] md:top-auto md:bottom-6 md:w-[380px]"
            >
              <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
                <h2 className="text-sm font-semibold text-[var(--text-primary)]">Notifications</h2>
                {data && data.items.length > 0 && (
                  <>
                    <button
                      className="ml-auto text-xs font-medium text-[var(--accent)] hover:underline"
                      onClick={() => workApi.readNotifications([], true).then(setData).catch(() => undefined)}
                    >
                      Mark all read
                    </button>
                    <button
                      className="text-xs font-medium text-[var(--text-secondary)] hover:underline"
                      onClick={() => workApi.dismissNotifications([], true).then(setData).catch(() => undefined)}
                    >
                      Clear all
                    </button>
                  </>
                )}
                <button onClick={() => setOpen(false)} aria-label="Close" className={`${data?.items.length ? "" : "ml-auto"} rounded p-1 hover:bg-[var(--bg-hover)]`}>
                  <X size={16} />
                </button>
              </div>
              <div className="overflow-y-auto">
                {!data ? (
                  <p className="px-4 py-6 text-sm text-[var(--text-secondary)]">Loading…</p>
                ) : data.items.length === 0 ? (
                  <p className="px-4 py-8 text-center text-sm text-[var(--text-secondary)]">You&apos;re all caught up.</p>
                ) : (
                  <ul className="divide-y divide-[var(--border)]">
                    {data.items.map((n) => (
                      <li key={n.key} className={`group flex items-start gap-2 px-4 py-2.5 ${n.read ? "" : "bg-[var(--accent-subtle)]"}`}>
                        <button onClick={() => go(n)} className="min-w-0 flex-1 text-left">
                          <span className="flex items-center gap-1.5">
                            <span
                              className={`rounded-full px-1.5 text-[10px] font-semibold ${n.severity === "high" ? "bg-[var(--badge-red-bg)] text-[var(--badge-red-text)]" : "bg-[var(--bg-hover)] text-[var(--text-secondary)]"}`}
                            >
                              {KIND_LABEL[n.kind]}
                            </span>
                            {!n.read && <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" aria-label="Unread" />}
                          </span>
                          <span className="mt-0.5 block text-sm text-[var(--text-primary)]">{n.title}</span>
                          {n.detail && <span className="block truncate text-xs text-[var(--text-secondary)]">{n.detail}</span>}
                        </button>
                        <button
                          onClick={() => workApi.dismissNotifications([n.key]).then(setData).catch(() => undefined)}
                          aria-label={`Dismiss ${n.title}`}
                          title="Dismiss"
                          className="rounded p-1 text-[var(--text-secondary)] opacity-60 hover:bg-[var(--bg-hover)] hover:opacity-100"
                        >
                          <X size={14} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
