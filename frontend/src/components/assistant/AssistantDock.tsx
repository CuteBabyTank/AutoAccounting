"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ArrowUp, CaretRight, ClockCounterClockwise, LockSimple, PencilSimple, Plus, Question, SidebarSimple, Stop, Warning } from "@phosphor-icons/react";
import CasperHelp from "@/components/assistant/CasperHelp";
import ActionCard from "@/components/assistant/ActionCard";
import CasperChanges from "@/components/assistant/CasperChanges";
import AnswerText from "@/components/assistant/AnswerText";
import BotMascot from "@/components/assistant/BotMascot";
import CasperLauncher from "@/components/assistant/CasperLauncher";
import type { CasperNotice, CasperOutcome } from "@/components/assistant/casper-lines";
import ThinkingTrail from "@/components/assistant/ThinkingTrail";
import useBotMascotState from "@/components/assistant/useBotMascotState";
import { SearchRow } from "@/components/search/SearchResults";
import { assistantInfo, modelLabel, streamChat } from "@/lib/assistant-api";
import { openResult } from "@/lib/search-nav";
import { useFeatures } from "@/lib/features";
import { companyQuestion, shortName, usePageCompany, type PageCompany } from "@/lib/page-context";
import type { AssistantAction, AssistantEvent, AssistantInfo, AssistantMessage, AssistantStep } from "@/types/assistant";

const STORE_KEY = "aa:assistant:messages";
const OPEN_KEY = "aa:assistant:open";
const KEPT = 40;

/** Starting questions: different for read-only and write mode, about the open company when there is one. */
function suggestions(write: boolean, company: PageCompany | null): string[] {
  const c = company ? shortName(company.name) : "";
  if (write) {
    return company
      ? [
          `Remind me to collect ${c}'s October receipts by Friday`,
          `Assign ${c}'s 2550-Q for this quarter to me`,
          `Mark my ${c} bank statement task as done`,
          `Move ${c}'s latest receipt waiting for review to Office supplies`,
          `Make a task to prepare ${c}'s 0619-E, due the 10th`,
        ]
      : [
          "Remind me to follow up missing receipts next Friday",
          "Mark my bank statement task as done",
          "Move my receipts follow-up task to next Monday",
          "Assign a client's 2550-Q for this quarter to me",
          "Make a task to prepare this month's 0619-E, due the 10th",
        ];
  }
  return company
    ? [
        `What needs to be done for ${c} this week?`,
        `What was ${c}'s net income this year?`,
        `What needs review at ${c}?`,
        `Who owes ${c} money for over 90 days?`,
        `Which returns does ${c} file this quarter?`,
      ]
    : [
        "What do I need to do today?",
        "What's overdue across my clients?",
        "Which clients have documents waiting for review?",
        "What was net income last quarter?",
        "Find Meralco bills from October",
      ];
}

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
  const [casperNotice, setCasperNotice] = useState<CasperNotice | null>(null);
  // Write mode: off every time the dock opens; Casper may then propose changes, each needing Confirm.
  const [writeMode, setWriteMode] = useState(false);
  const [showChanges, setShowChanges] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const features = useFeatures();
  const pageCompany = usePageCompany();
  // Per chat: whether the person said their questions are about the open company (asked once per company).
  const [companyAnswers, setCompanyAnswers] = useState<Record<string, "yes" | "no">>({});
  const openRef = useRef(open);
  useEffect(() => { openRef.current = open; }, [open]);
  const { state: mascotState, start: startMascot, finish: finishMascot, reset: resetMascot } = useBotMascotState(busy);
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
    else setWriteMode(false);
  }, [open, mounted]);
  useEffect(() => {
    if (!busy && mounted) write(STORE_KEY, messages.filter((m) => !m.pending).slice(-KEPT), true);
  }, [messages, busy, mounted]);
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
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
  /** A change moved on (confirmed, cancelled, undone): show the new state wherever its card is. */
  const actionChanged = useCallback((next: AssistantAction) => {
    setMessages((list) => list.map((m) =>
      m.actions?.some((a) => a.id === next.id) ? { ...m, actions: m.actions.map((a) => (a.id === next.id ? next : a)) } : m,
    ));
  }, []);

  const send = useCallback(
    async (raw: string, opts: { companyId?: string | null; askedAlready?: boolean } = {}) => {
      const question = raw.trim();
      if (!question || busy) return;
      const writing = writeMode;
      let companyId = opts.companyId;
      if (companyId === undefined) {
        companyId = null;
        const pc = pageCompany;
        if (pc) {
          const said = companyAnswers[pc.id];
          const verdict = companyQuestion(question, pc);
          if (said === "yes" && verdict !== "skip") companyId = pc.id;
          else if (verdict === "yes") {
            companyId = pc.id;
            setCompanyAnswers((a) => ({ ...a, [pc.id]: "yes" }));
          } else if (verdict === "ask" && said === undefined) {
            // Ask first, with one-click answers; nothing goes to the model until they pick.
            const now = Date.now();
            setMessages((list) => [
              ...list,
              { id: newId(), role: "user", text: question, at: now },
              { id: newId(), role: "assistant", text: "", at: now, doneAt: now, ask: { companyId: pc.id, companyName: pc.name, question } },
            ]);
            setText("");
            return;
          }
        }
      }
      startMascot();
      const said = opts.askedAlready ? messages.slice(0, -2) : messages; // the asked question is already on screen
      const history = said.filter((m) => !m.error && m.text && !m.ask).map((m) => ({ role: m.role, text: m.text }));
      const now = Date.now();
      const reply: AssistantMessage = {
        id: newId(), role: "assistant", text: "", steps: [], pending: true, at: now, model: info?.model,
      };
      setMessages((list) => (opts.askedAlready ? [...list, reply] : [...list, { id: newId(), role: "user", text: question, at: now }, reply]));
      setText("");
      setBusy(true);
      const ctrl = new AbortController();
      abort.current = ctrl;
      let succeeded = false;
      let outcome: CasperOutcome = "error";
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
        } else if (e.type === "proposal") {
          update(reply.id, (m) => ({ ...m, actions: [...(m.actions ?? []).filter((a) => a.id !== e.action.id), e.action] }));
        } else if (e.type === "clarify") {
          succeeded = true;
          outcome = "clarify";
          update(reply.id, (m) => ({
            ...m, text: e.question, clarification: true, pending: false, doneAt: Date.now(), sources: [], ungrounded: [],
            replies: e.replies ?? [],
          }));
        } else if (e.type === "final") {
          succeeded = true;
          outcome = "done";
          update(reply.id, (m) => {
            const looked = (m.steps ?? []).some((s) => s.kind === "tool");
            const check: AssistantStep[] = !looked
              ? []
              : e.ungrounded_numbers.length
                ? [{ kind: "check", tool: "Some figures couldn't be traced to the books", summary: e.ungrounded_numbers.join(", "), ok: false }]
                : [{ kind: "check", tool: "Checked the figures against what it found", summary: "", ok: true }];
            return {
              ...m, text: e.answer, sources: e.sources, ungrounded: e.ungrounded_numbers, pending: false, replies: e.replies ?? [],
              doneAt: Date.now(), steps: [...(m.steps ?? []), ...check],
            };
          });
        } else if (e.type === "error") {
          succeeded = false;
          outcome = "error";
          resetMascot();
          update(reply.id, (m) => ({ ...m, text: e.message, error: true, pending: false, doneAt: Date.now() }));
        }
      };
      try {
        await streamChat(question, history, onEvent, ctrl.signal, writing, companyId);
      } catch {
        if (!ctrl.signal.aborted) onEvent({ type: "error", message: "Lost the connection. Send the question again." });
      } finally {
        update(reply.id, (m) =>
          m.pending ? { ...m, pending: false, doneAt: Date.now(), text: m.text || "Stopped.", error: !m.text } : m,
        );
        setBusy(false);
        const notify = !openRef.current && !ctrl.signal.aborted;
        finishMascot(succeeded && !ctrl.signal.aborted, notify ? 8200 : 2500);
        if (notify) setCasperNotice({ id: reply.id, kind: outcome });
        abort.current = null;
      }
    },
    [busy, info?.model, messages, update, startMascot, finishMascot, resetMascot, writeMode, pageCompany, companyAnswers],
  );

  /** One click on "Is this about …?": remember it for this chat and run the question. */
  const answerAsk = (m: AssistantMessage, answer: "yes" | "no" | "other") => {
    if (!m.ask || m.ask.answered || busy || messages[messages.length - 1]?.id !== m.id) return;
    const { companyId, question } = m.ask;
    update(m.id, (x) => ({ ...x, ask: x.ask && { ...x.ask, answered: answer } }));
    setCompanyAnswers((a) => ({ ...a, [companyId]: answer === "yes" ? "yes" : "no" }));
    if (answer === "other") {
      setText(`${question} for `);
      setTimeout(() => input.current?.focus(), 0);
      return;
    }
    send(question, { companyId: answer === "yes" ? companyId : null, askedAlready: true });
  };

  const stop = () => {
    resetMascot();
    abort.current?.abort();
  };
  const newChat = () => {
    resetMascot();
    abort.current?.abort();
    setMessages([]);
    setCompanyAnswers({});
    setShowChanges(false);
    setShowHelp(false);
    setText("");
    input.current?.focus();
  };

  if (!mounted) return null;

  const model = info?.model ? modelLabel(info.model) : "";
  const canWrite = !!info?.write?.allowed && features.on("assistant_write");
  const writing = writeMode && canWrite;

  return (
    <>
      <CasperLauncher open={open} state={mascotState} notice={casperNotice} onOpen={() => setOpen(true)} />
      {open && (
        <aside
          aria-label="Assistant"
          className="aa-dock lp-skin fixed inset-0 z-[60] flex flex-col bg-[var(--bg-secondary)] md:static md:z-auto md:h-screen md:w-[400px] md:shrink-0 md:border-l md:border-[var(--border-sidebar)] xl:w-[440px]"
        >
          <header className="flex h-14 shrink-0 items-center gap-1 border-b border-[var(--border-sidebar)] pl-5 pr-2">
            <BotMascot state={mascotState} size={36} />
            <h2 className="min-w-0 flex-1 truncate text-[15px] font-medium text-[var(--text-primary)]" title={titleOf(messages)}>
              {titleOf(messages)}
            </h2>
            <button
              type="button"
              onClick={() => { setShowHelp((v) => !v); setShowChanges(false); }}
              aria-label="What Casper can do"
              title="What Casper can do"
              aria-pressed={showHelp}
              className="aa-icon-btn"
            >
              <Question size={18} />
            </button>
            {canWrite && (
              <button type="button" onClick={() => { setShowChanges((v) => !v); setShowHelp(false); }} aria-label="Casper's changes" title="Casper's changes (last 7 days)" aria-pressed={showChanges} className="aa-icon-btn">
                <ClockCounterClockwise size={18} />
              </button>
            )}
            <button type="button" onClick={newChat} aria-label="New chat" title="New chat" className="aa-icon-btn">
              <Plus size={18} />
            </button>
            <button type="button" onClick={() => setOpen(false)} aria-label="Hide the assistant" title="Hide (Ctrl J)" className="aa-icon-btn">
              <SidebarSimple size={18} mirrored />
            </button>
          </header>

          <div ref={scroller} className="flex-1 overflow-y-auto px-5 py-6" aria-live="polite">
            {showHelp ? (
              <CasperHelp
                company={pageCompany}
                canWrite={canWrite}
                writeReason={info?.write?.reason ?? ""}
                onBack={() => setShowHelp(false)}
                onPick={(example, needsWrite) => {
                  if (needsWrite) setWriteMode(true);
                  setShowHelp(false);
                  setText(example);
                  setTimeout(() => input.current?.focus(), 0);
                }}
              />
            ) : showChanges ? (
              <CasperChanges onBack={() => setShowChanges(false)} onChange={actionChanged} />
            ) : messages.length === 0 ? (
              <div className="flex min-h-full flex-col justify-end pb-2">
                <p className="text-[17px] font-medium text-[var(--text-primary)]">Howdy! I&apos;m Casper.</p>
                <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
                  Ask what&apos;s on your plate today, what&apos;s due or overdue, what needs review, figures from the books, a quarter&apos;s returns or an ATC.
                  {writing
                    ? " With write mode on I can also set up tasks, assign filings and tidy documents. I'll show you each change first, and nothing happens until you confirm it."
                    : " I only read your firm's records and never change them."}
                </p>
                <ul className="mt-5 divide-y divide-[var(--border-sidebar)] border-y border-[var(--border-sidebar)]">
                  {suggestions(writing, pageCompany).map((q) => (
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
                  <li>
                    <button
                      type="button"
                      onClick={() => setShowHelp(true)}
                      className="flex w-full items-center gap-1.5 py-2.5 text-left text-sm font-medium text-[var(--accent)] hover:underline"
                    >
                      What else can I do?
                      <CaretRight size={13} weight="bold" />
                    </button>
                  </li>
                </ul>
              </div>
            ) : (
              <div className="space-y-7">
                {messages.map((m, i) =>
                  m.role === "user" ? (
                    <div key={m.id} className="flex flex-col items-end">
                      <p className="max-w-[88%] whitespace-pre-wrap rounded-[20px] bg-[var(--text-primary)] px-4 py-2.5 text-[14.5px] leading-relaxed text-[var(--bg-secondary)]">
                        {m.text}
                      </p>
                      {m.at && <span className="mt-1.5 text-[11.5px] text-[var(--text-tertiary)]">{when(m.at)}</span>}
                    </div>
                  ) : m.ask ? (
                    <CompanyAsk key={m.id} ask={m.ask} disabled={busy} latest={i === messages.length - 1} onAnswer={(a) => answerAsk(m, a)} />
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
                          {!m.replies?.length && (
                            <p className="mt-1.5 text-xs text-[var(--text-secondary)]">Reply below and it will carry on.</p>
                          )}
                        </div>
                      ) : (
                        <AnswerText text={m.text} />
                      )}
                      {m.actions?.map((a) => <ActionCard key={a.id} action={a} onChange={actionChanged} />)}
                      {!m.pending && !m.error && i === messages.length - 1 && !busy && m.replies && m.replies.length > 0 && (
                        <QuickReplies replies={m.replies} onPick={send} onType={() => input.current?.focus()} />
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
                          {(m.model || info?.model) && <p>{modelLabel(m.model || info?.model || "")}, {m.actions?.length ? "changes only with your confirm" : "reading this firm only"}</p>}
                          {m.doneAt && <p>{when(m.doneAt)}</p>}
                        </div>
                      )}
                    </div>
                  ),
                )}
              </div>
            )}
          </div>

          {pageCompany && companyAnswers[pageCompany.id] === "yes" && !showChanges && !showHelp && (
            <div className="mx-3 mb-2 flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
              <span className="truncate rounded-full border border-[var(--accent)] bg-[var(--accent)]/[0.06] px-2.5 py-1 text-[var(--accent)]">
                About {pageCompany.name}
              </span>
              <button
                type="button"
                onClick={() => setCompanyAnswers((a) => ({ ...a, [pageCompany.id]: "no" }))}
                className="rounded-full px-1.5 py-1 hover:text-[var(--text-primary)]"
                title="Stop assuming this company"
                aria-label={`Stop assuming ${pageCompany.name}`}
              >
                ×
              </button>
            </div>
          )}
          {writing && !showChanges && (
            <p className="mx-3 mb-2 flex items-start gap-1.5 rounded-lg bg-[var(--alert-warning-bg)] px-3 py-2 text-xs leading-relaxed text-[var(--alert-warning-text)]">
              <PencilSimple size={13} className="mt-px shrink-0" />
              Write mode is on. Casper can propose changes, and nothing happens until you confirm.
            </p>
          )}
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
              placeholder={writing ? "Ask, or tell Casper what to change" : "Ask about a client, a filing or a figure"}
              aria-label="Your question"
              className="block max-h-40 w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-[14.5px] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none"
            />
            <div className="flex items-center gap-2 px-2.5 pb-2.5 pt-1">
              {canWrite ? (
                <button
                  type="button"
                  role="switch"
                  aria-checked={writeMode}
                  onClick={() => setWriteMode((v) => !v)}
                  title={writeMode ? "Casper can propose changes for you to confirm. Click to go back to read-only." : "Let Casper propose changes (each needs your confirm)"}
                  className={`flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors ${
                    writeMode
                      ? "border-[var(--alert-warning-text)] bg-[var(--alert-warning-bg)] font-medium text-[var(--alert-warning-text)]"
                      : "border-[var(--border-sidebar)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  }`}
                >
                  {writeMode ? <PencilSimple size={12} /> : <LockSimple size={12} />}
                  {writeMode ? "Write mode" : "Read-only"}
                </button>
              ) : (
                <span className="flex items-center gap-1 rounded-md border border-[var(--border-sidebar)] px-2 py-1 text-xs text-[var(--text-secondary)]" title={info?.write?.reason || "It can look things up but never changes your records"}>
                  <LockSimple size={12} />
                  Read-only
                </span>
              )}
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


/** One-tap answers under a question: "Yes" plus "No, I'll type it", or one button per choice plus "Something else".
 * Typing in the composer works just the same. */
function QuickReplies({ replies, onPick, onType }: { replies: string[]; onPick: (text: string) => void; onType: () => void }) {
  const yesNo = replies.length === 1;
  const chip =
    "rounded-full border px-3.5 py-1.5 text-[13.5px] leading-tight transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]";
  return (
    <div className="aa-replies mt-3 flex flex-wrap gap-2" role="group" aria-label="Quick replies">
      {replies.map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => onPick(r)}
          className={`${chip} border-[var(--accent)] bg-[var(--accent)]/[0.07] font-medium text-[var(--accent)] hover:bg-[var(--accent)] hover:text-white`}
        >
          {r}
        </button>
      ))}
      <button
        type="button"
        onClick={onType}
        className={`${chip} border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--text-tertiary)] hover:text-[var(--text-primary)]`}
      >
        {yesNo ? "No, I'll type it" : "Something else"}
      </button>
    </div>
  );
}


/** "Is this about <company>?" with one-click answers, for a question asked while that company is open. */
function CompanyAsk({ ask, disabled, latest, onAnswer }: {
  ask: NonNullable<AssistantMessage["ask"]>;
  disabled: boolean;
  /** Only the newest question can be answered; an older one was moved past. */
  latest: boolean;
  onAnswer: (answer: "yes" | "no" | "other") => void;
}) {
  const short = shortName(ask.companyName);
  const chip =
    "rounded-full border px-3.5 py-1.5 text-[13.5px] leading-tight transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] disabled:opacity-50";
  const picked = {
    yes: `Yes, ${ask.companyName}`,
    no: "No, all companies",
    other: "Another company",
  };
  return (
    <div className="border-l-2 border-[var(--accent)] pl-3">
      <p className="text-[14.5px] leading-relaxed text-[var(--text-primary)]">
        Is this about <span className="font-medium">{ask.companyName}</span>, the company you have open?
      </p>
      {ask.answered ? (
        <p className="mt-1.5 text-xs text-[var(--text-secondary)]">You picked: {picked[ask.answered]}</p>
      ) : !latest ? (
        <p className="mt-1.5 text-xs text-[var(--text-secondary)]">Not answered.</p>
      ) : (
        <div className="aa-replies mt-3 flex flex-wrap gap-2" role="group" aria-label="Which company">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onAnswer("yes")}
            className={`${chip} border-[var(--accent)] bg-[var(--accent)]/[0.07] font-medium text-[var(--accent)] hover:bg-[var(--accent)] hover:text-white`}
          >
            Yes, {short}
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onAnswer("no")}
            className={`${chip} border-[var(--border)] text-[var(--text-primary)] hover:border-[var(--accent)]`}
          >
            No, all companies
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onAnswer("other")}
            className={`${chip} border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--text-tertiary)] hover:text-[var(--text-primary)]`}
          >
            Another company
          </button>
        </div>
      )}
    </div>
  );
}
