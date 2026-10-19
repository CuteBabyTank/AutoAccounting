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
 *  slider / buttons / trackpad pinch or Ctrl-scroll, always around the pointer (up to 500%); drag or scroll to move around when zoomed. */
export default function PageViewer({ images, firstPage, className = "" }: Props) {
  const [page, setPage] = useState(0);
  const [zoom, setZoomState] = useState(MIN);
  const box = useRef<HTMLDivElement>(null);
  const zoomRef = useRef(MIN);
  // The scroll position the next render must land on, so the point under the pointer stays under it.
  const pending = useRef<{ left: number; top: number } | null>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number; moved: boolean } | null>(null);

  function reset() {
    pending.current = null;
    zoomRef.current = MIN;
    setZoomState(MIN);
  }

  useEffect(() => {
    setPage(0);
    reset();
  }, [images]);

  useLayoutEffect(() => {
    const el = box.current;
    const p = pending.current;
    if (!el || !p) return;
    el.scrollLeft = p.left;
    el.scrollTop = p.top;
    pending.current = null;
  }, [zoom]);

  /** Zoom to ``next`` keeping the point at (ox, oy) in the box (pixels from its top-left; the centre when left out)
   *  fixed on screen. The page's size is exactly ``zoom`` × the box, so scroll positions scale by the zoom ratio. */
  function zoomAt(next: number, ox?: number, oy?: number, snap = true) {
    const el = box.current;
    const old = zoomRef.current;
    const z = snap ? clamp(next) : Math.min(MAX, Math.max(MIN, next));
    if (!el || z === old) return;
    const x = ox ?? el.clientWidth / 2;
    const y = oy ?? el.clientHeight / 2;
    const left = pending.current?.left ?? el.scrollLeft;
    const top = pending.current?.top ?? el.scrollTop;
    const k = z / old;
    pending.current = { left: (left + x) * k - x, top: (top + y) * k - y };
    zoomRef.current = z;
    setZoomState(z);
  }

  function offset(e: { clientX: number; clientY: number }): [number, number] {
    const r = box.current!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }

  // Trackpad pinch (Chrome / Firefox send it as Ctrl + wheel) and Ctrl/Cmd + wheel zoom smoothly around the pointer;
  // a plain wheel or two-finger swipe still scrolls. Safari sends pinches as gesture events instead.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const delta = Math.max(-50, Math.min(50, e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY));
      zoomAt(zoomRef.current * Math.exp(-delta * 0.01), ...offset(e), false);
    };
    let base = MIN;
    const onGestureStart = (e: Event) => {
      e.preventDefault();
      base = zoomRef.current;
    };
    const onGestureChange = (e: Event) => {
      e.preventDefault();
      const g = e as Event & { scale: number; clientX: number; clientY: number };
      zoomAt(base * g.scale, ...offset(g), false);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("gesturestart", onGestureStart);
    el.addEventListener("gesturechange", onGestureChange);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("gesturestart", onGestureStart);
      el.removeEventListener("gesturechange", onGestureChange);
    };
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
          if (zoomed) zoomAt(MIN);
          else zoomAt(CLICK_ZOOM, ...offset(e));
        }}
        title={zoomed ? "Click to fit the page" : "Click to zoom in"}
      >
        {src ? (
          <div style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }}>
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
              onClick={() => { setPage((p) => p - 1); reset(); }}>
              <CaretLeft size={16} />
            </button>
            <span className="tabular-nums">Page {firstPage + page} of {firstPage + images.length - 1}</span>
            <button className={ICON_BTN} aria-label="Next page" disabled={page >= images.length - 1}
              onClick={() => { setPage((p) => p + 1); reset(); }}>
              <CaretRight size={16} />
            </button>
          </span>
        )}
        <span className="ml-auto flex items-center gap-1.5">
          <button className={ICON_BTN} aria-label="Zoom out" disabled={zoom <= MIN} onClick={() => zoomAt(zoom - STEP)}>
            <MagnifyingGlassMinus size={16} />
          </button>
          <input
            type="range"
            min={MIN}
            max={MAX}
            step={STEP}
            value={zoom}
            onChange={(e) => zoomAt(Number(e.target.value))}
            aria-label="Zoom"
            className="w-28 accent-[var(--accent)]"
          />
          <button className={ICON_BTN} aria-label="Zoom in" disabled={zoom >= MAX} onClick={() => zoomAt(zoom + STEP)}>
            <MagnifyingGlassPlus size={16} />
          </button>
          <span className="w-10 text-right tabular-nums">{zoomed ? `${Math.round(zoom * 100)}%` : "Fit"}</span>
          <button className={ICON_BTN} aria-label="Fit the page" disabled={!zoomed} onClick={() => zoomAt(MIN)}>
            <CornersIn size={16} />
          </button>
        </span>
      </div>
    </div>
  );
}
