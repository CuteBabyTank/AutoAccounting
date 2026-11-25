"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { CaretLeft, CaretRight, CornersIn, MagnifyingGlassMinus, MagnifyingGlassPlus } from "@phosphor-icons/react";
import { useAuth } from "@/lib/auth";
import { boxInShown, locate, type FieldKind, type Hint, type Rect } from "@/lib/field-locate";
import { wordsFor, type PageWords } from "@/lib/page-words";
import { drawnRect, toContainer, zoomFor } from "@/lib/viewer-geometry";

const MIN = 1; // 1 = the whole page fits
const MAX = 5;
const STEP = 0.25;
const CLICK_ZOOM = 2.5;
const ICON_BTN = "rounded-md p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-40";

const clamp = (z: number) => Math.min(MAX, Math.max(MIN, Math.round(z / STEP) * STEP));

/** One field the viewer can outline: its current value (boxes follow edits) and the reader's hint. */
export interface FieldTarget {
  key: string;
  value: string;
  kind: FieldKind;
  hint?: Hint;
}

/** Field boxes (lib/field-locate.ts): focusing a field outlines it on the scan and, with "Zoom to field" on, zooms
 *  to it; flagged fields are outlined amber. A box is drawn only once its page's image and words are in. */
export interface FieldBoxes {
  src: "accounting" | "extract";
  fileId: string;
  targets: FieldTarget[];
  active: string | null;
  flagged: string[];
  onBoxClick?: (key: string) => void;
}

interface Props {
  images: string[];
  /** The file page each image shows (defaults to firstPage, firstPage + 1, ...). */
  pageNumbers?: number[];
  fields?: FieldBoxes;
  /** The document's first page number in the file (for the page label). */
  firstPage: number;
  className?: string;
  /** The shown page's width ÷ height once it loads, so a parent can size the box to hug the page. */
  onAspect?: (ratio: number) => void;
}

/** A document's pages, one at a time, fitted to the box. Click to zoom in on a spot (click again to fit), or use the
 *  slider / buttons / trackpad pinch or Ctrl-scroll, always around the pointer (up to 500%); drag or scroll to move around when zoomed. */
export default function PageViewer({ images, firstPage, className = "", onAspect, pageNumbers, fields }: Props) {
  const [page, setPage] = useState(0);
  const [zoom, setZoomState] = useState(MIN);
  const { user } = useAuth();
  const userId = user?.id ?? "";
  const pageNo = (i: number) => pageNumbers?.[i] ?? firstPage + i;
  // Natural size of each shown image (by URL) and the words of each page (by file + page), once loaded.
  const [sizes, setSizes] = useState<Record<string, { w: number; h: number }>>({});
  const [words, setWords] = useState<Record<string, PageWords>>({});
  const [boxAspect, setBoxAspect] = useState(0);
  const [follow, setFollow] = useState(true);
  const followKey = `aa:zoom-field:${userId}`;
  const seeking = useRef<string | null>(null);   // the field just focused, until it has been zoomed to
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
  const currentNo = pageNo(page);
  const wordsKey = fields ? `${fields.fileId}:${currentNo}` : "";

  useEffect(() => {
    try {
      setFollow(localStorage.getItem(followKey) !== "off");
    } catch {
      // storage blocked: keep the default
    }
  }, [followKey]);

  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => el.clientHeight && setBoxAspect(el.clientWidth / el.clientHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // The shown page's words: only for a page that is open, once its image has loaded.
  const size = src ? sizes[src] : undefined;
  useEffect(() => {
    if (!fields || !src || !size || !userId || words[wordsKey]) return;
    const ctl = new AbortController();
    const key = wordsKey;
    wordsFor({ src: fields.src, fileId: fields.fileId, page: currentNo, userId, imageUrl: src, width: size.w,
      height: size.h, signal: ctl.signal })
      .then((got) => setWords((prev) => ({ ...prev, [key]: got })))
      .catch(() => undefined);   // no words, no boxes; the page still shows
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- words[wordsKey] is the guard, not an input
  }, [fields?.src, fields?.fileId, src, size, userId, wordsKey, currentNo]);

  // A focused field on another page (its hint says which): show that page first.
  const active = fields?.active ?? null;
  useEffect(() => {
    seeking.current = active;
    if (!fields || !active) return;
    const target = fields.targets.find((t) => t.key === active);
    const hintPage = target?.hint && "page" in target.hint ? target.hint.page : null;
    if (hintPage === null) return;
    const idx = images.findIndex((_, i) => pageNo(i) === hintPage);
    if (idx >= 0 && idx !== page) {
      setPage(idx);
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the focus moves
  }, [active]);

  // Boxes on the shown page, in container fractions. Nothing until both its image and its words are in.
  const pw = wordsKey ? words[wordsKey] : undefined;
  const boxes = useMemo(() => {
    const out: Record<string, Rect> = {};
    if (!fields || !pw || !size || !boxAspect) return out;
    const imageAspect = size.w / size.h;
    const drawn = drawnRect(boxAspect, imageAspect);
    for (const t of fields.targets) {
      if (t.key !== fields.active && !fields.flagged.includes(t.key)) continue;
      const r = locate(t.value, t.kind, pw.words, t.hint, currentNo);
      const shown = r && boxInShown(r, pw.crop, imageAspect, pw.aspect);
      if (shown) out[t.key] = toContainer(shown, drawn);
    }
    return out;
  }, [fields, pw, size, boxAspect, currentNo]);

  // Zoom to the focused field once its box is known (only once per focus).
  const activeBox = active ? boxes[active] : undefined;
  useEffect(() => {
    const el = box.current;
    if (!el || !activeBox || seeking.current !== active) return;
    seeking.current = null;
    if (!follow) return;
    const next = zoomFor(activeBox, { w: el.clientWidth, h: el.clientHeight, left: el.scrollLeft, top: el.scrollTop,
      zoom: zoomRef.current });
    if (!next) return;
    if (next.zoom === zoomRef.current) {
      el.scrollTo({ left: next.left, top: next.top, behavior: "smooth" });
      return;
    }
    pending.current = { left: next.left, top: next.top };
    zoomRef.current = next.zoom;
    setZoomState(next.zoom);
  }, [activeBox, active, follow]);

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
          <div className="relative" style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={src} alt={`Page ${currentNo}`} draggable={false}
              onLoad={(e) => {
                const { naturalWidth: w, naturalHeight: h } = e.currentTarget;
                if (w && h) {
                  onAspect?.(w / h);
                  const url = e.currentTarget.getAttribute("src") ?? "";
                  setSizes((prev) => (prev[url] ? prev : { ...prev, [url]: { w, h } }));
                }
              }}
              className="h-full w-full select-none object-contain" />
            {Object.entries(boxes).map(([key, r]) => (
              <button
                key={key}
                type="button"
                aria-label="Go to this field"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  fields?.onBoxClick?.(key);
                }}
                className={`absolute rounded-sm border-2 ${key === active
                  ? "border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_12%,transparent)]"
                  : "border-amber-500 bg-amber-400/10"}`}
                style={{ left: `${r[0] * 100}%`, top: `${r[1] * 100}%`, width: `${(r[2] - r[0]) * 100}%`,
                  height: `${(r[3] - r[1]) * 100}%`, zIndex: key === active ? 2 : 1 }}
              />
            ))}
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
            <span className="tabular-nums">Page {currentNo} of {pageNo(images.length - 1)}</span>
            <button className={ICON_BTN} aria-label="Next page" disabled={page >= images.length - 1}
              onClick={() => { setPage((p) => p + 1); reset(); }}>
              <CaretRight size={16} />
            </button>
          </span>
        )}
        {fields && (
          <label data-tour="zoom-to-field" className="flex cursor-pointer items-center gap-1.5"
            title="Clicking a field zooms the scan to where it is printed">
            <input type="checkbox" checked={follow} className="accent-[var(--accent)]"
              onChange={(e) => {
                setFollow(e.target.checked);
                try {
                  localStorage.setItem(followKey, e.target.checked ? "on" : "off");
                } catch {
                  // storage blocked: the choice lasts for this page only
                }
              }} />
            Zoom to field
          </label>
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
