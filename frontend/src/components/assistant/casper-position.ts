export const CASPER_SIZE = 72;
const MARGIN = 8;

export interface CasperPoint { x: number; y: number }
export interface CasperViewport { width: number; height: number; bottom: number }

export function clampCasper(point: CasperPoint, view: CasperViewport): CasperPoint {
  return {
    x: Math.max(MARGIN, Math.min(point.x, view.width - CASPER_SIZE - MARGIN)),
    y: Math.max(MARGIN, Math.min(point.y, view.height - CASPER_SIZE - view.bottom)),
  };
}

export function defaultCasper(view: CasperViewport): CasperPoint {
  const gap = view.width < 768 ? 20 : 24;
  return clampCasper({ x: view.width - CASPER_SIZE - gap, y: view.height - CASPER_SIZE - Math.max(gap, view.bottom) }, view);
}

export function casperFraction(point: CasperPoint, view: CasperViewport): CasperPoint {
  return {
    x: (point.x - MARGIN) / Math.max(1, view.width - CASPER_SIZE - MARGIN * 2),
    y: (point.y - MARGIN) / Math.max(1, view.height - CASPER_SIZE - view.bottom - MARGIN),
  };
}

export function restoreCasper(value: unknown, view: CasperViewport): CasperPoint {
  if (!value || typeof value !== "object" || !("x" in value) || !("y" in value)
    || typeof value.x !== "number" || typeof value.y !== "number"
    || !Number.isFinite(value.x) || !Number.isFinite(value.y)
    || value.x < 0 || value.x > 1 || value.y < 0 || value.y > 1) return defaultCasper(view);
  return clampCasper({
    x: MARGIN + value.x * Math.max(0, view.width - CASPER_SIZE - MARGIN * 2),
    y: MARGIN + value.y * Math.max(0, view.height - CASPER_SIZE - view.bottom - MARGIN),
  }, view);
}

/** Prefer above, then a roomy side. Constrain short-screen bubbles to scroll instead of covering Casper. */
export function placeCasperBubble(point: CasperPoint, view: CasperViewport, width: number, height: number) {
  const gap = 12;
  const above = point.y - gap - MARGIN;
  const below = view.height - view.bottom - point.y - CASPER_SIZE - gap;
  const right = view.width - point.x - CASPER_SIZE - gap - MARGIN;
  const left = point.x - gap - MARGIN;
  let side: "top" | "bottom" | "left" | "right" = "bottom";
  if (above < height) {
    if (right >= width) side = "left";
    else if (left >= width) side = "right";
    else side = below > above ? "top" : "bottom";
  }
  const vertical = side === "top" || side === "bottom";
  const maxHeight = Math.max(1, vertical ? (side === "bottom" ? above : below) : view.height - view.bottom - MARGIN);
  const actualHeight = Math.min(height, maxHeight);
  const x = vertical
    ? Math.max(MARGIN, Math.min(point.x + CASPER_SIZE / 2 - width / 2, view.width - width - MARGIN))
    : side === "left" ? point.x + CASPER_SIZE + gap : point.x - width - gap;
  const y = vertical
    ? side === "bottom" ? point.y - gap - actualHeight : point.y + CASPER_SIZE + gap
    : Math.max(MARGIN, Math.min(point.y + CASPER_SIZE / 2 - actualHeight / 2, view.height - view.bottom - actualHeight));
  const tail = vertical ? point.x + CASPER_SIZE / 2 - x : point.y + CASPER_SIZE / 2 - y;
  return { x, y, side, maxHeight, tail: Math.max(20, Math.min(tail, (vertical ? width : actualHeight) - 20)) };
}
