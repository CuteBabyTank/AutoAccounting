"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { CaretLeft, CaretRight, CornersIn, MagnifyingGlassMinus, MagnifyingGlassPlus } from "@phosphor-icons/react";

const MIN = 1; // 1 = the whole page fits
const MAX = 5;
const STEP = 0.25;
const CLICK_ZOOM = 2.5;
const ICON_BTN = "rounded-md p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-40";

const clamp = (z: number) => Math.min(MAX, Math.max(MIN, Math.round(z / STEP) * STEP));

interface Props {
  images: string[];
  /** The document's first page number in the file (for the page label). */
  firstPage: number;
  className?: string;
}

/** A document's pages, one at a time, fitted to the box. Click to zoom in on a spot (click again to fit), or use the
 *  slider / buttons / Ctrl-scroll (up to 500%); drag or scroll to move around when zoomed. */
export default function PageViewer({ images, firstPage, className = "" }: Props) {
  const [page, setPage] = useState(0);
  const [zoom, setZoom] = useState(MIN);
  const box = useRef<HTMLDivElement>(null);
  const focus = useRef<{ fx: number; fy: number } | null>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number; moved: boolean } | null>(null);

  useEffect(() => {
    setPage(0);
    setZoom(MIN);
  }, [images]);

  // After a zoom change, keep the chosen point (click spot, or the centre) in the middle of the box.
  useLayoutEffect(() => {
    const el = box.current;
    const f = focus.current;
    if (!el || !f) return;
    el.scrollLeft = f.fx * el.scrollWidth - el.clientWidth / 2;
    el.scrollTop = f.fy * el.scrollHeight - el.clientHeight / 2;
    focus.current = null;
  }, [zoom]);

  function zoomTo(next: number, at?: { fx: number; fy: number }) {
    const el = box.current;
    const z = clamp(next);
    if (z === zoom) return;
    focus.current = at ?? (el ? {
      fx: (el.scrollLeft + el.clientWidth / 2) / el.scrollWidth,
      fy: (el.scrollTop + el.clientHeight / 2) / el.scrollHeight,
    } : { fx: 0.5, fy: 0.5 });
    setZoom(z);
  }

  function spot(e: React.MouseEvent): { fx: number; fy: number } {
    const el = box.current!;
    const r = el.getBoundingClientRect();
    return {
      fx: (el.scrollLeft + e.clientX - r.left) / el.scrollWidth,
      fy: (el.scrollTop + e.clientY - r.top) / el.scrollHeight,
    };
  }

  // Ctrl/Cmd + wheel zooms (a plain wheel still scrolls). Needs a non-passive listener to stop the page zooming.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const at = { fx: (el.scrollLeft + e.clientX - r.left) / el.scrollWidth, fy: (el.scrollTop + e.clientY - r.top) / el.scrollHeight };
      setZoom((z) => {
        const next = clamp(z + (e.deltaY < 0 ? STEP : -STEP));
        if (next !== z) focus.current = at;
        return next;
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const zoomed = zoom > MIN;
  const src = images[page];

  return (
    <div className={`flex min-h-0 flex-col ${className}`}>
      <div
        ref={box}
        className={`relative min-h-0 flex-1 overflow-auto rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] ${zoomed ? "cursor-grab active:cursor-grabbing" : "cursor-zoom-in"}`}
        onMouseDown={(e) => {
          if (!zoomed || e.button !== 0) return;
          const el = box.current!;
          drag.current = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop, moved: false };
        }}
        onMouseMove={(e) => {
          const d = drag.current;
          if (!d) return;
          const dx = e.clientX - d.x;
          const dy = e.clientY - d.y;
          if (Math.abs(dx) + Math.abs(dy) > 4) d.moved = true;
          box.current!.scrollLeft = d.left - dx;
          box.current!.scrollTop = d.top - dy;
        }}
        onMouseUp={() => {
          // keep the drag record until the click handler has seen it
          setTimeout(() => (drag.current = null), 0);
        }}
        onMouseLeave={() => (drag.current = null)}
        onClick={(e) => {
          if (drag.current?.moved) return; // that was a pan, not a click
          if (zoomed) zoomTo(MIN, { fx: 0.5, fy: 0.5 });
          else zoomTo(CLICK_ZOOM, spot(e));
        }}
        title={zoomed ? "Click to fit the page" : "Click to zoom in"}
      >
        {src ? (
          <div className="p-2" style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={src} alt={`Page ${firstPage + page}`} draggable={false}
              className="h-full w-full select-none object-contain" />
          </div>
        ) : (
          <div className="h-full min-h-40 animate-pulse" />
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--text-secondary)]">
        {images.length > 1 && (
          <span className="flex items-center gap-1">
            <button className={ICON_BTN} aria-label="Previous page" disabled={page === 0}
              onClick={() => { setPage((p) => p - 1); setZoom(MIN); }}>
              <CaretLeft size={16} />
            </button>
            <span className="tabular-nums">Page {firstPage + page} of {firstPage + images.length - 1}</span>
            <button className={ICON_BTN} aria-label="Next page" disabled={page >= images.length - 1}
              onClick={() => { setPage((p) => p + 1); setZoom(MIN); }}>
              <CaretRight size={16} />
            </button>
          </span>
        )}
        <span className="ml-auto flex items-center gap-1.5">
          <button className={ICON_BTN} aria-label="Zoom out" disabled={zoom <= MIN} onClick={() => zoomTo(zoom - STEP)}>
            <MagnifyingGlassMinus size={16} />
          </button>
          <input
            type="range"
            min={MIN}
            max={MAX}
            step={STEP}
            value={zoom}
            onChange={(e) => zoomTo(Number(e.target.value))}
            aria-label="Zoom"
            className="w-28 accent-[var(--accent)]"
          />
          <button className={ICON_BTN} aria-label="Zoom in" disabled={zoom >= MAX} onClick={() => zoomTo(zoom + STEP)}>
            <MagnifyingGlassPlus size={16} />
          </button>
          <span className="w-10 text-right tabular-nums">{zoomed ? `${Math.round(zoom * 100)}%` : "Fit"}</span>
          <button className={ICON_BTN} aria-label="Fit the page" disabled={!zoomed} onClick={() => zoomTo(MIN, { fx: 0.5, fy: 0.5 })}>
            <CornersIn size={16} />
          </button>
        </span>
      </div>
    </div>
  );
}
