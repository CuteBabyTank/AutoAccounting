"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { DotsThree } from "@phosphor-icons/react";
import BotMascot, { type BotMascotState } from "./BotMascot";
import CasperBubble from "./CasperBubble";
import { CASPER_LINES, type CasperNotice } from "./casper-lines";
import useDraggable from "./useDraggable";
import useCasperBubble from "./useCasperBubble";

interface CasperLauncherProps {
  open: boolean;
  state: BotMascotState;
  notice: CasperNotice | null;
  onOpen: () => void;
  onAsk: (question: string) => void;
}

export default function CasperLauncher({ open, state, notice, onOpen, onAsk }: CasperLauncherProps) {
  const drag = useDraggable();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const speech = useCasperBubble(open, notice, hovered || focused || drag.dragging);
  const { bubble } = speech;
  const cancelDrag = drag.cancel;
  useEffect(() => { if (open) cancelDrag(); }, [open, cancelDrag]);
  useEffect(() => {
    if (!bubble || open || drag.dragging) { setHovered(false); setFocused(false); }
  }, [bubble, open, drag.dragging]);

  if (open || !drag.layout) return null;
  const { point, view } = drag.layout;
  const line = bubble?.kind === "greeting" ? CASPER_LINES[bubble.index] : null;
  const openCasper = () => { speech.dismiss(); onOpen(); };
  const reset = () => { drag.reset(); speech.dismiss(); };

  return (
    <>
      <div className="aa-casper-anchor" style={{ left: point.x, top: point.y }} data-dragging={drag.dragging}>
        <button
          type="button"
          {...drag.handlers}
          onClick={() => { if (drag.allowClick()) openCasper(); }}
          onContextMenu={(e) => { e.preventDefault(); speech.showMenu(); }}
          aria-label="Open Casper, your assistant (Ctrl J)"
          title="Open Casper, your assistant (Ctrl J). Drag to move; Alt + arrow keys move 16px. Casper options: Reset position."
          data-tour="assistant"
          data-dragging={drag.dragging}
          className="aa-launcher aa-casper-launcher flex h-[72px] w-[72px] items-center justify-center rounded-full text-[var(--text-primary)]"
          style={{ "--casper-tilt": `${drag.tilt}deg` } as CSSProperties}
        >
          <span key={bubble?.kind === "notice" ? bubble.id : "rest"} className="aa-casper-lift" data-notice={bubble?.kind === "notice"}>
            <BotMascot state={state} size={72} playful={!drag.dragging} />
          </span>
        </button>
        <button type="button" className="aa-casper-options" aria-label="Casper options" title="Casper options and Reset position" onClick={speech.showMenu}>
          <DotsThree size={18} weight="bold" />
        </button>
      </div>
      {bubble && !drag.dragging && (
        <CasperBubble
          point={point} view={view}
          text={line?.text ?? (bubble.kind === "notice" ? bubble.text : "Need a little room? Drag me somewhere comfy, or send me back to my corner.")}
          index={bubble.kind === "greeting" ? bubble.index : undefined}
          notice={bubble.kind === "notice"} leaving={speech.leaving}
          onClose={speech.dismiss} onNext={speech.next} onReset={reset}
          onHover={setHovered} onFocus={setFocused}
          onAction={() => {
            if (bubble.kind === "notice") openCasper();
            else if (line?.question) { speech.dismiss(); onAsk(line.question); }
            else speech.next();
          }}
        />
      )}
    </>
  );
}
