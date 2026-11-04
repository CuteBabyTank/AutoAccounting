"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChatCircleText, LockSimple, PencilSimple, Prohibit, X } from "@phosphor-icons/react";
import { teamApi } from "@/lib/api";
import { firmSettings } from "@/lib/work-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { roleLabel } from "@/lib/roles";
import type { AccessArea, AssistantLevel, Member, MemberAccess } from "@/types";

type CasperChoice = AssistantLevel | "default";

const CASPER: { value: CasperChoice; title: string; text: string; Icon: typeof LockSimple }[] = [
  { value: "default", title: "Firm default", text: "Follows \"Casper can make changes for\" in Work settings.", Icon: LockSimple },
  { value: "off", title: "Off", text: "No Casper chat at all.", Icon: Prohibit },
  { value: "read", title: "Ask questions", text: "Casper answers from the records but never changes anything.", Icon: ChatCircleText },
  { value: "write", title: "Ask and make changes", text: "Casper can also prepare changes. Each one waits for their Confirm and can be undone for 7 days.", Icon: PencilSimple },
];

/** One-click starting points; the switches below can then be fine-tuned. Keys not listed are turned off. */
const PRESETS: { name: string; text: string; on: string[] | "all" }[] = [
  { name: "Full access", text: "Everything on", on: "all" },
  {
    name: "Bookkeeper",
    text: "Documents and books, no filing or firm setup",
    on: ["documents", "upload", "search", "notifications", "work", "books", "recurring", "bank", "subledgers", "reports", "atc", "employees"],
  },
  { name: "Documents only", text: "Upload, sort and review documents", on: ["documents", "upload", "search", "notifications", "work"] },
];

/**
 * Team page: what one person can use. Areas switched off disappear from their menus and the server refuses them;
 * Casper follows the same access, so it can't read or change those areas for them either.
 */
export default function AccessPanel({ member, onClose, onSaved }: {
  member: Member;
  onClose: () => void;
  onSaved: (m: Member) => void;
}) {
  const [areas, setAreas] = useState<AccessArea[] | null>(null);
  const [off, setOff] = useState<Set<string>>(() => new Set(member.access?.off ?? []));
  const [casper, setCasper] = useState<CasperChoice>(member.access?.assistant ?? "default");
  const [busy, setBusy] = useState(false);
  const [firmDefault, setFirmDefault] = useState("");
  const [error, setError] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  const name = member.nickname || member.email;

  useEffect(() => {
    teamApi.accessCatalog().then(setAreas).catch((e) => setError(apiErrorMessage(e, "Couldn't load the list of areas")));
    firmSettings()
      .then((s) => {
        const writes = s.assistant_writes === "everyone" || (s.assistant_writes === "managers" && member.role === "manager");
        setFirmDefault(writes ? "Right now that means: ask and make changes." : "Right now that means: ask questions only.");
      })
      .catch(() => undefined);
  }, [member.role]);
  useEffect(() => {
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const groups = useMemo(() => {
    const map = new Map<string, AccessArea[]>();
    for (const a of areas ?? []) map.set(a.group, [...(map.get(a.group) ?? []), a]);
    return [...map.entries()];
  }, [areas]);

  const initial = useMemo(
    () => JSON.stringify({ off: [...(member.access?.off ?? [])].sort(), casper: member.access?.assistant ?? "default" }),
    [member.access],
  );
  const dirty = JSON.stringify({ off: [...off].sort(), casper }) !== initial;
  const onCount = (areas?.length ?? 0) - off.size;

  const toggle = (key: string) =>
    setOff((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const preset = (on: string[] | "all") =>
    setOff(new Set(on === "all" ? [] : (areas ?? []).map((a) => a.key).filter((k) => !on.includes(k))));
  const activePreset = PRESETS.find((p) =>
    p.on === "all" ? off.size === 0 : (areas ?? []).every((a) => (p.on as string[]).includes(a.key) !== off.has(a.key)),
  )?.name;

  async function save() {
    setBusy(true);
    setError("");
    try {
      const body: MemberAccess = { off: [...off], ...(casper === "default" ? {} : { assistant: casper }) };
      onSaved(await teamApi.setAccess(member.id, body));
      onClose();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save their access"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[90] flex justify-end bg-black/30" onClick={onClose}>
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="access-title"
        onClick={(e) => e.stopPropagation()}
        className="lp-skin flex h-full w-full max-w-[480px] flex-col bg-[var(--bg-secondary)] shadow-2xl outline-none"
      >
        <header className="flex items-start gap-3 border-b border-[var(--border)] px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 id="access-title" className="truncate text-base font-semibold text-[var(--text-primary)]">What {name} can use</h2>
            <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
              {roleLabel(member.role)}. Anything turned off disappears from their screens, and Casper can&apos;t use it for them either.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="aa-icon-btn">
            <X size={18} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          <section aria-labelledby="casper-heading">
            <h3 id="casper-heading" className="text-sm font-semibold text-[var(--text-primary)]">Casper, the assistant</h3>
            <div role="radiogroup" aria-labelledby="casper-heading" className="mt-2 grid gap-2">
              {CASPER.map(({ value, title, text, Icon }) => {
                const picked = casper === value;
                return (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={picked}
                    onClick={() => setCasper(value)}
                    className={`flex items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                      picked ? "border-[var(--accent)] bg-[var(--accent)]/[0.06]" : "border-[var(--border)] hover:border-[var(--text-tertiary)]"
                    }`}
                  >
                    <Icon size={16} className={`mt-0.5 shrink-0 ${picked ? "text-[var(--accent)]" : "text-[var(--text-secondary)]"}`} />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-[var(--text-primary)]">{title}</span>
                      <span className="block text-xs leading-relaxed text-[var(--text-secondary)]">
                        {text}
                        {value === "default" && firmDefault ? ` ${firmDefault}` : ""}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="mt-7" aria-labelledby="areas-heading">
            <div className="flex items-baseline justify-between gap-2">
              <h3 id="areas-heading" className="text-sm font-semibold text-[var(--text-primary)]">Areas</h3>
              {areas && <span className="text-xs text-[var(--text-secondary)]">{onCount} of {areas.length} on</span>}
            </div>
            <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Quick choices">
              {PRESETS.map((p) => (
                <button
                  key={p.name}
                  type="button"
                  disabled={!areas}
                  onClick={() => preset(p.on)}
                  title={p.text}
                  aria-pressed={activePreset === p.name}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors disabled:opacity-50 ${
                    activePreset === p.name
                      ? "border-[var(--accent)] bg-[var(--accent)] text-white"
                      : "border-[var(--border)] text-[var(--text-primary)] hover:border-[var(--accent)]"
                  }`}
                >
                  {p.name}
                </button>
              ))}
            </div>

            {!areas && !error && <p className="mt-4 text-sm text-[var(--text-tertiary)]">Loading…</p>}
            {groups.map(([group, list]) => (
              <div key={group} className="mt-5">
                <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-[var(--text-tertiary)]">{group}</p>
                <ul className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)]">
                  {list.map((a) => {
                    const on = !off.has(a.key);
                    return (
                      <li key={a.key}>
                        <label className="flex cursor-pointer items-center gap-3 px-3 py-2.5">
                          <span className="min-w-0 flex-1">
                            <span className={`block text-sm ${on ? "text-[var(--text-primary)]" : "text-[var(--text-secondary)] line-through decoration-[var(--text-tertiary)]"}`}>
                              {a.label}
                            </span>
                            <span className="block text-xs leading-relaxed text-[var(--text-secondary)]">{a.description}</span>
                          </span>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={on}
                            aria-label={`${a.label}: ${on ? "on" : "off"}`}
                            onClick={() => toggle(a.key)}
                            className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
                              on ? "bg-[var(--accent)]" : "bg-[var(--border)]"
                            }`}
                          >
                            <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${on ? "translate-x-[18px]" : "translate-x-0.5"}`} />
                          </button>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </section>
        </div>

        <footer className="border-t border-[var(--border)] px-5 py-3">
          {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
          <div className="flex items-center justify-end gap-2">
            <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
              Cancel
            </button>
            <button
              type="button"
              disabled={busy || !dirty || !areas}
              onClick={save}
              className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save access"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
