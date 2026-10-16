"use client";

import { useEffect, useState, type CSSProperties, type ReactNode, type RefObject } from "react";

/* Building blocks for the guide illustrations. Everything here is decorative
   (the slide text carries the meaning), so the stage marks it aria-hidden. */

type El = RefObject<HTMLElement | null>;

/** Stagger index for the entrance animation. */
export const d = (i: number) => ({ "--d": i }) as CSSProperties;

/**
 * Dashed emerald wire from one element to another inside `box`, like the homepage's
 * source trail. Re-measures on resize and once entrance animations settle.
 */
export function Wire({ box, from, to, delay = 4, dir }: { box: El; from: El; to: El; delay?: number; dir?: "h" | "v" }) {
  const [geo, setGeo] = useState<{ path: string; a: [number, number]; b: [number, number] } | null>(null);

  // useEffect, not useLayoutEffect: the box ref sits on a parent, which React attaches after this child's layout effects.
  useEffect(() => {
    const root = box.current;
    if (!root) return;
    const measure = () => {
      const r = root.getBoundingClientRect();
      const fa = from.current?.getBoundingClientRect();
      const tb = to.current?.getBoundingClientRect();
      if (!fa || !tb || !root.offsetWidth) return;
      // The art is CSS-scaled on phones; convert screen pixels back to layout pixels.
      const k = r.width / root.offsetWidth;
      const local = (x: number, y: number): [number, number] => [(x - r.left) / k, (y - r.top) / k];
      const dx = tb.left + tb.width / 2 - (fa.left + fa.width / 2);
      const dy = tb.top + tb.height / 2 - (fa.top + fa.height / 2);
      let a: [number, number];
      let b: [number, number];
      let path: string;
      if (dir ? dir === "h" : Math.abs(dx) >= Math.abs(dy)) {
        a = local(dx > 0 ? fa.right + 5 : fa.left - 5, fa.top + fa.height / 2);
        b = local(dx > 0 ? tb.left : tb.right, tb.top + tb.height / 2);
        const mx = (a[0] + b[0]) / 2;
        path = `M${a[0]},${a[1]} C${mx},${a[1]} ${mx},${b[1]} ${b[0]},${b[1]}`;
      } else {
        a = local(fa.left + fa.width / 2, dy > 0 ? fa.bottom + 5 : fa.top - 5);
        b = local(tb.left + tb.width / 2, dy > 0 ? tb.top : tb.bottom);
        const my = (a[1] + b[1]) / 2;
        path = `M${a[0]},${a[1]} C${a[0]},${my} ${b[0]},${my} ${b[0]},${b[1]}`;
      }
      setGeo({ path, a, b });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    root.addEventListener("animationend", measure);
    // Crossing the phone breakpoint changes the scale but not the layout size.
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      root.removeEventListener("animationend", measure);
      window.removeEventListener("resize", measure);
    };
  }, [box, from, to, dir]);

  if (!geo) return null;
  return (
    <svg className="gd-wire gd-in" style={d(delay)}>
      <path d={geo.path} />
      <circle cx={geo.a[0]} cy={geo.a[1]} r={3.5} />
      <circle cx={geo.b[0]} cy={geo.b[1]} r={3.5} />
    </svg>
  );
}

const TONES = {
  green: "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]",
  blue: "bg-[var(--badge-blue-bg)] text-[var(--badge-blue-text)]",
  yellow: "bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]",
  gray: "bg-[var(--lp-bg-gray)] text-[var(--lp-muted)]",
  red: "bg-[var(--badge-red-bg)] text-[var(--badge-red-text)]",
};

export function Pill({ tone = "gray", children, className = "" }: { tone?: keyof typeof TONES; children: ReactNode; className?: string }) {
  return <span className={`gd-pill ${TONES[tone]} ${className}`}>{children}</span>;
}

/** Entry-style card: bold title, optional mono reference, then label/value rows. */
export function Card({ title, code, children, className = "", style }: { title?: ReactNode; code?: string; children: ReactNode; className?: string; style?: CSSProperties }) {
  return (
    <div className={`gd-card ${className}`} style={style}>
      {title && (
        <p className="gd-title">
          <span>{title}</span>
          {code && <small>{code}</small>}
        </p>
      )}
      {children}
    </div>
  );
}

export function Row({ k, v, on, warn, rowRef }: { k: ReactNode; v: ReactNode; on?: boolean; warn?: boolean; rowRef?: RefObject<HTMLDivElement | null> }) {
  return (
    <div ref={rowRef} className={`gd-row ${on ? "gd-row--on" : ""} ${warn ? "gd-row--warn" : ""}`}>
      <span>{k}</span>
      <span>{v}</span>
    </div>
  );
}

/** Two-column receipt line. */
export function Line({ l, r, bold }: { l: ReactNode; r: ReactNode; bold?: boolean }) {
  const Tag = bold ? "b" : "span";
  return (
    <div className="flex justify-between gap-2">
      <Tag>{l}</Tag>
      <Tag>{r}</Tag>
    </div>
  );
}
