import { describe, expect, it } from "vitest";
import { drawnRect, toContainer, zoomFor } from "./viewer-geometry";

describe("drawnRect", () => {
  it("letterboxes a tall page in a wide box", () => {
    const r = drawnRect(2, 0.5);   // box twice as wide as tall; page half as wide as tall
    [0.375, 0, 0.625, 1].forEach((v, i) => expect(r[i]).toBeCloseTo(v, 6));
  });
  it("letterboxes a wide page in a tall box", () => {
    const r = drawnRect(0.5, 2);
    [0, 0.375, 1, 0.625].forEach((v, i) => expect(r[i]).toBeCloseTo(v, 6));
  });
  it("maps image fractions into the container", () => {
    const got = toContainer([0.5, 0.5, 1, 1], [0.375, 0, 0.625, 1]);
    [0.5, 0.5, 0.625, 1].forEach((v, i) => expect(got[i]).toBeCloseTo(v, 6));
  });
});

describe("zoomFor", () => {
  const view = { w: 400, h: 600, left: 0, top: 0, zoom: 1 };
  it("makes the box about 40% of the view width and centres it", () => {
    const z = zoomFor([0.45, 0.5, 0.55, 0.52], view)!;
    expect(z.zoom).toBe(3);   // 0.4 / 0.1 = 4, clamped to 3
    expect(z.left).toBeCloseTo(0.5 * 3 * 400 - 200, 6);
    expect(z.top).toBeCloseTo(0.51 * 3 * 600 - 300, 6);
  });
  it("stays at least at fit and keeps scroll inside the page", () => {
    const z = zoomFor([0, 0, 0.9, 0.2], { ...view, zoom: 3, left: 500, top: 500 })!;
    expect(z.zoom).toBe(1);
    expect(z.left).toBe(0);
    expect(z.top).toBe(0);
  });
  it("leaves the view alone when the box is already in view at about the right zoom", () => {
    expect(zoomFor([0.45, 0.5, 0.55, 0.52], { ...view, zoom: 3, left: 400, top: 600 })).toBeNull();
  });
  it("limits the zoom so a tall box still fits", () => {
    // 40% width wants 4x, but a box half the page tall fits 60% of the view only at 1.2x: rounded down to the 0.25
    // zoom steps, 1x.
    expect(zoomFor([0.4, 0.1, 0.5, 0.6], { ...view, zoom: 3, left: 0, top: 0 })!.zoom).toBe(1);
    expect(zoomFor([0.4, 0.1, 0.5, 0.3], view)!.zoom).toBe(3);
  });
});
