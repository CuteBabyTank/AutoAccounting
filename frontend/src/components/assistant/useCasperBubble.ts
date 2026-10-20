"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CASPER_LINES, casperDoneLine, type CasperNotice } from "./casper-lines";

type Bubble = { kind: "greeting"; index: number } | { kind: "notice"; text: string; id: string } | { kind: "menu" };

export default function useCasperBubble(open: boolean, notice: CasperNotice | null, paused: boolean) {
  const [bubble, setBubble] = useState<Bubble | null>(null);
  const [leaving, setLeaving] = useState(false);
  const greeted = useRef(false);
  const handledNotice = useRef<string | null>(null);
  const remaining = useRef(45000);
  const exitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback((next: Bubble | null) => {
    if (exitTimer.current) clearTimeout(exitTimer.current);
    setLeaving(false);
    setBubble(next);
  }, []);
  const dismiss = useCallback(() => {
    setLeaving(true);
    if (exitTimer.current) clearTimeout(exitTimer.current);
    exitTimer.current = setTimeout(() => setBubble(null), 160);
  }, []);
  useEffect(() => () => { if (exitTimer.current) clearTimeout(exitTimer.current); }, []);

  useEffect(() => {
    if (open) { show(null); return; }
    if (greeted.current) return;
    greeted.current = true;
    try {
      if (sessionStorage.getItem("aa:casper:greeted")) return;
      sessionStorage.setItem("aa:casper:greeted", "1");
    } catch { /* The mounted launcher still greets only once if storage is blocked. */ }
    show({ kind: "greeting", index: 0 });
  }, [open, show]);

  useEffect(() => {
    if (!notice || notice.id === handledNotice.current) return;
    handledNotice.current = notice.id;
    if (!open) show({ kind: "notice", id: notice.id, text: casperDoneLine(notice.kind) });
  }, [notice, open, show]);

  const next = useCallback(() => {
    if (bubble?.kind !== "greeting") return;
    if (bubble.index === CASPER_LINES.length - 1) dismiss();
    else show({ kind: "greeting", index: bubble.index + 1 });
  }, [bubble, dismiss, show]);

  const noticeId = bubble?.kind === "notice" ? bubble.id : null;
  useEffect(() => {
    if (!noticeId) return;
    const timer = setTimeout(dismiss, 8000);
    return () => clearTimeout(timer);
  }, [noticeId, dismiss]);

  useEffect(() => {
    if (bubble?.kind !== "greeting" || paused || leaving) return;
    const started = Date.now();
    const timer = setTimeout(remaining.current <= 6000 ? dismiss : next, Math.min(6000, remaining.current));
    return () => {
      clearTimeout(timer);
      remaining.current -= Date.now() - started;
    };
  }, [bubble, paused, leaving, next, dismiss]);

  return { bubble, leaving, dismiss, next, showMenu: () => show({ kind: "menu" }) };
}
