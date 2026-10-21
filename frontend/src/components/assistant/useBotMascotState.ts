"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { BotMascotState } from "./BotMascot";

export default function useBotMascotState(busy: boolean) {
  const [settled, setSettled] = useState<BotMascotState>("idle");
  const [cancelled, setCancelled] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clear = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }, []);
  useEffect(() => clear, [clear]);

  const start = useCallback(() => {
    clear();
    setSettled("idle");
    setCancelled(false);
  }, [clear]);
  const reset = useCallback(() => {
    clear();
    setSettled("idle");
    setCancelled(true);
  }, [clear]);
  const finish = useCallback((success: boolean, doneMs = 2500) => {
    clear();
    setCancelled(true);
    setSettled(success ? "done" : "idle");
    if (success) timer.current = setTimeout(() => {
      timer.current = null;
      setSettled("idle");
    }, doneMs);
  }, [clear]);

  return { state: busy && !cancelled ? "thinking" as const : settled, start, finish, reset };
}
