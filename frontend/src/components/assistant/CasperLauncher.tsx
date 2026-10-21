"use client";

import { useEffect, useRef, type CSSProperties } from "react";
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
}

export default function CasperLauncher({ open, state, notice, onOpen }: CasperLauncherProps) {
  const speech = useCasperBubble(open, notice);
  const drag = useDraggable(speech.dismiss);
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { bubble } = speech;
  const cancelDrag = drag.cancel;
  useEffect(() => { if (open) cancelDrag(); }, [open, cancelDrag]);
  useEffect(() => {
    if (open && clickTimer.current) clearTimeout(clickTimer.current);
    return () => { if (clickTimer.current) clearTimeout(clickTimer.current); };
  }, [open]);

  if (open || !drag.layout) return null;
  const { point, view } = drag.layout;
  const openCasper = () => { speech.dismiss(); onOpen(); };
  const reset = () => { drag.reset(); speech.dismiss(); };
  const showOptions = () => {
    if (clickTimer.current) clearTimeout(clickTimer.current);
    speech.showMenu();
  };

  return (
    <>
      <div className="aa-casper-anchor" style={{ left: point.x, top: point.y }} data-dragging={drag.dragging}>
        <button
          type="button"
          {...drag.handlers}
          onClick={(e) => {
            if (!drag.allowClick()) return;
            if (clickTimer.current) clearTimeout(clickTimer.current);
            if (e.detail === 0) openCasper();
            else if (e.detail === 1) clickTimer.current = setTimeout(openCasper, 300);
          }}
          onDoubleClick={showOptions}
          onContextMenu={(e) => { e.preventDefault(); showOptions(); }}
          aria-label="Open Casper, your assistant (Ctrl J)"
          title="Open Casper, your assistant (Ctrl J). Drag to move; Alt + arrow keys move 16px. Double-click for Casper options: Reset position."
          data-tour="assistant"
          data-dragging={drag.dragging}
          className="aa-launcher aa-casper-launcher flex h-[72px] w-[72px] items-center justify-center rounded-full text-[var(--text-primary)]"
          style={{ "--casper-tilt": `${drag.tilt}deg` } as CSSProperties}
        >
          <span key={bubble?.kind === "notice" ? bubble.id : "rest"} className="aa-casper-lift" data-notice={bubble?.kind === "notice"}>
            <BotMascot state={state} size={72} playful={!drag.dragging} />
          </span>
        </button>
        <button type="button" className="aa-casper-options" aria-label="Casper options" title="Casper options and Reset position" onClick={showOptions}>
          <DotsThree size={18} weight="bold" />
        </button>
      </div>
      {bubble && (
        <CasperBubble
          point={point} view={view}
          text={bubble.kind === "greeting" ? CASPER_LINES[0].text : bubble.kind === "notice" ? bubble.text : "Need a little room? Drag me somewhere comfy, or send me back to my corner."}
          kind={bubble.kind} leaving={speech.leaving}
          onClose={speech.dismiss} onReset={reset}
          onAction={openCasper}
        />
      )}
    </>
  );
}
