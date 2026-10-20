"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent, type KeyboardEvent } from "react";
import { casperFraction, clampCasper, defaultCasper, restoreCasper, type CasperPoint, type CasperViewport } from "./casper-position";

const POSITION_KEY = "aa:casper:pos";
const viewport = (): CasperViewport => ({
  width: document.documentElement.clientWidth,
  height: window.innerHeight,
  // Leave the phone's navigation / safe area reachable, even after a drag.
  bottom: window.innerWidth < 768 ? 80 : 8,
});

export default function useDraggable(onMove: () => void) {
  const [layout, setLayout] = useState<{ point: CasperPoint; view: CasperViewport } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [tilt, setTilt] = useState(0);
  const current = useRef(layout);
  const fraction = useRef<unknown>(null);
  const gesture = useRef<{ id: number; x: number; y: number; point: CasperPoint; lastX: number; lastAt: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);

  const move = useCallback((point: CasperPoint, persist = false) => {
    const view = viewport();
    const next = { point: clampCasper(point, view), view };
    current.current = next;
    fraction.current = casperFraction(next.point, view);
    setLayout(next);
    if (persist) {
      try { localStorage.setItem(POSITION_KEY, JSON.stringify(fraction.current)); } catch { /* Dragging works without storage. */ }
    }
  }, []);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(POSITION_KEY);
      const legacy = saved === null ? localStorage.getItem("aa:buddy:pos") : null;
      fraction.current = JSON.parse(saved ?? legacy ?? "null");
      if (legacy !== null) localStorage.setItem(POSITION_KEY, legacy);
    } catch { /* Use the default corner if the saved position cannot be read. */ }
    const resize = () => {
      const view = viewport();
      const next = { point: restoreCasper(fraction.current, view), view };
      current.current = next;
      setLayout(next);
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  useEffect(() => {
    if (!dragging) return;
    const previous = document.body.style.userSelect;
    document.body.style.userSelect = "none";
    return () => { document.body.style.userSelect = previous; };
  }, [dragging]);

  const cancel = useCallback(() => {
    const drag = gesture.current;
    if (!drag) return;
    suppressClick.current = drag.moved;
    gesture.current = null;
    setDragging(false);
    setTilt(0);
    if (drag.moved && current.current) move(current.current.point, true);
  }, [move]);

  const finish = (e: PointerEvent<HTMLButtonElement>) => {
    if (gesture.current?.id !== e.pointerId) return;
    cancel();
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  };

  return {
    layout, dragging, tilt, cancel,
    reset: () => {
      fraction.current = null;
      const view = viewport();
      const next = { point: defaultCasper(view), view };
      current.current = next;
      setLayout(next);
      try { localStorage.setItem(POSITION_KEY, "null"); } catch { /* This visit still resets. */ }
    },
    handlers: {
      onPointerDown: (e: PointerEvent<HTMLButtonElement>) => {
        if (!e.isPrimary || e.button !== 0 || !current.current) return;
        suppressClick.current = false;
        gesture.current = { id: e.pointerId, x: e.clientX, y: e.clientY, point: current.current.point, lastX: e.clientX, lastAt: e.timeStamp, moved: false };
        e.currentTarget.setPointerCapture(e.pointerId);
      },
      onPointerMove: (e: PointerEvent<HTMLButtonElement>) => {
        const drag = gesture.current;
        if (!drag || drag.id !== e.pointerId) return;
        const dx = e.clientX - drag.x;
        const dy = e.clientY - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) < 5) return;
        if (!drag.moved) {
          drag.moved = true;
          onMove();
        }
        setDragging(true);
        setTilt(Math.max(-9, Math.min(9, (e.clientX - drag.lastX) / Math.max(1, e.timeStamp - drag.lastAt) * 8)));
        drag.lastX = e.clientX;
        drag.lastAt = e.timeStamp;
        move({ x: drag.point.x + dx, y: drag.point.y + dy });
      },
      onPointerUp: finish,
      onPointerCancel: finish,
      onLostPointerCapture: finish,
      onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => {
        // A previous drag must never suppress keyboard activation.
        if (e.key === "Enter" || e.key === " ") suppressClick.current = false;
        if (!e.altKey || !current.current) return;
        const delta: Record<string, CasperPoint> = {
          ArrowLeft: { x: -16, y: 0 }, ArrowRight: { x: 16, y: 0 },
          ArrowUp: { x: 0, y: -16 }, ArrowDown: { x: 0, y: 16 },
        };
        const step = delta[e.key];
        if (!step) return;
        e.preventDefault();
        onMove();
        move({ x: current.current.point.x + step.x, y: current.current.point.y + step.y }, true);
      },
    },
    allowClick: () => {
      const allowed = !suppressClick.current;
      suppressClick.current = false;
      return allowed;
    },
  };
}
