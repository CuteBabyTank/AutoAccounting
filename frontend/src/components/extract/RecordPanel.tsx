"use client";

import { Fragment, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { CaretLeft, CaretRight, Check, Spinner, X } from "@phosphor-icons/react";
import PageViewer from "@/components/extract/PageViewer";
import { EditedMark, FlagMark } from "@/components/extract/FlagMark";
import { extractApi } from "@/lib/extract-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import {
  LEVEL_INPUT, LEVEL_TEXT, MAX_VALUE_CHARS, cellId, editedCells, firstCell, flagLine, flagSentence, flagsByCell, isNumeric,
  lowConfidence, pagesLabel, worst,
} from "@/lib/extract-flags";
import type { ExtractField, ExtractFlag, ExtractRecord, ExtractSnapshot } from "@/types/extract";

/** Saves one cell; resolves to an error message, or null when it went through. */
type Save = (key: string, row: number | null, value: string) => Promise<string | null>;
/** An input tells the panel whether it holds unsaved typing (`draft`) or a save on its way (`saving`). */
type Report = (id: string, draft: boolean, saving: boolean) => void;

interface Props {
  record: ExtractRecord;
  snapshot: ExtractSnapshot | undefined;
  number: number;
  fileName: string;
  /** A cell to focus on open (a flagged cell clicked in the table); `nonce` repeats a focus on the same cell. */
  focus: { cell: string | null; nonce: number };
  /** Phones: a full-screen sheet, so a modal dialog that takes focus. */
  modal: boolean;
  onClose: () => void;
  /** A save of this record started (before its reply) / failed. */
  onEditStart: (recordId: string) => void;
  onEditFailed: (recordId: string) => void;
  onSaved: (record: ExtractRecord) => void;
  /** True while any input has unsaved typing or a save in flight (the parent holds page reloads until false). */
  onBusy: (busy: boolean) => void;
  onPrev?: () => void;
  onNext?: () => void;
}

const LINES_NOTES = "lines-flags";
const ICON_BTN =
  "rounded-md border border-[var(--border)] p-1.5 text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-40 disabled:hover:bg-transparent";

/** One record: the page beside its fields and line table, every value editable (saved on blur / Enter). The parent
 *  keys it by record id, so its save queue and inputs start fresh per record. */
export default function RecordPanel({
  record, snapshot, number, fileName, focus, modal, onClose, onEditStart, onEditFailed, onSaved, onBusy, onPrev, onNext,
}: Props) {
  const root = useRef<HTMLElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const seq = useRef(0);
  const applied = useRef(0);
  const cb = useRef({ onEditStart, onEditFailed, onSaved, onBusy });
  useEffect(() => {
    cb.current = { onEditStart, onEditFailed, onSaved, onBusy };
  });

  // Which inputs hold unsaved typing / a save in flight; the parent hears only when "busy" flips.
  const drafts = useRef(new Set<string>());
  const saving = useRef(new Set<string>());
  const wasBusy = useRef(false);
  const report: Report = (id, draft, isSaving) => {
    if (draft) drafts.current.add(id);
    else drafts.current.delete(id);
    if (isSaving) saving.current.add(id);
    else saving.current.delete(id);
    const busy = drafts.current.size + saving.current.size > 0;
    if (busy !== wasBusy.current) {
      wasBusy.current = busy;
      cb.current.onBusy(busy);
    }
  };
  /** Someone is typing in another input (a failed save then leaves focus where it is). */
  const typingElsewhere = (id: string) => [...drafts.current].some((d) => d !== id);
  useEffect(() => () => {
    if (wasBusy.current) cb.current.onBusy(false);
  }, []);

  const fields = snapshot?.fields ?? [];
  const header = fields.filter((f) => f.scope === "header");
  const rowFields = fields.filter((f) => f.scope === "row");
  const byCell = flagsByCell(record);
  const edited = editedCells(record);
  const rows = record.values.rows ?? [];
  /** Flags about several lines (or lines plus a header total): told once under the grid, not under each line. */
  const spanning = record.flags.filter((fl) => flagLine(fl) === null && fl.cells?.some((c) => c.row !== null));

  // Saves run one at a time, so replies come back in order; the counter still drops any reply older than one
  // already shown.
  const save: Save = (key, row, value) => {
    cb.current.onEditStart(record.id);
    const next = chain.current.then(async () => {
      const mine = ++seq.current;
      try {
        const updated = await extractApi.editRecord(record.id, [{ key, row, value }]);
        if (mine > applied.current) {
          applied.current = mine;
          cb.current.onSaved(updated);
        } else cb.current.onEditFailed(record.id); // superseded: only ends the in-flight mark
        return null;
      } catch (e) {
        cb.current.onEditFailed(record.id);
        return apiErrorMessage(e, "Couldn't save this value");
      }
    });
    chain.current = next;
    return next;
  };

  const inputs = () => Array.from(root.current?.querySelectorAll<HTMLInputElement>("input[data-cell]") ?? []);
  const focusCell = (id: string) => {
    const el = inputs().find((i) => i.dataset.cell === id);
    if (!el) return;
    el.scrollIntoView({ block: "nearest" });
    el.focus();
  };
  const focusNext = (from: HTMLInputElement, step: 1 | -1) => {
    const list = inputs();
    const next = list[list.indexOf(from) + step];
    if (next) {
      next.focus();
      next.select();
    }
  };

  useEffect(() => {
    if (focus.cell) focusCell(focus.cell);
    // focusCell only reads the DOM; refocus when the asked-for cell (or its nonce) changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus.cell, focus.nonce]);

  // The sheet on phones takes focus when it opens (unless a cell was asked for).
  useEffect(() => {
    if (modal && !focus.cell) closeBtn.current?.focus();
    // only on open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      // A dialog above the panel (the workbook preview, a confirm) handles its own Escape.
      const above = Array.from(document.querySelectorAll('[aria-modal="true"]')).some((d) => d !== root.current);
      if (!above) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const confident = !lowConfidence(record);
  const level = worst(record.flags.map((f) => f.level));

  return (
    <aside
      ref={root}
      aria-label={`Record ${number}`}
      role={modal ? "dialog" : undefined}
      aria-modal={modal || undefined}
      className="@container fixed inset-x-0 bottom-0 top-14 z-30 flex flex-col bg-[var(--bg-primary)] md:sticky md:inset-auto md:top-4 md:z-auto md:h-[calc(100dvh-2rem)] md:rounded-xl md:border md:border-[var(--border)] md:bg-[var(--bg-secondary)]"
    >
      <div className="flex shrink-0 items-center gap-2 border-b border-[var(--border)] px-4 py-3">
        <div className="min-w-0 flex-1">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--text-primary)]">
            Record {number} {level && <FlagMark level={level} />}
          </h3>
          <p className="truncate text-xs text-[var(--text-secondary)]" title={fileName}>
            {fileName} · page {pagesLabel(record.page_start, record.page_end)}
          </p>
        </div>
        <button type="button" className={ICON_BTN} aria-label="Previous record" disabled={!onPrev} onClick={onPrev}>
          <CaretLeft size={14} />
        </button>
        <button type="button" className={ICON_BTN} aria-label="Next record" disabled={!onNext} onClick={onNext}>
          <CaretRight size={14} />
        </button>
        <button ref={closeBtn} type="button" className={ICON_BTN} aria-label="Close" onClick={onClose}>
          <X size={14} />
        </button>
      </div>

      {record.flags.length > 0 ? (
        <FlagList flags={record.flags} confident={confident} onPick={focusCell} />
      ) : (
        <p className="flex shrink-0 items-center gap-1.5 border-b border-[var(--border)] px-4 py-2 text-xs text-[var(--alert-success-text)]">
          <Check size={12} weight="bold" /> Every check passed.
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-4 @2xl:grid @2xl:grid-cols-2 @2xl:gap-4 @2xl:overflow-hidden">
        <div className="h-[55vh] @2xl:h-auto @2xl:min-h-0">
          <PageViewer fileId={record.file_id} start={record.page_start} end={record.page_end} />
        </div>
        <div className="mt-4 @2xl:mt-0 @2xl:min-h-0 @2xl:overflow-y-auto @2xl:pr-1">
          {header.length > 0 && (
            <div className="grid grid-cols-1 gap-3 @md:grid-cols-2 @2xl:grid-cols-1 @4xl:grid-cols-2">
              {header.map((f) => {
                const id = cellId(f.key, null);
                return (
                  <label key={f.key} className="block min-w-0">
                    <span className="mb-1 flex items-center gap-1 text-[11px] font-medium text-[var(--text-secondary)]">
                      {f.label} {edited.has(id) && <EditedMark />}
                    </span>
                    <CellInput id={id} field={f} row={null} value={record.values.header?.[f.key] ?? ""}
                      flags={byCell.get(id) ?? []} save={save} onStep={focusNext}
                      report={report} typingElsewhere={typingElsewhere} />
                  </label>
                );
              })}
            </div>
          )}
          {rowFields.length > 0 && (
            <div className="mt-5">
              <h4 className="mb-2 text-xs font-semibold text-[var(--text-primary)]">Lines ({rows.length})</h4>
              {rows.length === 0 ? (
                <p className="text-xs text-[var(--text-secondary)]">No lines were read on this document.</p>
              ) : (
                <div className="relative overflow-x-auto rounded-lg border border-[var(--border)]">
                  <table className="w-full border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-[var(--border)]">
                        <th className="sticky left-0 bg-[var(--bg-secondary)] px-2 py-1.5 text-left text-[11px] font-semibold text-[var(--text-secondary)]">#</th>
                        {rowFields.map((f) => (
                          <th key={f.key} className={`whitespace-nowrap px-2 py-1.5 text-[11px] font-semibold text-[var(--text-secondary)] ${isNumeric(f.type) ? "text-right" : "text-left"}`}>
                            {f.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r, i) => {
                        const rowFlags = record.flags.filter((fl) => flagLine(fl) === i);
                        const notesId = `line-${i}-flags`;
                        return (
                          <Fragment key={i}>
                            <tr className={`align-top ${rowFlags.length ? "" : "border-b border-[var(--border)] last:border-b-0"}`}>
                              <td className="sticky left-0 bg-[var(--bg-secondary)] px-2 py-1.5 text-xs tabular-nums text-[var(--text-secondary)]">{i + 1}</td>
                              {rowFields.map((f) => {
                                const id = cellId(f.key, i);
                                const inSpanning = spanning.some((fl) => fl.cells.some((c) => c.row === i && c.key === f.key));
                                const notes = [rowFlags.length ? notesId : "", inSpanning ? LINES_NOTES : ""].filter(Boolean).join(" ");
                                return (
                                  <td key={f.key} className="min-w-[8rem] px-1 py-1">
                                    <CellInput id={id} field={f} row={i} value={r?.[f.key] ?? ""} compact
                                      label={`${f.label}, line ${i + 1}`} edited={edited.has(id)}
                                      describedBy={notes || undefined}
                                      flags={byCell.get(id) ?? []} save={save} onStep={focusNext}
                      report={report} typingElsewhere={typingElsewhere} />
                                  </td>
                                );
                              })}
                            </tr>
                            {rowFlags.length > 0 && (
                              <tr className="border-b border-[var(--border)] last:border-b-0">
                                {/* One note per flag under its line (a grid cell is too narrow for the sentence). */}
                                <td colSpan={rowFields.length + 1} id={notesId} className="px-2 pb-1.5">
                                  <FlagNotes flags={rowFlags} />
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              {spanning.length > 0 && (
                // Checks across the lines (line totals = the header total): once, under the grid.
                <div id={LINES_NOTES} className="mt-1.5 space-y-0.5 px-1">
                  <FlagNotes flags={spanning} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

function FlagList({ flags, confident, onPick }: { flags: ExtractFlag[]; confident: boolean; onPick: (id: string) => void }) {
  return (
    <div className="max-h-40 shrink-0 overflow-y-auto border-b border-[var(--border)] px-4 py-2">
      {!confident && (
        <p className="mb-1.5 rounded-md border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] px-2 py-1 text-xs text-[var(--alert-warning-text)]">
          The reader was not sure about this document. Check every value against the page.
        </p>
      )}
      <ul className="space-y-0.5">
        {flags.map((flag, i) => {
          const cell = firstCell(flag);
          if (!cell) return null; // record-wide (the low-confidence note above)
          return (
            <li key={i}>
              <button type="button" onClick={() => onPick(cellId(cell.key, cell.row))}
                className="flex w-full items-start gap-1.5 rounded px-1 py-0.5 text-left text-xs text-[var(--text-primary)] hover:bg-[var(--bg-hover)]">
                <span className="mt-0.5"><FlagMark level={flag.level} /></span>
                <span>{flagSentence(flag)}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

type SaveState = "idle" | "saving" | "saved" | "error";

function CellInput({
  id, field, row, value, flags, save, onStep, report, typingElsewhere, compact = false, label, edited = false, describedBy,
}: {
  id: string;
  field: ExtractField;
  row: number | null;
  value: string;
  flags: ExtractFlag[];
  save: Save;
  onStep: (from: HTMLInputElement, step: 1 | -1) => void;
  report: Report;
  typingElsewhere: (id: string) => boolean;
  compact?: boolean;
  /** Grid cells have no visible label. */
  label?: string;
  edited?: boolean;
  /** Grid cells: the line's flag notes, shown under the line instead of under each cell. */
  describedBy?: string;
}) {
  // `draft` is what the person typed and hasn't been saved yet; null shows the stored value.
  const [draft, setDraft] = useState<string | null>(null);
  const [state, setState] = useState<SaveState>("idle");
  const [error, setError] = useState("");
  const sending = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const input = useRef<HTMLInputElement>(null);
  const reportRef = useRef(report);
  useEffect(() => {
    reportRef.current = report;
  });
  useEffect(() => {
    reportRef.current(id, draft !== null, state === "saving");
  }, [id, draft, state]);
  useEffect(() => () => reportRef.current(id, false, false), [id]);

  const level = worst(flags.map((f) => f.level));
  const numeric = isNumeric(field.type);
  const hintId = `${id}-hint`;

  const commit = async () => {
    if (draft === null) return;
    if (draft === value) {
      setDraft(null);
      setState("idle");
      setError("");
      return;
    }
    if (sending.current === draft) return; // this exact value is already on its way
    const text = draft;
    sending.current = text;
    clearTimeout(timer.current);
    setState("saving");
    setError("");
    const problem = await save(field.key, row, text);
    sending.current = null;
    if (problem) {
      // Keep what was typed: blur or Enter tries again. Enter already moved focus on; bring it back to the value that
      // failed unless the person has started typing in another box.
      setState("error");
      setError(problem);
      if (input.current && !typingElsewhere(id)) input.current.focus();
      return;
    }
    setDraft((d) => (d === text ? null : d));
    setState("saved");
    timer.current = setTimeout(() => setState((s) => (s === "saved" ? "idle" : s)), 1500);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void commit();
      onStep(e.currentTarget, e.shiftKey ? -1 : 1);
    } else if (e.key === "Escape" && draft !== null && state !== "saving") {
      e.preventDefault(); // undo the typing instead of closing the panel
      setDraft(null);
      setState("idle");
      setError("");
    }
  };

  return (
    <div className="min-w-0">
      <div className="relative flex items-center gap-1">
        <input
          ref={input}
          data-cell={id}
          value={draft ?? value}
          maxLength={MAX_VALUE_CHARS}
          inputMode={numeric ? "decimal" : undefined}
          aria-label={label}
          aria-invalid={level === "red" || state === "error" || undefined}
          aria-describedby={[describedBy, (level && !compact) || error ? hintId : ""].filter(Boolean).join(" ") || undefined}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commit()}
          onKeyDown={onKeyDown}
          className={`w-full rounded-md border border-[var(--border)] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none ${
            compact ? "px-2 py-1 text-xs" : "px-2.5 py-1.5 text-sm"
          } ${numeric ? "text-right tabular-nums" : ""} ${field.type === "money" ? "aa-amount" : ""} ${level ? LEVEL_INPUT[level] : "bg-[var(--input-bg)]"} ${
            state === "error" ? "!border-[var(--error)]" : ""
          } pr-7`}
        />
        <span className="pointer-events-none absolute right-2 flex items-center" aria-live="polite">
          {state === "saving" && <Spinner size={12} className="animate-spin text-[var(--text-secondary)]" aria-label="Saving" />}
          {state === "saved" && <Check size={12} weight="bold" className="text-[var(--alert-success-text)]" aria-label="Saved" />}
          {state === "idle" && compact && edited && <EditedMark />}
        </span>
      </div>
      {((!compact && flags.length > 0) || error) && (
        <div id={hintId} className="mt-0.5 space-y-0.5">
          {!compact && <FlagNotes flags={flags} />}
          {error && (
            <p className="text-[11px] leading-snug text-[var(--alert-error-text)]">
              {error} Press Enter to try again.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function FlagNotes({ flags }: { flags: ExtractFlag[] }) {
  return (
    <>
      {flags.map((f, i) => (
        <p key={i} className={`flex items-start gap-1 text-[11px] leading-snug ${LEVEL_TEXT[f.level]}`}>
          <span className="mt-px"><FlagMark level={f.level} size={10} /></span>
          <span>{f.message}</span>
        </p>
      ))}
    </>
  );
}
