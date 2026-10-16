"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Info } from "@phosphor-icons/react";

interface Props {
  children: ReactNode;
  /** Which way the bubble opens from the icon. */
  align?: "left" | "right" | "center";
  label?: string;
}

const WIDTH = 256;
const GUTTER = 12;

/** Small (i) that explains a term on hover or keyboard focus. The bubble is portaled so table and panel overflow can't clip it. */
export default function Hint({ children, align = "center", label = "What's this?" }: Props) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  const show = () => {
    const r = button.current?.getBoundingClientRect();
    if (!r) return;
    const wanted = align === "left" ? r.right - WIDTH : align === "right" ? r.left : r.left + r.width / 2 - WIDTH / 2;
    const left = Math.min(Math.max(wanted, GUTTER), window.innerWidth - WIDTH - GUTTER);
    setPos({ top: r.bottom + 6, left });
  };
  const hide = () => setPos(null);

  return (
    <span className="inline-flex align-middle">
      <button
        ref={button}
        type="button"
        aria-label={label}
        aria-describedby={pos ? id : undefined}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={(e) => {
          e.preventDefault();
          if (pos) hide();
          else show();
        }}
        onKeyDown={(e) => e.key === "Escape" && hide()}
        className="rounded-full p-0.5 text-[var(--text-tertiary)] hover:text-[var(--accent)] focus-visible:text-[var(--accent)]"
      >
        <Info size={14} />
      </button>
      {pos &&
        createPortal(
          <span
            id={id}
            role="tooltip"
            style={{ top: pos.top, left: pos.left, width: WIDTH }}
            className="lp-skin overlay-enter pointer-events-none fixed z-[60] rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-[var(--text-secondary)] shadow-lg"
          >
            {children}
          </span>,
          document.body,
        )}
    </span>
  );
}
