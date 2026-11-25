/** Field boxes in the page viewer (pure): where the fitted image is drawn inside its zoomed container, and how far
 *  to zoom and scroll so a field fills a comfortable part of the view. All rects are [x0, y0, x1, y1] fractions. */
import type { Rect } from "@/lib/field-locate";

const MAX_FIELD_ZOOM = 3;
const STEP = 0.25;
const WIDTH_SHARE = 0.4;    // the field ends up about this share of the view's width
const HEIGHT_SHARE = 0.6;   // ...unless it would be taller than this share of its height
const CLOSE_ENOUGH = 0.75;  // already zoomed to at least this share of the target: just move the outline

/** Where an image of `imageAspect` (w / h) is drawn with object-contain in a box of `boxAspect`. */
export function drawnRect(boxAspect: number, imageAspect: number): Rect {
  if (imageAspect >= boxAspect) {
    const h = boxAspect / imageAspect;
    return [0, (1 - h) / 2, 1, (1 + h) / 2];
  }
  const w = imageAspect / boxAspect;
  return [(1 - w) / 2, 0, (1 + w) / 2, 1];
}

/** A rect in image fractions as container fractions, given where the image is drawn. */
export function toContainer(r: Rect, drawn: Rect): Rect {
  const w = drawn[2] - drawn[0];
  const h = drawn[3] - drawn[1];
  return [drawn[0] + r[0] * w, drawn[1] + r[1] * h, drawn[0] + r[2] * w, drawn[1] + r[3] * h];
}

export interface View {
  /** The scroll box's size in pixels (the container is `zoom` × this). */
  w: number;
  h: number;
  left: number;
  top: number;
  zoom: number;
}

/** The zoom and scroll that centre `box` (container fractions), or null when it is already fully in view at
 *  about the right zoom (then only the outline moves). */
export function zoomFor(box: Rect, view: View): { zoom: number; left: number; top: number } | null {
  const bw = Math.max(box[2] - box[0], 1e-6);
  const bh = Math.max(box[3] - box[1], 1e-6);
  const want = Math.min(WIDTH_SHARE / bw, HEIGHT_SHARE / bh);
  const zoom = Math.min(MAX_FIELD_ZOOM, Math.max(1, Math.floor(want / STEP) * STEP));
  const px = (z: number) => [box[0] * z * view.w, box[1] * z * view.h, box[2] * z * view.w, box[3] * z * view.h];
  const [x0, y0, x1, y1] = px(view.zoom);
  const inView = x0 >= view.left && x1 <= view.left + view.w && y0 >= view.top && y1 <= view.top + view.h;
  if (inView && view.zoom >= zoom * CLOSE_ENOUGH) return null;
  const [a0, b0, a1, b1] = px(zoom);
  const fit = (v: number, size: number) => Math.min(Math.max(0, v), Math.max(0, size * zoom - size));
  return { zoom, left: fit((a0 + a1) / 2 - view.w / 2, view.w), top: fit((b0 + b1) / 2 - view.h / 2, view.h) };
}
