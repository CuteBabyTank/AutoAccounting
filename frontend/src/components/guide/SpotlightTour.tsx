"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, ArrowRight, BookOpen, X } from "@phosphor-icons/react";

/** One stop on an on-screen tour. ``target`` is a ``data-tour`` value; without one the card sits in the middle. */
export interface Spot {
  target?: string;
  title: string;
  body: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  /** Shown above each title, e.g. "Documents". */
  label: string;
  spots: Spot[];
  /** Offered on the last stop: opens the illustrated walkthrough. */
  onMore?: () => void;
}

interface Box { top: number; left: number; width: number; height: number }

const PAD = 6;       // ring breathing room around the element
const GAP = 64;      // room for the connector between ring and card
const EDGE = 12;     // viewport margin
const CARD_W = 340;

/** The first element marked ``data-tour={name}`` that is actually on screen (the rail and the phone bar both carry some). */
function findTarget(name: string): HTMLElement | null {
  for (const el of document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`)) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && r.right > 0 && r.left < window.innerWidth && getComputedStyle(el).visibility !== "hidden") return el;
  }
  return null;
}

const available = (spots: Spot[]) => spots.filter((s) => !s.target || findTarget(s.target));

const same = (a: Box | null, b: Box | null) =>
  a === b || (!!a && !!b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height);

/** Ring, card and connector positions for a target box. */
function layout(ring: Box | null, cardH: number, vw: number, vh: number) {
  if (!ring) {
    const w = Math.min(CARD_W + 60, vw - EDGE * 2);
    return { card: { left: (vw - w) / 2, top: Math.max(EDGE, (vh - cardH) / 2), width: w }, wire: null };
  }
  const cx = ring.left + ring.width / 2;
  const cy = ring.top + ring.height / 2;
  const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));

  if (vw < 640) {
    // Phone: dock the card to whichever half the element isn't in.
    const below = cy < vh / 2;
    const top = below ? Math.max(EDGE, vh - cardH - EDGE) : EDGE;
    const tx = clamp(cx, EDGE + 24, vw - EDGE - 24);
    const wire = below
      ? { from: [cx, ring.top + ring.height], to: [tx, top], dir: "v" as const }
      : { from: [cx, ring.top], to: [tx, top + cardH], dir: "v" as const };
    // no wire when the card has to cover part of a tall element
    const fits = below ? ring.top + ring.height + 16 < top : top + cardH + 16 < ring.top;
    return { card: { left: EDGE, top, width: vw - EDGE * 2 }, wire: fits ? wire : null };
  }

  const room = { right: vw - ring.left - ring.width, left: ring.left, bottom: vh - ring.top - ring.height, top: ring.top };
  const side =
    room.right >= CARD_W + GAP + EDGE ? "right"
    : room.bottom >= cardH + GAP + EDGE ? "bottom"
    : room.left >= CARD_W + GAP + EDGE ? "left"
    : room.top >= cardH + GAP + EDGE ? "top"
    : "over";

  if (side === "right" || side === "left") {
    const left = side === "right" ? ring.left + ring.width + GAP : ring.left - GAP - CARD_W;
    const top = clamp(cy - cardH / 2, EDGE, vh - cardH - EDGE);
    const fromX = side === "right" ? ring.left + ring.width : ring.left;
    const toX = side === "right" ? left : left + CARD_W;
    return {
      card: { left, top, width: CARD_W },
      wire: { from: [fromX, cy], to: [toX, clamp(cy, top + 28, top + cardH - 28)], dir: "h" as const },
    };
  }
  if (side === "bottom" || side === "top") {
    const left = clamp(cx - CARD_W / 2, EDGE, vw - CARD_W - EDGE);
    const top = side === "bottom" ? ring.top + ring.height + GAP : ring.top - GAP - cardH;
    const tx = clamp(cx, left + 28, left + CARD_W - 28);
    return {
      card: { left, top, width: CARD_W },
      wire: side === "bottom"
        ? { from: [cx, ring.top + ring.height], to: [tx, top], dir: "v" as const }
        : { from: [cx, ring.top], to: [tx, top + cardH], dir: "v" as const },
    };
  }
  // The element fills the screen (a whole panel): float the card inside its lower right corner.
  return {
    card: {
      left: clamp(ring.left + ring.width - CARD_W - 24, EDGE, vw - CARD_W - EDGE),
      top: clamp(ring.top + ring.height - cardH - 24, EDGE, vh - cardH - EDGE),
      width: CARD_W,
    },
    wire: null,
  };
}

function wirePath({ from: [x1, y1], to: [x2, y2], dir }: { from: number[]; to: number[]; dir: "h" | "v" }) {
  if (dir === "h") {
    const mx = (x1 + x2) / 2;
    return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
  }
  const my = (y1 + y2) / 2;
  return `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`;
}

/**
 * On-screen walkthrough: dims the page, rings the real element and explains it in a card joined to it by the same
 * dashed wire the illustrations use. Stops whose element isn't on screen (a role can't see it, the data isn't there
 * yet, the phone layout hides it) are skipped.
 */
export default function SpotlightTour({ open, onClose, label, spots, onMore }: Props) {
  const [list, setList] = useState<Spot[] | null>(null);
  const [step, setStep] = useState(0);
  const [ring, setRing] = useState<Box | null>(null);
  const [view, setView] = useState({ w: 0, h: 0 });
  const [cardH, setCardH] = useState(220);
  const card = useRef<HTMLDivElement>(null);
  const titleId = useId();

  // Start once the page has settled (enter animation, first data).
  useEffect(() => {
    if (!open) {
      setList(null);
      return;
    }
    const previous = document.activeElement as HTMLElement | null;
    const t = window.setTimeout(() => {
      setList(available(spots));
      setStep(0);
    }, 350);
    return () => {
      window.clearTimeout(t);
      previous?.focus?.();
    };
  }, [open, spots]);

  const spot = list?.[step];

  // Moving re-checks what's on screen, so a checklist that loaded late still gets its stop.
  const go = useCallback(
    (delta: number) => {
      if (!list || !spot) return;
      const fresh = available(spots);
      const at = fresh.indexOf(spot);
      const next = (at < 0 ? step : at) + delta;
      if (next >= fresh.length) return onClose();
      setList(fresh);
      setStep(Math.max(0, next));
    },
    [list, spot, spots, step, onClose],
  );

  // Bring the element into view, then follow it (scrolling, resizing, the rail expanding).
  useEffect(() => {
    if (!spot) return;
    const el = spot.target ? findTarget(spot.target) : null;
    if (el) {
      const r = el.getBoundingClientRect();
      if (r.top < EDGE || r.bottom > window.innerHeight - EDGE) {
        const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        // a tall panel keeps what's above it in sight, so it's clear where on the page it is
        const margin = el.style.scrollMarginTop;
        el.style.scrollMarginTop = "96px";
        el.scrollIntoView({ block: r.height > window.innerHeight * 0.6 ? "start" : "center", behavior: smooth ? "smooth" : "auto" });
        el.style.scrollMarginTop = margin;
      }
    }
    let frame = 0;
    const tick = () => {
      const target = spot.target ? findTarget(spot.target) : null;
      let next: Box | null = null;
      if (target) {
        const r = target.getBoundingClientRect();
        // clip to the viewport so a tall panel still shows a ring on screen
        const top = Math.max(r.top - PAD, EDGE / 2);
        const bottom = Math.min(r.bottom + PAD, window.innerHeight - EDGE / 2);
        next = { top: Math.round(top), left: Math.round(r.left - PAD), width: Math.round(r.width + PAD * 2), height: Math.round(Math.max(bottom - top, 0)) };
      }
      setRing((prev) => (same(prev, next) ? prev : next));
      setView((v) => (v.w === window.innerWidth && v.h === window.innerHeight ? v : { w: window.innerWidth, h: window.innerHeight }));
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, [spot]);

  // The card's height decides where it fits; it changes with each stop's text.
  const shown = Boolean(spot) && view.w > 0;
  useLayoutEffect(() => {
    const el = card.current;
    if (!shown || !el) return;
    const measure = () => setCardH((prev) => (Math.abs(prev - el.offsetHeight) > 1 ? el.offsetHeight : prev));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [shown]);

  useEffect(() => {
    if (spot) card.current?.focus({ preventScroll: true });
  }, [spot]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") go(1);
      if (e.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, go]);

  if (!open || !list || !spot || typeof document === "undefined" || !view.w) return null;
  const last = step === list.length - 1;
  const { card: pos, wire } = layout(ring, cardH, view.w, view.h);

  return createPortal(
    <div className="lp-skin">
      {/* Swallows clicks so the tour can't be lost by clicking the page behind it. */}
      <div className="fixed inset-0 z-[70]" onMouseDown={(e) => e.preventDefault()} />
      {ring ? (
        <div
          aria-hidden="true"
          className="sp-ring pointer-events-none fixed z-[71] rounded-xl"
          style={{ top: ring.top, left: ring.left, width: ring.width, height: ring.height }}
        />
      ) : (
        <div aria-hidden="true" className="overlay-enter pointer-events-none fixed inset-0 z-[71] bg-[rgba(8,10,20,0.55)]" />
      )}
      {wire && (
        <svg aria-hidden="true" className="gd-wire pointer-events-none fixed inset-0 z-[72] !h-screen !w-screen">
          <path key={spot.title} className="sp-wire" d={wirePath(wire)} />
          <circle cx={wire.from[0]} cy={wire.from[1]} r={4} />
          <circle cx={wire.to[0]} cy={wire.to[1]} r={4} />
        </svg>
      )}
      <div
        ref={card}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="sp-card gd-card fixed z-[73] p-5 focus:outline-none"
        style={{ top: pos.top, left: pos.left, width: pos.width }}
      >
        <div className="flex items-center gap-3">
          <p className="text-xs font-medium text-[var(--lp-accent)]">
            {label} tour <span className="text-[var(--lp-faint)]">· {step + 1} of {list.length}</span>
          </p>
          <button
            onClick={onClose}
            aria-label="Close tour"
            className="-mr-2 ml-auto rounded-lg p-1.5 text-[var(--lp-muted)] hover:bg-[var(--lp-bg-gray)] hover:text-[var(--lp-text)]"
          >
            <X size={15} />
          </button>
        </div>
        <div key={spot.title} className="gd-in">
          <h2 id={titleId} className="mt-2 text-[17px] font-semibold tracking-tight text-[var(--lp-text)]">{spot.title}</h2>
          <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--lp-muted)]">{spot.body}</p>
        </div>
        {last && onMore && (
          <button
            onClick={() => {
              onClose();
              onMore();
            }}
            className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-[var(--lp-accent)] hover:underline"
          >
            <BookOpen size={15} /> See how it works, step by step
          </button>
        )}
        <div className="mt-5 flex items-center gap-2">
          {!last && (
            <button onClick={onClose} className="text-[13px] text-[var(--lp-muted)] hover:text-[var(--lp-text)]">
              Skip tour
            </button>
          )}
          <div className="ml-auto flex items-center gap-2">
            {step > 0 && (
              <button onClick={() => go(-1)} aria-label="Back" className="aa-ghost inline-flex items-center !h-8 !px-2.5">
                <ArrowLeft size={14} />
              </button>
            )}
            <button
              onClick={() => go(1)}
              className="inline-flex h-8 items-center gap-1.5 rounded-[10px] bg-[var(--lp-accent)] px-3.5 text-[13px] font-medium text-white hover:bg-[var(--lp-accent-hover)]"
            >
              {last ? "Got it" : step === 0 && !spot.target ? <>Show me <ArrowRight size={14} /></> : <>Next <ArrowRight size={14} /></>}
            </button>
          </div>
        </div>
        <div className="mt-4 flex gap-1" aria-hidden="true">
          {list.map((s, i) => (
            <span key={s.title} className={`h-1 flex-1 rounded-full transition-colors duration-300 ${i <= step ? "bg-[var(--lp-accent)]" : "bg-[var(--lp-border)]"}`} />
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}
