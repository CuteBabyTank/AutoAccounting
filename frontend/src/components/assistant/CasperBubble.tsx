"use client";

import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { ArrowRight, ArrowCounterClockwise, X } from "@phosphor-icons/react";
import { CASPER_LINES } from "./casper-lines";
import { placeCasperBubble, type CasperPoint, type CasperViewport } from "./casper-position";

interface CasperBubbleProps {
  point: CasperPoint;
  view: CasperViewport;
  text: string;
  index?: number;
  notice: boolean;
  leaving: boolean;
  onNext: () => void;
  onAction: () => void;
  onClose: () => void;
  onReset: () => void;
  onHover: (hovered: boolean) => void;
  onFocus: (focused: boolean) => void;
}

export default function CasperBubble({ point, view, text, index, notice, leaving, onNext, onAction, onClose, onReset, onHover, onFocus }: CasperBubbleProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(180);
  const width = Math.min(view.width < 768 ? 228 : 260, view.width - 16);
  const place = placeCasperBubble(point, view, width, height);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setHeight(element.scrollHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text, width]);

  return (
    <div
      className="aa-casper-bubble"
      data-side={place.side}
      data-leaving={leaving}
      style={{ left: place.x, top: place.y, width, "--casper-tail": `${place.tail}px` } as CSSProperties}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      onFocusCapture={() => onFocus(true)}
      onBlurCapture={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) onFocus(false); }}
      onClick={(e) => { if (!(e.target as Element).closest("button")) onAction(); }}
    >
      <div ref={ref} className="aa-casper-bubble-content" style={{ maxHeight: place.maxHeight }}>
        <div className="aa-casper-bubble-heading">
          <span>Casper <span className="aa-casper-bubble-caption">{notice ? "has news" : index === undefined ? "at your service" : "says hello"}</span></span>
          <button type="button" onClick={onClose} aria-label="Close Casper's bubble" className="aa-casper-small-button"><X size={14} /></button>
        </div>
        <div aria-live="polite" aria-atomic="true">
          <button type="button" className="aa-casper-bubble-message" onClick={onAction}>
            {text}
            {(notice || (index !== undefined && CASPER_LINES[index].question)) && <ArrowRight size={14} className="inline-block ml-1 align-middle" />}
          </button>
        </div>
        <div className="aa-casper-bubble-footer">
          {index !== undefined && (
            <button type="button" onClick={onNext} aria-label={`Next Casper tip (${index + 1} of ${CASPER_LINES.length})`} className="aa-casper-dots">
              {CASPER_LINES.map((_, i) => <span key={i} data-active={i === index} />)}
            </button>
          )}
          <button type="button" className="aa-casper-reset" onClick={onReset}><ArrowCounterClockwise size={12} /> Reset position</button>
        </div>
      </div>
    </div>
  );
}
