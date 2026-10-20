"use client";

import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowUp, CheckCircle, ChatCircleText, CircleNotch, Trash, Warning, WarningCircle, X,
} from "@phosphor-icons/react";
import { SearchRow } from "@/components/search/SearchResults";
import { streamChat } from "@/lib/assistant-api";
import { openResult } from "@/lib/search-nav";
import type { AssistantEvent, AssistantMessage, AssistantStep } from "@/types/assistant";

const STORE_KEY = "aa:assistant:messages";
const KEPT = 40;

const TOOL_LABELS: Record<string, string> = {
  list_companies: "Companies",
  search: "Search",
  get_document: "Document",
  report: "Books report",
  aging: "Aging",
  company_health: "Company health",
  filings: "Filings",
  quarter_returns: "Quarter returns",
  tax_reference: "BIR notes",
};

const EXAMPLES = [
  "What filings are due in the next two weeks?",
  "Which companies have documents waiting for review?",
  "Profit and loss this quarter for my first company",
  "What ATC applies to office rent?",
];

const newId = () => Math.random().toString(36).slice(2);

function load(): AssistantMessage[] {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    const list = raw ? (JSON.parse(raw) as AssistantMessage[]) : [];
    return Array.isArray(list) ? list.filter((m) => !m.pending) : [];
  } catch {
    return [];
  }
}

function save(messages: AssistantMessage[]): void {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(messages.filter((m) => !m.pending).slice(-KEPT)));
  } catch {
    // storage full or blocked: the chat still works for this visit
  }
}

/** **bold** inside one line. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>,
  );
}

/** The answer's light formatting: paragraphs and "- " / "* " / "1. " bullet lines. */
function Answer({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) {
      blocks.push(
        <ul key={blocks.length} className="ml-4 list-disc space-y-0.5">
          {bullets.map((b, i) => <li key={i}>{inline(b)}</li>)}
        </ul>,
      );
      bullets = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = line.match(/^(?:[-*•]|\d+\.)\s+(.*)$/);
    if (bullet) {
      bullets.push(bullet[1]);
      continue;
    }
    flush();
    if (line) blocks.push(<p key={blocks.length}>{inline(line.replace(/^#+\s*/, ""))}</p>);
  }
  flush();
  return <div className="space-y-2">{blocks}</div>;
}

function Steps({ steps }: { steps: AssistantStep[] }) {
  return (
    <ul className="mb-2 space-y-1">
      {steps.map((s, i) => (
        <li key={i} className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          {s.ok === null ? (
            <CircleNotch size={12} className="shrink-0 animate-spin" />
          ) : s.ok ? (
            <CheckCircle size={12} className="shrink-0 text-[var(--accent)]" />
          ) : (
            <WarningCircle size={12} className="shrink-0 text-[var(--alert-warning-text)]" />
          )}
          <span className="font-medium text-[var(--text-primary)]">{TOOL_LABELS[s.tool] ?? s.tool}</span>
          {s.summary && <span className="truncate">· {s.summary}</span>}
        </li>
      ))}
    </ul>
  );
}

/** The firm assistant: a floating chat that answers from the firm's books, documents and filings (read-only). */
export default function AssistantPanel() {
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    setMessages(load());
    setMounted(true);
  }, []);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (open) setTimeout(() => input.current?.focus(), 0);
  }, [open]);
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages, open]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const update = useCallback((id: string, change: (m: AssistantMessage) => AssistantMessage) => {
    setMessages((list) => list.map((m) => (m.id === id ? change(m) : m)));
  }, []);

  const send = useCallback(
    async (raw: string) => {
      const question = raw.trim();
      if (!question || busy) return;
      const history = messages.filter((m) => !m.error && m.text).map((m) => ({ role: m.role, text: m.text }));
      const reply: AssistantMessage = { id: newId(), role: "assistant", text: "", steps: [], pending: true };
      setMessages((list) => [...list, { id: newId(), role: "user", text: question }, reply]);
      setText("");
      setBusy(true);
      const ctrl = new AbortController();
      abort.current = ctrl;
      const onEvent = (e: AssistantEvent) => {
        if (e.type === "action") {
          update(reply.id, (m) => ({ ...m, steps: [...(m.steps ?? []), { tool: e.tool, summary: e.label ?? "", ok: null }] }));
        } else if (e.type === "observation") {
          update(reply.id, (m) => {
            const steps = [...(m.steps ?? [])];
            let at = steps.length - 1;
            while (at >= 0 && !(steps[at].tool === e.tool && steps[at].ok === null)) at -= 1;
            if (at >= 0) steps[at] = { tool: e.tool, summary: e.summary, ok: e.ok };
            return { ...m, steps };
          });
        } else if (e.type === "clarify") {
          update(reply.id, (m) => ({ ...m, text: e.question, clarification: true, pending: false,
            sources: [], ungrounded: [] }));
        } else if (e.type === "final") {
          update(reply.id, (m) => ({
            ...m, text: e.answer, sources: e.sources, ungrounded: e.ungrounded_numbers, pending: false,
          }));
        } else if (e.type === "error") {
          update(reply.id, (m) => ({ ...m, text: e.message, error: true, pending: false }));
        }
      };
      try {
        await streamChat(question, history, onEvent, ctrl.signal);
      } catch {
        if (!ctrl.signal.aborted) onEvent({ type: "error", message: "Lost the connection. Please try again." });
      } finally {
        update(reply.id, (m) => (m.pending ? { ...m, pending: false, text: m.text || "Stopped.", error: !m.text } : m));
        setBusy(false);
        abort.current = null;
      }
    },
    [busy, messages, update],
  );

  useEffect(() => {
    if (!busy) save(messages);
  }, [messages, busy]);

  const clear = () => {
    abort.current?.abort();
    setMessages([]);
    save([]);
  };

  const launcher = (
    <button
      onClick={() => setOpen((o) => !o)}
      aria-label={open ? "Close assistant" : "Ask the assistant"}
      aria-expanded={open}
      data-tour="assistant"
      className="nav-press fixed bottom-4 right-4 z-[55] flex h-12 w-12 items-center justify-center rounded-full bg-[var(--accent)] text-white shadow-lg hover:brightness-110 md:bottom-6 md:right-6"
    >
      {open ? <X size={22} /> : <ChatCircleText size={24} weight="fill" />}
    </button>
  );

  if (!mounted) return null;
  return createPortal(
    <div className="lp-skin">
      {launcher}
      {open && (
        <section
          role="dialog"
          aria-label="Assistant"
          className="modal-enter fixed inset-x-2 bottom-20 top-16 z-[55] flex flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] shadow-xl md:inset-x-auto md:right-6 md:top-auto md:h-[min(640px,calc(100vh-8rem))] md:w-[420px] md:bottom-24"
        >
          <header className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
            <ChatCircleText size={18} className="text-[var(--accent)]" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-[var(--text-primary)]">Assistant</p>
              <p className="text-xs text-[var(--text-secondary)]">Answers from your firm&apos;s books and filings. Read-only.</p>
            </div>
            {messages.length > 0 && (
              <button onClick={clear} aria-label="Clear chat" title="Clear chat" className="rounded p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]">
                <Trash size={16} />
              </button>
            )}
            <button onClick={() => setOpen(false)} aria-label="Close assistant" className="rounded p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]">
              <X size={16} />
            </button>
          </header>

          <div ref={scroller} className="flex-1 space-y-4 overflow-y-auto px-4 py-4" aria-live="polite">
            {messages.length === 0 && (
              <div className="space-y-3">
                <p className="text-sm text-[var(--text-secondary)]">
                  Ask about a client&apos;s P&amp;L, a supplier&apos;s invoices, what&apos;s due, a quarter&apos;s VAT or an ATC.
                </p>
                <div className="flex flex-wrap gap-2">
                  {EXAMPLES.map((q) => (
                    <button
                      key={q}
                      onClick={() => send(q)}
                      className="rounded-full border border-[var(--border)] px-3 py-1 text-left text-xs text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-[var(--accent-subtle)] px-3 py-2 text-sm text-[var(--text-primary)]">
                  {m.text}
                </div>
              ) : (
                <div key={m.id} className="max-w-full text-sm text-[var(--text-primary)]">
                  {m.steps && m.steps.length > 0 && <Steps steps={m.steps} />}
                  {m.pending && !m.text ? (
                    <p className="flex items-center gap-2 text-[var(--text-secondary)]">
                      <CircleNotch size={14} className="animate-spin" /> Looking…
                    </p>
                  ) : m.clarification ? (
                    <p className="whitespace-pre-wrap rounded-2xl rounded-bl-md border border-[var(--border)] bg-[var(--bg-hover)] px-3 py-2">
                      {m.text}
                    </p>
                  ) : m.error ? (
                    <p className="text-[var(--alert-error-text)]">{m.text}</p>
                  ) : (
                    <Answer text={m.text} />
                  )}
                  {m.ungrounded && m.ungrounded.length > 0 && (
                    <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-[var(--alert-warning-bg)] px-2.5 py-1.5 text-xs text-[var(--alert-warning-text)]">
                      <Warning size={14} className="mt-px shrink-0" />
                      Couldn&apos;t trace {m.ungrounded.join(", ")} to the books. Check before relying on it.
                    </p>
                  )}
                  {m.sources && m.sources.length > 0 && (
                    <div className="mt-2 rounded-lg border border-[var(--border)]">
                      <p className="px-3 pt-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]">Sources</p>
                      <ul className="p-1">
                        {m.sources.map((s) => (
                          <li key={`${s.type}-${s.id}`}>
                            <button className="w-full rounded-lg hover:bg-[var(--bg-hover)]" onClick={() => openResult(s, pathname, router.push)}>
                              <SearchRow item={s} />
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ),
            )}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(text);
            }}
            className="flex items-end gap-2 border-t border-[var(--border)] px-3 py-3"
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
              placeholder="Ask about a client, a filing, a figure…"
              aria-label="Your question"
              className="max-h-32 min-h-[40px] flex-1 resize-none rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-secondary)] focus:border-[var(--accent)] focus:outline-none"
            />
            <button
              type="submit"
              disabled={busy || !text.trim()}
              aria-label="Send"
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)] text-white disabled:opacity-40"
            >
              {busy ? <CircleNotch size={18} className="animate-spin" /> : <ArrowUp size={18} weight="bold" />}
            </button>
          </form>
        </section>
      )}
    </div>,
    document.body,
  );
}
