/**
 * Calm indigo backdrop for signed-in app surfaces.
 *
 * Reuses the landing `.lp-page-*` layers but stays quiet — a faint
 * masked grid plus two soft, static colour blooms. No floating orbs,
 * rings or motion, so it sits comfortably behind dense data UI.
 *
 * Render once inside a `.lp` page root; it absolutely fills the parent
 * at z-index -1, so page content stays above it automatically.
 */
export default function AppBackdrop() {
  return (
    <div className="lp-page-bg" aria-hidden="true">
      <div className="lp-page-grid" />
      <div
        className="lp-bloom"
        style={{
          width: 520,
          height: 520,
          top: -180,
          right: -160,
          background: "radial-gradient(circle, var(--lp-glow) 0%, transparent 65%)",
        }}
      />
      <div
        className="lp-bloom"
        style={{
          width: 460,
          height: 460,
          bottom: -200,
          left: -140,
          background: "radial-gradient(circle, var(--lp-glow2) 0%, transparent 65%)",
        }}
      />
    </div>
  );
}
