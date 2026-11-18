"use client";

import { PencilSimple, Warning, XCircle } from "@phosphor-icons/react";
import { LEVEL_TEXT, LEVEL_WORD } from "@/lib/extract-flags";
import type { ExtractLevel } from "@/types/extract";

/** The level as a shape too (red: a crossed circle, yellow: a triangle), so it never rests on colour alone. */
export function FlagMark({ level, size = 12 }: { level: ExtractLevel; size?: number }) {
  const Icon = level === "red" ? XCircle : Warning;
  return (
    <span className={`inline-flex shrink-0 ${LEVEL_TEXT[level]}`}>
      <Icon size={size} weight="fill" aria-hidden />
      <span className="sr-only">{LEVEL_WORD[level]}</span>
    </span>
  );
}

/** A hand-edited cell. */
export function EditedMark() {
  return (
    <span className="inline-flex shrink-0 text-[var(--text-tertiary)]" title="Edited by hand">
      <PencilSimple size={11} aria-hidden />
      <span className="sr-only">Edited</span>
    </span>
  );
}
