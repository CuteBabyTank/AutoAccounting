/**
 * The AutoAccounting "A" mark, tinted by CSS (`.aa-logo` in globals.css):
 * emerald #10B981 in both light and dark mode. The SVG file itself is the same
 * colour for places without the app's CSS (favicon, the static homepage).
 */
export default function LogoMark({ width, height, className = "" }: { width: number; height: number; className?: string }) {
  return <span aria-hidden="true" className={`aa-logo ${className}`} style={{ width, height }} />;
}
