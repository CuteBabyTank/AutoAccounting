"use client";

import { useState, type FocusEvent, type HTMLAttributes, type KeyboardEvent, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { CaretLeft, CaretRight, FileXls, Spinner } from "@phosphor-icons/react";
import { EditedMark, FlagMark } from "@/components/extract/FlagMark";
import {
  LEVEL_CELL, PAGE_SIZE, cellId, displayValue, flagSentence, editedCells, flagsByCell, isNumeric, lowConfidence, pagesLabel, plural,
  rangeLabel, recordWideFlags, rowsLevel, worst,
} from "@/lib/extract-flags";
import type { ExtractField, ExtractFormatCount, ExtractLevel, ExtractRecord, ExtractSnapshot } from "@/types/extract";

/** One format's current page of records (RunTable loads it). */
export interface RecordPage {
  offset: number;
  total: number;
  records: ExtractRecord[];
  loading: boolean;
  error: string;
}

interface Props {
  count: ExtractFormatCount;
  snapshot: ExtractSnapshot | undefined;
  /** Several formats in the run: each table shows its format's name. */
  showName: boolean;
  page: RecordPage | undefined;
  reviewOnly: boolean;
  fileNames: Map<string, string>;
  openId: string | null;
  onOpen: (record: ExtractRecord, cell: string | null) => void;
  onPage: (offset: number) => void;
  onRetry: () => void;
  onDownload: () => void;
}

interface Tip {
  lines: string[];
  level: ExtractLevel;
  x: number;
  y: number;
  above: boolean;
}

type TipProps = (lines: string[], level: ExtractLevel | null) =>
  Pick<HTMLAttributes<HTMLElement>, "tabIndex" | "onMouseEnter" | "onMouseLeave" | "onFocus" | "onBlur">;

const BTN =
  "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50 disabled:hover:bg-transparent";
const TH = "whitespace-nowrap px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]";
const TD = "px-3 py-2 align-top focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--accent)]";

/** One format's records: a table with flagged cells tinted, a pager, and its own Excel download. */
export default function RecordsTable({
  count, snapshot, showName, page, reviewOnly, fileNames, openId, onOpen, onPage, onRetry, onDownload,
}: Props) {
  const [tip, setTip] = useState<Tip | null>(null);
  const header = (snapshot?.fields ?? []).filter((f) => f.scope === "header");
  const hasRows = (snapshot?.fields ?? []).some((f) => f.scope === "row");
  const review = count.red + count.yellow;
  const records = page?.records ?? [];

  const showTip = (el: HTMLElement, lines: string[], level: ExtractLevel) => {
    const r = el.getBoundingClientRect();
    const above = r.bottom + 120 > window.innerHeight;
    setTip({ lines, level, x: Math.min(r.left, window.innerWidth - 300), y: above ? r.top - 4 : r.bottom + 4, above });
  };
  const tipProps: TipProps = (lines, level) =>
    level && lines.length
      ? {
          tabIndex: 0,
          onMouseEnter: (e: MouseEvent<HTMLElement>) => showTip(e.currentTarget, lines, level),
          onMouseLeave: () => setTip(null),
          onFocus: (e: FocusEvent<HTMLElement>) => showTip(e.currentTarget, lines, level),
          onBlur: () => setTip(null),
        }
      : {};

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
        <div className="min-w-0 flex-1">
          {showName && <h3 className="truncate text-sm font-semibold text-[var(--text-primary)]">{count.name}</h3>}
          <p className="flex flex-wrap items-center gap-x-2 text-xs text-[var(--text-secondary)]">
            <span>{plural(count.records, "record")}</span>
            {review > 0 ? (
              <>
                <span>· {review} need review</span>
                {count.red > 0 && (
                  <span className="inline-flex items-center gap-1"><FlagMark level="red" /> {count.red} red</span>
                )}
                {count.yellow > 0 && (
                  <span className="inline-flex items-center gap-1"><FlagMark level="yellow" /> {count.yellow} yellow</span>
                )}
              </>
            ) : (
              count.records > 0 && <span>· all checks passed</span>
            )}
          </p>
        </div>
        <button type="button" className={BTN} disabled={count.records === 0} onClick={onDownload}>
          <FileXls size={16} /> Download Excel
        </button>
      </div>

      {page?.error ? (
        <p className="border-t border-[var(--border)] px-4 py-4 text-sm text-[var(--alert-error-text)]">
          {page.error}{" "}
          <button type="button" onClick={onRetry} className="font-medium underline">Retry</button>
        </p>
      ) : !page || (page.loading && records.length === 0) ? (
        <p className="flex items-center gap-2 border-t border-[var(--border)] px-4 py-4 text-sm text-[var(--text-secondary)]">
          <Spinner size={14} className="animate-spin" /> Loading records
        </p>
      ) : records.length === 0 ? (
        <p className="border-t border-[var(--border)] px-4 py-6 text-center text-sm text-[var(--text-secondary)]">
          {reviewOnly ? "Nothing here needs review." : "No records yet."}
        </p>
      ) : (
        <div className="relative overflow-x-auto border-t border-[var(--border)]" onScroll={() => setTip(null)}>
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className={`${TH} sticky left-0 z-[2] bg-[var(--bg-secondary)]`}>#</th>
                <th className={TH}>File</th>
                <th className={TH}>Pages</th>
                {header.map((f) => (
                  <th key={f.key} className={`${TH} ${isNumeric(f.type) ? "text-right" : ""}`}>{f.label}</th>
                ))}
                {hasRows && <th className={`${TH} text-right`}>Lines</th>}
              </tr>
            </thead>
            <tbody>
              {records.map((rec, i) => (
                <Row
                  key={rec.id}
                  rec={rec}
                  number={page.offset + i + 1}
                  header={header}
                  hasRows={hasRows}
                  fileName={fileNames.get(rec.file_id) ?? ""}
                  open={rec.id === openId}
                  onOpen={onOpen}
                  tipProps={tipProps}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {page && page.total > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-2 border-t border-[var(--border)] px-4 py-2 text-xs text-[var(--text-secondary)]">
          {page.loading && <Spinner size={12} className="animate-spin" />}
          <span>{rangeLabel(page.offset, records.length, page.total)}</span>
          <button type="button" className={`${BTN} !px-2 !py-1`} disabled={page.loading || page.offset === 0}
            onClick={() => onPage(Math.max(0, page.offset - PAGE_SIZE))}>
            <CaretLeft size={12} /> Prev
          </button>
          <button type="button" className={`${BTN} !px-2 !py-1`}
            disabled={page.loading || page.offset + PAGE_SIZE >= page.total}
            onClick={() => onPage(page.offset + PAGE_SIZE)}>
            Next <CaretRight size={12} />
          </button>
        </div>
      )}

      {tip &&
        createPortal(
          <div
            aria-hidden
            className="pointer-events-none fixed z-[95] max-w-[18rem] rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-xs text-[var(--text-primary)] shadow-lg"
            style={{ left: Math.max(8, tip.x), top: tip.y, transform: tip.above ? "translateY(-100%)" : undefined }}
          >
            {tip.lines.map((line, i) => (
              <p key={i} className="flex items-start gap-1.5">
                <FlagMark level={tip.level} /> <span>{line}</span>
              </p>
            ))}
          </div>,
          document.body,
        )}
    </section>
  );
}

function Row({ rec, number, header, hasRows, fileName, open, onOpen, tipProps }: {
  rec: ExtractRecord;
  number: number;
  header: ExtractField[];
  hasRows: boolean;
  fileName: string;
  open: boolean;
  onOpen: (record: ExtractRecord, cell: string | null) => void;
  tipProps: TipProps;
}) {
  const byCell = flagsByCell(rec);
  const edited = editedCells(rec);
  const wide = recordWideFlags(rec);
  const wideLevel = worst(wide.map((f) => f.level));
  const linesLevel = rowsLevel(rec);
  const lineFlags = rec.flags.filter((f) => f.cells?.some((c) => c.row !== null));
  const lineMessages = lineFlags.map(flagSentence);
  const firstLine = lineFlags[0]?.cells.find((c) => c.row !== null);
  // The sticky cell must stay opaque (the accent / hover tints are translucent): layer them over the card colour.
  const bg = open
    ? "[background:linear-gradient(var(--accent-subtle),var(--accent-subtle)),var(--bg-secondary)]"
    : "bg-[var(--bg-secondary)] group-hover:[background:linear-gradient(var(--bg-hover),var(--bg-hover)),var(--bg-secondary)]";
  const enter = (cell: string | null) => (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen(rec, cell);
    }
  };

  return (
    <tr
      className={`group cursor-pointer border-b border-[var(--border)] last:border-b-0 ${open ? "bg-[var(--accent-subtle)]" : "hover:bg-[var(--bg-hover)]"}`}
      onClick={() => onOpen(rec, null)}
    >
      <td className={`${TD} sticky left-0 z-[1] ${wideLevel ? LEVEL_CELL[wideLevel] : bg}`}>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onOpen(rec, null);
          }}
          {...tipProps(wide.map((f) => f.message), wideLevel)}
          tabIndex={0}
          aria-label={`Open record ${number}${lowConfidence(rec) ? ", the reader was not sure about it" : ""}`}
          className="inline-flex items-center gap-1 font-medium tabular-nums text-[var(--text-primary)] hover:underline"
        >
          {number}
          {wideLevel && <FlagMark level={wideLevel} size={10} />}
        </button>
      </td>
      <td className={`${TD} text-[var(--text-secondary)]`}>
        <span className="block max-w-[14rem] truncate" title={fileName}>{fileName}</span>
      </td>
      <td className={`${TD} whitespace-nowrap tabular-nums text-[var(--text-secondary)]`}>
        {pagesLabel(rec.page_start, rec.page_end)}
      </td>
      {header.map((f) => {
        const id = cellId(f.key, null);
        const flags = byCell.get(id) ?? [];
        const level = worst(flags.map((x) => x.level));
        const numeric = isNumeric(f.type);
        const text = displayValue(rec.values.header?.[f.key], f.type);
        return (
          <td
            key={f.key}
            className={`${TD} ${level ? LEVEL_CELL[level] : ""} ${numeric ? "text-right" : ""}`}
            {...tipProps(flags.map((x) => x.message), level)}
            onKeyDown={level ? enter(id) : undefined}
          >
            <span className={`inline-flex max-w-[16rem] items-center gap-1 ${numeric ? "flex-row-reverse" : ""}`}>
              {level && <FlagMark level={level} />}
              <span className={`truncate text-[var(--text-primary)] ${numeric ? "tabular-nums" : ""} ${f.type === "money" ? "aa-amount" : ""}`}>
                {text || <span className="text-[var(--text-tertiary)]">—</span>}
              </span>
              {edited.has(id) && <EditedMark />}
            </span>
            {level && <span className="sr-only">: {flags.map((x) => x.message).join(". ")}</span>}
          </td>
        );
      })}
      {hasRows && (
        <td
          className={`${TD} whitespace-nowrap text-right tabular-nums ${linesLevel ? LEVEL_CELL[linesLevel] : ""}`}
          {...tipProps(lineMessages, linesLevel)}
          onKeyDown={linesLevel && firstLine ? enter(cellId(firstLine.key, firstLine.row)) : undefined}
        >
          <span className="inline-flex items-center gap-1 text-[var(--text-primary)]">
            {linesLevel && <FlagMark level={linesLevel} />}
            {rec.values.rows?.length ?? 0}
          </span>
          {linesLevel && <span className="sr-only">: {lineMessages.join(". ")}</span>}
        </td>
      )}
    </tr>
  );
}
