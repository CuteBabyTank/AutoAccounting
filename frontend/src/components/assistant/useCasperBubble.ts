"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { casperDoneLine, type CasperNotice } from "./casper-lines";

type Bubble = { kind: "greeting" } | { kind: "notice"; text: string; id: string } | { kind: "menu" };

export default function useCasperBubble(open: boolean, notice: CasperNotice | null) {
  const [bubble, setBubble] = useState<Bubble | null>(null);
  const [leaving, setLeaving] = useState(false);
  const greeted = useRef(false);
  const handledNotice = useRef<string | null>(null);
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
    show({ kind: "greeting" });
  }, [open, show]);

  useEffect(() => {
    if (!notice || notice.id === handledNotice.current) return;
    handledNotice.current = notice.id;
    if (!open) show({ kind: "notice", id: notice.id, text: casperDoneLine(notice.kind) });
  }, [notice, open, show]);

  const noticeId = bubble?.kind === "notice" ? bubble.id : null;
  useEffect(() => {
    if (!noticeId) return;
    const timer = setTimeout(dismiss, 8000);
    return () => clearTimeout(timer);
  }, [noticeId, dismiss]);

  const greeting = bubble?.kind === "greeting";
  useEffect(() => {
    if (!greeting) return;
    const timer = setTimeout(dismiss, 12000);
    return () => clearTimeout(timer);
  }, [greeting, dismiss]);

  return { bubble, leaving, dismiss, showMenu: () => show({ kind: "menu" }) };
}
