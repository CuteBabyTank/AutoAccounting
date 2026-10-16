"use client";

import { useEffect, useRef } from "react";

/**
 * The homepage's flowing line ribbons, brought into the app, plus one soft
 * emerald glow. Ribbons live in the right gutter (a mask fades them out before
 * the content column) and are drawn in page coordinates against the scrolling
 * <main>, so scrolling reveals one continuous drawing. Time adds a slow drift.
 *
 * This is the background for every app page: AuthGate mounts it once inside
 * <main>, and public pages (login, pending) render it in their own `.lp` root.
 * It fills its positioned parent, behind content.
 */
type Ribbon = {
  base: number; amp: number; f: number; width: number; tf: number; ph: number; n: number;
  ink: "slate" | "emerald"; a: number;
};

const RIBBONS: Ribbon[] = [
  // base x (0–1), meander amplitude, spine frequency, band width, twist frequency, phase, lines, ink, alpha
  { base: 0.9, amp: 0.05, f: 0.0026, width: 0.09, tf: 0.0031, ph: 0.4, n: 36, ink: "slate", a: 0.24 },
  { base: 0.86, amp: 0.08, f: 0.0017, width: 0.07, tf: 0.0024, ph: 4.0, n: 30, ink: "emerald", a: 0.16 },
];

const INK = {
  light: { slate: [71, 85, 105], emerald: [5, 150, 105] },
  dark: { slate: [148, 163, 184], emerald: [52, 211, 153] },
} as const;

export default function AppFlow() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const g = canvas?.getContext("2d");
    if (!canvas || !g) return;
    const scroller = canvas.closest("main");
    // Gentler, never frozen, under reduced motion.
    const speed = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0.4 : 1;

    let w = 0, h = 0, t = 0, raf = 0, on = false;
    const size = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = () => {
      t += speed;
      const T = t * 0.004, top = scroller ? scroller.scrollTop : window.scrollY, step = 10;
      const palette = document.documentElement.classList.contains("dark") ? INK.dark : INK.light;
      g.clearRect(0, 0, w, h);
      g.lineWidth = 0.8;
      for (const r of RIBBONS) {
        const [cr, cg, cb] = palette[r.ink];
        for (let i = 0; i < r.n; i++) {
          const u = i / (r.n - 1) - 0.5;
          // Fainter toward one edge of the band, like light falling across it.
          g.strokeStyle = `rgba(${cr},${cg},${cb},${(r.a * (0.35 + 0.65 * (u + 0.5))).toFixed(3)})`;
          g.beginPath();
          for (let sy = -step; sy <= h + step; sy += step) {
            const y = top + sy;
            const spine = w * (r.base
              + r.amp * Math.sin(y * r.f + r.ph + T * 0.6)
              + r.amp * 0.35 * Math.sin(y * r.f * 2.3 - T * 0.4 + r.ph));
            const band = w * r.width * Math.sin(y * r.tf + r.ph * 1.7 + T * 0.35);
            const x = spine + u * band + w * 0.006 * Math.sin(y * 0.004 + u * 6 + T);
            if (sy < 0) g.moveTo(x, sy); else g.lineTo(x, sy);
          }
          g.stroke();
        }
      }
    };

    const loop = () => { draw(); if (on) raf = requestAnimationFrame(loop); };
    const go = () => { if (!on) { on = true; raf = requestAnimationFrame(loop); } };
    const halt = () => { on = false; cancelAnimationFrame(raf); };
    const onVisibility = () => (document.hidden ? halt() : go());

    size();
    go();
    const ro = new ResizeObserver(() => { size(); draw(); });
    ro.observe(canvas);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      halt();
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <div className="aa-flow" aria-hidden="true">
      <div className="aa-flow-view">
        <div className="aa-flow-glow" />
        <canvas ref={canvasRef} className="aa-flow-lines" />
      </div>
    </div>
  );
}
