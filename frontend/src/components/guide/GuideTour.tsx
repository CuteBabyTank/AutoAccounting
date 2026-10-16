"use client";

import { useEffect, useId, useRef, useState, type ComponentType } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, ArrowRight, CheckCircle, Question, X } from "@phosphor-icons/react";

export interface Slide {
  id: string;
  title: string;
  body: string;
  points?: string[];
  Art: ComponentType;
}

interface Props {
  open: boolean;
  onClose: () => void;
  /** Shown above each slide title, e.g. "Documents". */
  label: string;
  slides: Slide[];
}

/** Step-by-step walkthrough: an illustration on the left, the explanation on the right. */
export default function GuideTour({ open, onClose, label, slides }: Props) {
  const [step, setStep] = useState(0);
  const dialog = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    setStep(0);
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.focus();
    return () => previous?.focus?.();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setStep((s) => Math.min(s + 1, slides.length - 1));
      if (e.key === "ArrowLeft") setStep((s) => Math.max(s - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, slides.length]);

  if (!open || typeof document === "undefined") return null;
  const slide = slides[step];
  const last = step === slides.length - 1;

  return createPortal(
    <div
      className="lp-skin overlay-enter fixed inset-0 z-[70] flex items-center justify-center bg-black/40 p-3 sm:p-6"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="gd-card modal-enter grid max-h-[calc(100dvh-1.5rem)] w-full max-w-[1020px] overflow-y-auto focus:outline-none md:grid-cols-[1.2fr_1fr]"
      >
        <div className="gd-stage min-h-[250px] px-4 py-8 sm:min-h-[340px] md:min-h-[500px]" aria-hidden="true">
          <slide.Art key={slide.id} />
        </div>

        <div className="flex flex-col p-6 sm:p-8">
          <div className="flex items-center gap-3">
            <p className="text-xs font-medium text-[var(--lp-accent)]">
              {label} guide <span className="text-[var(--lp-faint)]">· Step {step + 1} of {slides.length}</span>
            </p>
            <button
              onClick={onClose}
              aria-label="Close guide"
              className="-mr-2 ml-auto rounded-lg p-2 text-[var(--lp-muted)] hover:bg-[var(--lp-bg-gray)] hover:text-[var(--lp-text)]"
            >
              <X size={16} />
            </button>
          </div>

          <div key={slide.id} className="gd-in">
            <h2 id={titleId} className="mt-3 text-xl font-semibold tracking-tight text-[var(--lp-text)] sm:text-[22px]">
              {slide.title}
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-[var(--lp-muted)]">{slide.body}</p>
            {slide.points && (
              <ul className="mt-5 space-y-2.5">
                {slide.points.map((p) => (
                  <li key={p} className="flex gap-2.5 text-[13px] leading-relaxed text-[var(--lp-text)]">
                    <CheckCircle size={17} weight="fill" className="mt-0.5 shrink-0 text-[var(--lp-accent)]" />
                    <span>{p}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="mt-auto flex flex-wrap items-center gap-3 pt-8">
            <div className="flex items-center gap-1.5" role="tablist" aria-label="Guide steps">
              {slides.map((s, i) => (
                <button
                  key={s.id}
                  role="tab"
                  aria-selected={i === step}
                  aria-label={`Step ${i + 1}: ${s.title}`}
                  onClick={() => setStep(i)}
                  className={`h-1.5 rounded-full transition-all duration-300 ${
                    i === step ? "w-5 bg-[var(--lp-accent)]" : "w-1.5 bg-[var(--lp-border)] hover:bg-[var(--lp-faint)]"
                  }`}
                />
              ))}
            </div>
            <div className="ml-auto flex items-center gap-2">
              {step > 0 && (
                <button onClick={() => setStep(step - 1)} className="aa-ghost inline-flex items-center gap-1.5 !h-9">
                  <ArrowLeft size={14} /> Back
                </button>
              )}
              <button
                onClick={() => (last ? onClose() : setStep(step + 1))}
                className="inline-flex h-9 items-center gap-1.5 rounded-[10px] bg-[var(--lp-accent)] px-4 text-sm font-medium text-white hover:bg-[var(--lp-accent-hover)]"
              >
                {last ? "Done" : <>Next <ArrowRight size={14} /></>}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** Header button that reopens (or hides) a page's guide. */
export function GuideButton({ open, onClick, label = "How this works" }: { open: boolean; onClick: () => void; label?: string }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={open}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm ${
        open
          ? "border-[var(--accent)] bg-[var(--accent-subtle)] text-[var(--text-primary)]"
          : "border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
      }`}
    >
      <Question size={15} /> {label}
    </button>
  );
}
