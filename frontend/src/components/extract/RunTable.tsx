"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, Spinner } from "@phosphor-icons/react";
import PrivacyToggle from "@/components/accounting/PrivacyToggle";
import { useWorkbookPreview } from "@/components/accounting/WorkbookPreview";
import { when } from "@/components/extract/RunHistory";
import { FlagMark } from "@/components/extract/FlagMark";
import RecordPanel from "@/components/extract/RecordPanel";
import RecordsTable, { type RecordPage } from "@/components/extract/RecordsTable";
import RunFiles from "@/components/extract/RunFiles";
import { extractApi } from "@/lib/extract-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { PAGE_SIZE, plural } from "@/lib/extract-flags";
import type { ExtractRecord, ExtractRun } from "@/types/extract";

const POLL_MS = 2000;
const MAX_RETRIES = 5;
const GONE = "That extract no longer exists.";

interface Props {
  runId: string;
  /** Back to Past extracts; `message` explains why when the run is gone. */
  onBack: (message?: string) => void;
  /** The run finished reading (Past extracts' counts changed). */
  onChanged: () => void;
}

interface Open {
  formatKey: string;
  recordId: string;
  focus: { cell: string | null; nonce: number };
}

const WIDE = "(min-width: 768px)";
const subscribeWide = (cb: () => void) => {
  const mq = window.matchMedia(WIDE);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
};
/** md+ shows the record panel beside the tables; phones get a full-screen sheet (portalled: the page's entrance
 *  animation leaves a transform that would trap a fixed element). */
const useWide = () => useSyncExternalStore(subscribeWide, () => window.matchMedia(WIDE).matches, () => true);

const status = (e: unknown) => (e as { response?: { status?: number } })?.response?.status;
const fileSafe = (name: string) => name.replace(/[^A-Za-z0-9 _-]+/g, "").trim() || "Extract";

/** The run screen: files still working or waiting for a format, one records table per format, the record panel. */
export default function RunTable({ runId, onBack, onChanged }: Props) {
  const [run, setRun] = useState<ExtractRun | null>(null);
  const [pollError, setPollError] = useState("");
  const [kick, setKick] = useState(0);
  const [reviewOnly, setReviewOnly] = useState(false);
  const [pages, setPages] = useState<Record<string, RecordPage>>({});
  const [open, setOpen] = useState<Open | null>(null);
  const sheet = useWorkbookPreview();

  const changed = useRef(onChanged);
  const back = useRef(onBack);
  useEffect(() => {
    changed.current = onChanged;
    back.current = onBack;
  });
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const review = useRef(false);
  const seen = useRef<Record<string, number>>({}); // record count per format when its table last loaded
  const offsets = useRef<Record<string, number>>({});
  const requests = useRef<Record<string, number>>({}); // drop page replies older than the latest asked for

  // The run itself: polled every 2 s while reading, with backoff on failures (then Retry), stopped on unmount.
  const wasReading = useRef(false);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    setPollError("");
    const tick = () =>
      extractApi
        .run(runId)
        .then((r) => {
          if (!live) return;
          failures = 0;
          setRun(r);
          setPollError("");
          if (r.status === "reading") {
            wasReading.current = true;
            timer = setTimeout(tick, POLL_MS);
          } else if (wasReading.current) {
            wasReading.current = false;
            changed.current();
          }
        })
        .catch((e) => {
          if (!live) return;
          if (status(e) === 404) {
            back.current(GONE);
            return;
          }
          failures += 1;
          if (failures > MAX_RETRIES) setPollError(apiErrorMessage(e, "Couldn't load this extract"));
          else timer = setTimeout(tick, POLL_MS * 2 ** failures);
        });
    tick();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [runId, kick]);

  const load = useCallback(
    (key: string, offset: number, reviewOnlyNow: boolean) => {
      const mine = (requests.current[key] ?? 0) + 1;
      requests.current[key] = mine;
      offsets.current[key] = offset;
      setPages((p) => ({
        ...p,
        [key]: { ...(p[key] ?? { offset, total: 0, records: [] }), loading: true, error: "" },
      }));
      extractApi
        .records(runId, { formatKey: key, offset, limit: PAGE_SIZE, reviewOnly: reviewOnlyNow })
        .then((res) => {
          if (!alive.current || requests.current[key] !== mine) return;
          if (res.records.length === 0 && offset > 0) {
            load(key, 0, reviewOnlyNow); // the page emptied (fewer records now): back to the first
            return;
          }
          setPages((p) => ({ ...p, [key]: { offset: res.offset, total: res.total, records: res.records, loading: false, error: "" } }));
        })
        .catch((e) => {
          if (!alive.current || requests.current[key] !== mine) return;
          if (status(e) === 404) {
            back.current(GONE);
            return;
          }
          setPages((p) => ({
            ...p,
            [key]: { ...(p[key] ?? { offset, total: 0, records: [] }), loading: false, error: apiErrorMessage(e, "Couldn't load the records") },
          }));
        });
    },
    [runId],
  );

  // A table loads when its format first has records, and reloads its page when a poll shows more.
  useEffect(() => {
    if (!run) return;
    for (const f of run.formats) {
      if (f.records === 0) continue;
      const before = seen.current[f.format_key];
      if (before !== undefined && f.records <= before) continue;
      seen.current[f.format_key] = f.records;
      load(f.format_key, before === undefined ? 0 : offsets.current[f.format_key] ?? 0, review.current);
    }
  }, [run, load]);

  const setFilter = (on: boolean) => {
    if (on === review.current) return;
    review.current = on;
    setReviewOnly(on);
    Object.keys(seen.current).forEach((key) => load(key, 0, on));
  };

  const onSaved = useCallback(
    (formatKey: string, rec: ExtractRecord) => {
      setPages((p) => {
        const page = p[formatKey];
        if (!page) return p;
        return { ...p, [formatKey]: { ...page, records: page.records.map((r) => (r.id === rec.id ? rec : r)) } };
      });
      // Red / yellow counts changed: one run read refreshes them.
      extractApi
        .run(runId)
        .then((r) => {
          if (!alive.current) return;
          setRun(r);
          if (r.status === "reading") setKick((k) => k + 1);
        })
        .catch(() => undefined);
    },
    [runId],
  );
  const closePanel = useCallback(() => setOpen(null), []);

  const formats = (run?.formats ?? []).filter((f) => f.records > 0);
  const fileNames = new Map((run?.files ?? []).map((f) => [f.id, f.name]));
  const totals = formats.reduce((t, f) => ({ n: t.n + f.records, red: t.red + f.red, yellow: t.yellow + f.yellow }), { n: 0, red: 0, yellow: 0 });

  const openPage = open ? pages[open.formatKey] : undefined;
  const openIndex = open && openPage ? openPage.records.findIndex((r) => r.id === open.recordId) : -1;
  const openRecord = openIndex >= 0 && openPage ? openPage.records[openIndex] : null;
  const step = (by: 1 | -1) => {
    const next = open && openPage?.records[openIndex + by];
    if (open && next) setOpen({ formatKey: open.formatKey, recordId: next.id, focus: { cell: null, nonce: Date.now() } });
  };

  const download = (key: string, name: string) => {
    const day = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Manila" });
    sheet.open(`${name} · extract`, () => extractApi.xlsxPreview(runId, key), () => extractApi.xlsx(runId, key),
      `${fileSafe(name)} extract ${day}.xlsx`);
  };

  const panel = run && open && openRecord && openPage ? (
    <RecordPanel
      key={openRecord.id}
      record={openRecord}
      snapshot={run.snapshots[open.formatKey]}
      number={openPage.offset + openIndex + 1}
      fileName={fileNames.get(openRecord.file_id) ?? ""}
      focus={open.focus}
      onClose={closePanel}
      onSaved={(rec) => onSaved(open.formatKey, rec)}
      onPrev={openIndex > 0 ? () => step(-1) : undefined}
      onNext={openIndex < openPage.records.length - 1 ? () => step(1) : undefined}
    />
  ) : null;
  const wide = useWide();

  const anyChoose = run?.files.some((f) => f.status === "choose") ?? false;
  const allFailed = !!run && run.files.length > 0 && run.files.every((f) => f.status === "error");

  return (
    <div className="space-y-4">
      <section className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-3">
        <button
          type="button"
          onClick={() => onBack()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
        >
          <ArrowLeft size={14} /> Past extracts
        </button>
        {run ? (
          <div className="min-w-0 flex-1 basis-48">
            <h2 className="flex items-center gap-2 truncate text-base font-semibold text-[var(--text-primary)]">
              <span className="truncate">{run.format_name}</span>
              {run.status === "reading" && (
                <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-[var(--text-secondary)]">
                  <Spinner size={12} className="animate-spin" /> Reading
                </span>
              )}
              {run.status === "failed" && (
                <span className="shrink-0 rounded-full bg-[var(--badge-red-bg)] px-2 py-0.5 text-xs font-medium text-[var(--badge-red-text)]">Failed</span>
              )}
            </h2>
            <p className="flex flex-wrap items-center gap-x-2 text-xs text-[var(--text-secondary)]">
              <span>{run.created_by_name || "Someone"} · {when(run.created_at)}</span>
              <span>· {plural(totals.n, "record")}</span>
              {totals.red + totals.yellow > 0 && (
                <>
                  <span>· {totals.red + totals.yellow} need review</span>
                  {totals.red > 0 && <span className="inline-flex items-center gap-1"><FlagMark level="red" /> {totals.red} red</span>}
                  {totals.yellow > 0 && <span className="inline-flex items-center gap-1"><FlagMark level="yellow" /> {totals.yellow} yellow</span>}
                </>
              )}
            </p>
          </div>
        ) : (
          <span className="flex-1" />
        )}
        <div role="group" aria-label="Show" className="inline-flex rounded-lg border border-[var(--border)] p-0.5 text-sm">
          {([["All", false], ["Needs review", true]] as const).map(([label, on]) => (
            <button
              key={label}
              type="button"
              aria-pressed={reviewOnly === on}
              onClick={() => setFilter(on)}
              className={`rounded-md px-3 py-1 font-medium ${reviewOnly === on ? "bg-[var(--accent-subtle)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <PrivacyToggle />
      </section>

      {pollError && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--alert-error-border)] bg-[var(--alert-error-bg)] px-4 py-2 text-sm text-[var(--alert-error-text)]">
          <span className="flex-1">{pollError}</span>
          <button type="button" onClick={() => setKick((k) => k + 1)} className="font-medium underline">Retry</button>
        </div>
      )}
      {!run && !pollError && (
        <p className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          <Spinner size={14} className="animate-spin" /> Loading
        </p>
      )}

      {run && (
        <>
          <RunFiles
            run={run}
            onPicked={(file) => {
              setRun((r) => (r ? { ...r, status: "reading", files: r.files.map((f) => (f.id === file.id ? file : f)) } : r));
              setKick((k) => k + 1);
            }}
          />

          <div className={openRecord ? "md:grid md:grid-cols-2 md:items-start md:gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]" : ""}>
            <div className="min-w-0 space-y-4">
              {formats.length === 0 ? (
                <p className="flex items-center justify-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-10 text-center text-sm text-[var(--text-secondary)]">
                  {run.status === "reading" ? (
                    <><Spinner size={14} className="animate-spin" /> Reading your files. Records show up here as each one is read.</>
                  ) : anyChoose ? (
                    "Pick a format for the files above to read them."
                  ) : allFailed ? (
                    "None of these files could be read."
                  ) : (
                    "Nothing was found in these files."
                  )}
                </p>
              ) : (
                formats.map((f) => (
                  <RecordsTable
                    key={f.format_key}
                    count={f}
                    snapshot={run.snapshots[f.format_key]}
                    showName={formats.length > 1}
                    page={pages[f.format_key]}
                    reviewOnly={reviewOnly}
                    fileNames={fileNames}
                    openId={open?.recordId ?? null}
                    onOpen={(rec, cell) =>
                      setOpen({ formatKey: f.format_key, recordId: rec.id, focus: { cell, nonce: Date.now() } })}
                    onPage={(offset) => load(f.format_key, offset, review.current)}
                    onRetry={() => load(f.format_key, offsets.current[f.format_key] ?? 0, review.current)}
                    onDownload={() => download(f.format_key, f.name)}
                  />
                ))
              )}
            </div>
            {panel && (wide ? panel : createPortal(panel, document.body))}
          </div>
        </>
      )}
      {sheet.node}
    </div>
  );
}
