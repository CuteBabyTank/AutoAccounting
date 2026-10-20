"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ArrowUp, Brain, LockSimple, Plus, SidebarSimple, Stop, Warning } from "@phosphor-icons/react";
import AnswerText from "@/components/assistant/AnswerText";
import ThinkingTrail from "@/components/assistant/ThinkingTrail";
import { SearchRow } from "@/components/search/SearchResults";
import { assistantInfo, modelLabel, streamChat } from "@/lib/assistant-api";
import { openResult } from "@/lib/search-nav";
import type { AssistantEvent, AssistantInfo, AssistantMessage, AssistantStep } from "@/types/assistant";

const STORE_KEY = "aa:assistant:messages";
const OPEN_KEY = "aa:assistant:open";
const KEPT = 40;

const SUGGESTIONS = [
  "What filings are due in the next two weeks?",
  "Which companies have documents waiting for review?",
  "What was net income last quarter?",
  "What ATC applies to office rent?",
];

const newId = () => Math.random().toString(36).slice(2);

const stamp = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const when = (ms?: number) => (ms ? stamp.format(ms).replace(" at", ",") : "");

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key) ?? sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown, session = false): void {
  try {
    (session ? sessionStorage : localStorage).setItem(key, JSON.stringify(value));
  } catch {
    // storage blocked: the chat still works for this visit
  }
}

/** A conversation's title: its first question, cut to one line. */
function titleOf(messages: AssistantMessage[]): string {
  const first = messages.find((m) => m.role === "user")?.text.trim();
  if (!first) return "New chat";
  return first.length > 48 ? `${first.slice(0, 46).trimEnd()}…` : first;
}

/**
 * The firm assistant, docked on the right of every signed-in page. Closed, it's a round button bottom-right; open,
 * it's a full-height column that pushes the page over (a sheet over it on phones). Answers come from the firm's own
 * books, documents and filings; each shows the steps it took while it works, folded away once it's done.
 */
export default function AssistantDock() {
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<AssistantInfo | null>(null);
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const saved = read<AssistantMessage[]>(STORE_KEY, []);
    setMessages(Array.isArray(saved) ? saved.filter((m) => !m.pending) : []);
    setOpen(read<boolean>(OPEN_KEY, false) === true);
    setMounted(true);
    return () => abort.current?.abort();
  }, []);
  useEffect(() => {
    if (open && !info) assistantInfo().then(setInfo).catch(() => undefined);
  }, [open, info]);
  useEffect(() => {
    if (!mounted) return;
    write(OPEN_KEY, open);
    if (open) setTimeout(() => input.current?.focus(), 0);
  }, [open, mounted]);
  useEffect(() => {
    if (!busy && mounted) write(STORE_KEY, messages.filter((m) => !m.pending).slice(-KEPT), true);
  }, [messages, busy, mounted]);
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages, open]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape" && open && window.matchMedia("(max-width: 767px)").matches) {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  // Grow the composer with its text, up to a few lines.
  useEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text, open]);

  const update = useCallback((id: string, change: (m: AssistantMessage) => AssistantMessage) => {
    setMessages((list) => list.map((m) => (m.id === id ? change(m) : m)));
  }, []);

  const send = useCallback(
    async (raw: string) => {
      const question = raw.trim();
      if (!question || busy) return;
      const history = messages.filter((m) => !m.error && m.text).map((m) => ({ role: m.role, text: m.text }));
      const now = Date.now();
      const reply: AssistantMessage = {
        id: newId(), role: "assistant", text: "", steps: [], pending: true, at: now, model: info?.model,
      };
      setMessages((list) => [...list, { id: newId(), role: "user", text: question, at: now }, reply]);
      setText("");
      setBusy(true);
      const ctrl = new AbortController();
      abort.current = ctrl;
      const push = (step: AssistantStep) => update(reply.id, (m) => ({ ...m, steps: [...(m.steps ?? []), step] }));
      const onEvent = (e: AssistantEvent) => {
        if (e.type === "thought") {
          push({ kind: "thought", tool: "", summary: e.text, ok: true });
        } else if (e.type === "action") {
          push({ kind: "tool", tool: e.tool, summary: e.label ?? "", ok: null });
        } else if (e.type === "observation") {
          update(reply.id, (m) => {
            const steps = [...(m.steps ?? [])];
            let at = steps.length - 1;
            while (at >= 0 && !(steps[at].tool === e.tool && steps[at].ok === null)) at -= 1;
            if (at >= 0) steps[at] = { ...steps[at], summary: e.summary, ok: e.ok };
            return { ...m, steps };
          });
        } else if (e.type === "clarify") {
          update(reply.id, (m) => ({
            ...m, text: e.question, clarification: true, pending: false, doneAt: Date.now(), sources: [], ungrounded: [],
          }));
        } else if (e.type === "final") {
          update(reply.id, (m) => {
            const looked = (m.steps ?? []).some((s) => s.kind === "tool");
            const check: AssistantStep[] = !looked
              ? []
              : e.ungrounded_numbers.length
                ? [{ kind: "check", tool: "Some figures couldn't be traced to the books", summary: e.ungrounded_numbers.join(", "), ok: false }]
                : [{ kind: "check", tool: "Checked the figures against what it found", summary: "", ok: true }];
            return {
              ...m, text: e.answer, sources: e.sources, ungrounded: e.ungrounded_numbers, pending: false,
              doneAt: Date.now(), steps: [...(m.steps ?? []), ...check],
            };
          });
        } else if (e.type === "error") {
          update(reply.id, (m) => ({ ...m, text: e.message, error: true, pending: false, doneAt: Date.now() }));
        }
      };
      try {
        await streamChat(question, history, onEvent, ctrl.signal);
      } catch {
        if (!ctrl.signal.aborted) onEvent({ type: "error", message: "Lost the connection. Send the question again." });
      } finally {
        update(reply.id, (m) =>
          m.pending ? { ...m, pending: false, doneAt: Date.now(), text: m.text || "Stopped.", error: !m.text } : m,
        );
        setBusy(false);
        abort.current = null;
      }
    },
    [busy, info?.model, messages, update],
  );

  const stop = () => abort.current?.abort();
  const newChat = () => {
    abort.current?.abort();
    setMessages([]);
    setText("");
    input.current?.focus();
  };

  if (!mounted) return null;

  const launcher = !open && (
    <button
      type="button"
      onClick={() => setOpen(true)}
      aria-label="Open the assistant (Ctrl J)"
      title="Assistant (Ctrl J)"
      data-tour="assistant"
      className="aa-launcher nav-press fixed bottom-5 right-5 z-[55] flex h-14 w-14 items-center justify-center rounded-full border border-[var(--border-sidebar)] bg-[var(--bg-secondary)] text-[var(--text-primary)] md:bottom-6 md:right-6"
    >
      <Brain size={28} weight="light" />
    </button>
  );

  const model = info?.model ? modelLabel(info.model) : "";

  return (
    <>
      {launcher}
      {open && (
        <aside
          aria-label="Assistant"
          className="aa-dock lp-skin fixed inset-0 z-[60] flex flex-col bg-[var(--bg-secondary)] md:static md:z-auto md:h-screen md:w-[400px] md:shrink-0 md:border-l md:border-[var(--border-sidebar)] xl:w-[440px]"
        >
          <header className="flex h-14 shrink-0 items-center gap-1 border-b border-[var(--border-sidebar)] pl-5 pr-2">
            <h2 className="min-w-0 flex-1 truncate text-[15px] font-medium text-[var(--text-primary)]" title={titleOf(messages)}>
              {titleOf(messages)}
            </h2>
            <button type="button" onClick={newChat} aria-label="New chat" title="New chat" className="aa-icon-btn">
              <Plus size={18} />
            </button>
            <button type="button" onClick={() => setOpen(false)} aria-label="Hide the assistant" title="Hide (Ctrl J)" className="aa-icon-btn">
              <SidebarSimple size={18} mirrored />
            </button>
          </header>

          <div ref={scroller} className="flex-1 overflow-y-auto px-5 py-6" aria-live="polite">
            {messages.length === 0 ? (
              <div className="flex min-h-full flex-col justify-end pb-2">
                <Brain size={30} weight="light" className="mb-3 text-[var(--accent)]" />
                <p className="text-[17px] font-medium text-[var(--text-primary)]">Ask about your clients</p>
                <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
                  Figures from the books, what&apos;s due, what needs review, a quarter&apos;s returns or an ATC. It only reads your firm&apos;s records and never changes them.
                </p>
                <ul className="mt-5 divide-y divide-[var(--border-sidebar)] border-y border-[var(--border-sidebar)]">
                  {SUGGESTIONS.map((q) => (
                    <li key={q}>
                      <button
                        type="button"
                        onClick={() => send(q)}
                        className="w-full py-2.5 text-left text-sm text-[var(--text-primary)] hover:text-[var(--accent)]"
                      >
                        {q}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="space-y-7">
                {messages.map((m) =>
                  m.role === "user" ? (
                    <div key={m.id} className="flex flex-col items-end">
                      <p className="max-w-[88%] whitespace-pre-wrap rounded-[20px] bg-[var(--text-primary)] px-4 py-2.5 text-[14.5px] leading-relaxed text-[var(--bg-secondary)]">
                        {m.text}
                      </p>
                      {m.at && <span className="mt-1.5 text-[11.5px] text-[var(--text-tertiary)]">{when(m.at)}</span>}
                    </div>
                  ) : (
                    <div key={m.id}>
                      <ThinkingTrail steps={m.steps ?? []} pending={!!m.pending} startedAt={m.at} finishedAt={m.doneAt} />
                      {m.pending ? null : m.error ? (
                        <p className="flex items-start gap-2 text-[14.5px] leading-relaxed text-[var(--alert-error-text)]">
                          <Warning size={16} className="mt-1 shrink-0" />
                          {m.text}
                        </p>
                      ) : m.clarification ? (
                        <div className="border-l-2 border-[var(--accent)] pl-3">
                          <AnswerText text={m.text} />
                          <p className="mt-1.5 text-xs text-[var(--text-secondary)]">Reply below and it will carry on.</p>
                        </div>
                      ) : (
                        <AnswerText text={m.text} />
                      )}
                      {!m.pending && m.ungrounded && m.ungrounded.length > 0 && (
                        <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-[var(--alert-warning-bg)] px-3 py-2 text-xs leading-relaxed text-[var(--alert-warning-text)]">
                          <Warning size={14} className="mt-px shrink-0" />
                          Couldn&apos;t trace {m.ungrounded.join(", ")} to the books. Check before relying on it.
                        </p>
                      )}
                      {!m.pending && m.sources && m.sources.length > 0 && (
                        <div className="mt-4">
                          <p className="mb-1 text-xs font-medium text-[var(--text-secondary)]">Sources</p>
                          <ul className="-mx-3">
                            {m.sources.map((s) => (
                              <li key={`${s.type}-${s.id}`}>
                                <button type="button" className="w-full rounded-lg hover:bg-[var(--bg-hover)]" onClick={() => openResult(s, pathname, router.push)}>
                                  <SearchRow item={s} />
                                </button>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {!m.pending && (
                        <div className="mt-3 space-y-0.5 text-[11.5px] text-[var(--text-tertiary)]">
                          {(m.model || info?.model) && <p>{modelLabel(m.model || info?.model || "")}, reading this firm only</p>}
                          {m.doneAt && <p>{when(m.doneAt)}</p>}
                        </div>
                      )}
                    </div>
                  ),
                )}
              </div>
            )}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(text);
            }}
            className="m-3 mt-0 shrink-0 rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] shadow-[0_1px_2px_rgba(16,24,40,0.04)] focus-within:border-[var(--accent)]"
          >
            <textarea
              ref={input}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send(text);
                }
              }}
              rows={1}
              maxLength={2000}
              placeholder="Ask about a client, a filing or a figure"
              aria-label="Your question"
              className="block max-h-40 w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-[14.5px] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none"
            />
            <div className="flex items-center gap-2 px-2.5 pb-2.5 pt-1">
              <span className="flex items-center gap-1 rounded-md border border-[var(--border-sidebar)] px-2 py-1 text-xs text-[var(--text-secondary)]" title="It can look things up but never changes your records">
                <LockSimple size={12} />
                Read-only
              </span>
              <span className="ml-auto truncate rounded-md bg-[var(--bg-hover)] px-2 py-1 text-xs text-[var(--text-secondary)]" title={info?.model}>
                {model ? `${model}${info?.local ? ", on this machine" : ""}` : "Assistant"}
              </span>
              {busy ? (
                <button type="button" onClick={stop} aria-label="Stop" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--text-primary)] text-[var(--bg-secondary)]">
                  <Stop size={14} weight="fill" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!text.trim()}
                  aria-label="Send"
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)] text-white transition-opacity disabled:opacity-35"
                >
                  <ArrowUp size={16} weight="bold" />
                </button>
              )}
            </div>
          </form>
        </aside>
      )}
    </>
  );
}
