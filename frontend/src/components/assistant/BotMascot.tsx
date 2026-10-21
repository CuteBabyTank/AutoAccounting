"use client";

import { useEffect, useId, useState, type CSSProperties } from "react";
import { startBotIdle, type BotIdleScene } from "./bot-idle";

export type BotMascotState = "idle" | "thinking" | "done";

interface BotMascotProps {
  state: BotMascotState;
  size: number;
  playful?: boolean;
}

const STATES: BotMascotState[] = ["idle", "thinking", "done"];
const PIECES = [
  { x: 0, y: 36, color: "#36b8a8", cells: [[0, 0], [9, 0], [0, 9], [9, 9]] },
  { x: 18, y: 36, color: "#1e4b73", cells: [[0, 0], [0, 9], [9, 9], [18, 9]] },
  { x: 45, y: 36, color: "#79d9c8", cells: [[18, 0], [0, 9], [9, 9], [18, 9]] },
  { x: 27, y: 18, color: "#209e9a", cells: [[9, 0], [0, 9], [9, 9], [18, 9]] },
];

function GameBreak({ outcome }: { outcome: "win" | "lose" }) {
  const clip = useId();

  return (
    <svg className={`aa-bot-game aa-bot-game--${outcome}`} viewBox="0 0 256 256" fill="none" aria-hidden="true">
      <defs>
        <clipPath id={clip}>
          <path d="M92 86H146C164 86 178 100 178 119V140C178 154 168 165 153 165H86C72 165 61 155 61 140V119C61 100 73 86 92 86Z" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clip})`}>
        <path fill="#def9f0" d="M60 85h120v82H60z" />
        <svg x="65" y="87" width="108" height="77" viewBox="0 0 72 54" preserveAspectRatio="none">
          <g className="aa-bot-board">
            {PIECES.map((piece, i) => (
              <g key={i} transform={`translate(${piece.x} ${piece.y})`}>
                <g className="aa-bot-piece" style={{ "--aa-piece-delay": `${i * 950}ms` } as CSSProperties}>
                  {piece.cells.map(([x, y], j) => <rect key={j} x={x + 0.5} y={y + 0.5} width="8" height="8" rx="0.8" fill={piece.color} />)}
                </g>
              </g>
            ))}
            {outcome === "lose" && (
              <g className="aa-bot-topout" fill="#1e4b73">
                <path d="M0 9h18v9H9v9H0zM18 0h18v9h9v9H27V9h-9zM54 9h18v18h-9v-9h-9z" />
              </g>
            )}
          </g>
          {outcome === "win" && <rect className="aa-bot-line" y="45" width="72" height="9" fill="#fff" />}
        </svg>
        <g className="aa-bot-result" stroke="#1e4b73" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round">
          {outcome === "win" ? (
            <path d="m79 120 8-9 8 9m48 0 8-9 8 9m-54 21q14 17 28 0" />
          ) : (
            <path d="m80 111 15 15m0-15-15 15m63-15 15 15m0-15-15 15m-46 19q8-7 16 0t16 0" />
          )}
        </g>
      </g>
      <g className="aa-bot-controller" stroke="#1e4b73" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
        <path d="M85 186q-10-1-15 10l-7 15q-2 8 6 10l15-10h70l15 10q8-2 6-10l-7-15q-5-11-15-10Z" fill="#1e4b73" />
        <path d="M83 195v13m-6-6h12" stroke="#def9f0" />
        <circle cx="151" cy="198" r="3" fill="#79d9c8" stroke="none" />
        <circle cx="159" cy="206" r="3" fill="#79d9c8" stroke="none" />
        <path d="M64 199q-9-5-12 3t13 17q10 2 11-5t-12-15Zm111 0q9-5 12 3t-13 17q-10 2-11-5t12-15Z" fill="#fff" />
      </g>
      {outcome === "win" ? (
        <g className="aa-bot-sparkles" stroke="#36b8a8" strokeWidth="4" strokeLinecap="round">
          <path d="M43 67v16m-8-8h16m143-10v16m-8-8h16" />
        </g>
      ) : (
        <path className="aa-bot-sweat" d="M190 108q-12 16-5 21t12-4q2-6-7-17Z" fill="#79d9e2" stroke="#1e4b73" strokeWidth="2.5" />
      )}
    </svg>
  );
}

/** Each state crossfades as a pair; only the clipped head moves. */
export default function BotMascot({ state, size, playful = false }: BotMascotProps) {
  const [scene, setScene] = useState<BotIdleScene>("rest");
  const [paused, setPaused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(true);

  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(motion.matches);
    sync();
    motion.addEventListener("change", sync);
    return () => motion.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    setScene("rest");
    const idle = state === "idle" && playful && !reducedMotion ? startBotIdle(setScene) : null;
    const visibility = () => {
      setPaused(document.hidden);
      if (document.hidden) idle?.pause();
      else idle?.resume();
    };
    visibility();
    document.addEventListener("visibilitychange", visibility);
    return () => {
      idle?.stop();
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [state, playful, reducedMotion]);

  const activeScene = state === "idle" && playful && !reducedMotion ? scene : "rest";
  const game = activeScene === "win" || activeScene === "lose";

  return (
    <span className="aa-bot" data-state={state} data-scene={activeScene} data-paused={paused} style={{ width: size, height: size }} aria-hidden="true">
      {STATES.map((imageState) => (
        <span key={imageState} className="aa-bot-art" data-image-state={imageState} style={{ opacity: imageState === state ? 1 : 0 }}>
          {imageState !== "done" && (
            <svg className="aa-bot-neck" viewBox="0 0 256 256" fill="none" aria-hidden="true">
              {/* Hidden upper chest: the source helmet must not remain on the body. */}
              <path d="M50 150H188L194 175V186L190 202H48L44 186L45 175Z" fill={imageState === "idle" ? "#d7e7ec" : "#d4e6ec"} stroke={imageState === "idle" ? "#1a4d72" : "#044773"} strokeWidth="5" strokeLinejoin="round" />
            </svg>
          )}
          {["body", "head"].map((layer) => (
            // eslint-disable-next-line @next/next/no-img-element -- same-frame local art, clipped into overlapping layers
            <img key={layer} className={`aa-bot-image aa-bot-${layer}`} src={`/assistant/bot-${imageState}.png`} width={256} height={256} alt="" aria-hidden="true" draggable={false} />
          ))}
          {imageState === "done" && (
            // eslint-disable-next-line @next/next/no-img-element -- isolate the existing exclamation mark for its pulse
            <img className="aa-bot-image aa-bot-notification" src="/assistant/bot-done.png" width={256} height={256} alt="" aria-hidden="true" draggable={false} />
          )}
        </span>
      ))}
      {game && <GameBreak outcome={activeScene} />}
    </span>
  );
}
