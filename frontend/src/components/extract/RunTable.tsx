"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { Spinner } from "@phosphor-icons/react";
import { useWorkbookPreview } from "@/components/accounting/WorkbookPreview";
import RecordPanel from "@/components/extract/RecordPanel";
import RecordsTable, { type RecordPage } from "@/components/extract/RecordsTable";
import RunFiles from "@/components/extract/RunFiles";
import RunHeader from "@/components/extract/RunHeader";
import { extractApi } from "@/lib/extract-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { PAGE_SIZE } from "@/lib/extract-flags";
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

/** The open record: its last copy is held here, so the panel stays put when a reload drops it from the page (a fixed
 *  record under "Needs review") until the person closes it or opens another. */
interface Open {
  formatKey: string;
  record: ExtractRecord;
  number: number;
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

  // Hand edits vs page reloads: a page reply that started before an edit landed must not undo it on screen.
  const editSeq = useRef(0);
  const touched = useRef(new Map<string, number>()); // record id -> editSeq when an edit started or ended
  const inFlight = useRef(new Map<string, number>()); // record id -> saves on their way
  const latest = useRef(new Map<string, ExtractRecord>()); // record id -> the last PATCH reply
  const openRef = useRef<Open | null>(null);
  useEffect(() => {
    openRef.current = open;
  });
  // While the panel has unsaved typing or a save in flight, its table's reloads wait (then run once).
  const busy = useRef(false);
  const deferred = useRef<Record<string, { offset: number; review: boolean }>>({});

  // Every run read goes through one counter, so an older reply (a poll vs the read after an edit) never wins.
  const runAsked = useRef(0);
  const runShown = useRef(0);
  const polling = useRef(false);
  const readRun = useCallback(() => {
    const mine = ++runAsked.current;
    return extractApi.run(runId).then((r) => {
      if (alive.current && mine > runShown.current) {
        runShown.current = mine;
        setRun(r);
      }
      return r;
    });
  }, [runId]);

  // The run itself: polled every 2 s while reading, with backoff on failures (then Retry), stopped on unmount.
  const wasReading = useRef(false);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    setPollError("");
    polling.current = true;
    const tick = () =>
      readRun()
        .then((r) => {
          if (!live) return;
          failures = 0;
          setPollError("");
          if (r.status === "reading") {
            wasReading.current = true;
            timer = setTimeout(tick, POLL_MS);
            return;
          }
          polling.current = false;
          if (wasReading.current) {
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
          if (failures > MAX_RETRIES) {
            polling.current = false;
            setPollError(apiErrorMessage(e, "Couldn't load this extract"));
          } else timer = setTimeout(tick, POLL_MS * 2 ** failures);
        });
    tick();
    return () => {
      live = false;
      polling.current = false;
      clearTimeout(timer);
    };
  }, [readRun, kick]);

  const load = useCallback(
    (key: string, offset: number, reviewOnlyNow: boolean) => {
      const mine = (requests.current[key] ?? 0) + 1;
      requests.current[key] = mine;
      const since = editSeq.current;
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
          setPages((p) => {
            // Records edited (or with a save on its way) since this load started keep the copy on screen.
            const shown = new Map((p[key]?.records ?? []).map((r) => [r.id, r]));
            const keep = (id: string) => (touched.current.get(id) ?? 0) > since || (inFlight.current.get(id) ?? 0) > 0;
            const records = res.records.map((r) => (keep(r.id) ? latest.current.get(r.id) ?? shown.get(r.id) ?? r : r));
            return { ...p, [key]: { offset: res.offset, total: res.total, records, loading: false, error: "" } };
          });
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

  /** `load`, held while the open record's panel is busy (its table only). */
  const request = useCallback(
    (key: string, offset: number, reviewOnlyNow: boolean) => {
      if (busy.current && openRef.current?.formatKey === key) deferred.current[key] = { offset, review: reviewOnlyNow };
      else load(key, offset, reviewOnlyNow);
    },
    [load],
  );
  const onBusy = useCallback(
    (now: boolean) => {
      busy.current = now;
      if (now) return;
      const waiting = deferred.current;
      deferred.current = {};
      Object.entries(waiting).forEach(([key, w]) => load(key, w.offset, w.review));
    },
    [load],
  );

  // A table loads when its format first has records, and reloads its page when a poll shows more.
  useEffect(() => {
    if (!run) return;
    for (const f of run.formats) {
      if (f.records === 0) continue;
      const before = seen.current[f.format_key];
      if (before !== undefined && f.records <= before) continue;
      seen.current[f.format_key] = f.records;
      request(f.format_key, before === undefined ? 0 : offsets.current[f.format_key] ?? 0, review.current);
    }
  }, [run, request]);

  const setFilter = (on: boolean) => {
    if (on === review.current) return;
    review.current = on;
    setReviewOnly(on);
    Object.keys(seen.current).forEach((key) => request(key, 0, on));
  };

  const onEditStart = useCallback((id: string) => {
    inFlight.current.set(id, (inFlight.current.get(id) ?? 0) + 1);
    touched.current.set(id, ++editSeq.current);
  }, []);
  const endEdit = useCallback((id: string) => {
    const n = (inFlight.current.get(id) ?? 1) - 1;
    if (n > 0) inFlight.current.set(id, n);
    else inFlight.current.delete(id);
    touched.current.set(id, ++editSeq.current);
  }, []);
  const onSaved = useCallback(
    (formatKey: string, rec: ExtractRecord) => {
      latest.current.set(rec.id, rec);
      endEdit(rec.id);
      setPages((p) => {
        const page = p[formatKey];
        if (!page) return p;
        return { ...p, [formatKey]: { ...page, records: page.records.map((r) => (r.id === rec.id ? rec : r)) } };
      });
      setOpen((o) => (o && o.record.id === rec.id ? { ...o, record: rec } : o));
      // Red / yellow counts changed: one run read refreshes them (and resumes polling if the run reads again).
      readRun()
        .then((r) => {
          if (alive.current && r.status === "reading" && !polling.current) setKick((k) => k + 1);
        })
        .catch(() => undefined);
    },
    [readRun, endEdit],
  );
  const closePanel = useCallback(() => {
    const id = openRef.current?.record.id;
    setOpen(null);
    // Focus goes back to the record's row (its "Open record" button) when it is still on screen.
    if (id) {
      requestAnimationFrame(() => {
        const btn = Array.from(document.querySelectorAll<HTMLElement>("[data-open-record]")).find(
          (b) => b.dataset.openRecord === id,
        );
        btn?.focus();
      });
    }
  }, []);

  const formats = (run?.formats ?? []).filter((f) => f.records > 0);
  const fileNames = new Map((run?.files ?? []).map((f) => [f.id, f.name]));

  const openPage = open ? pages[open.formatKey] : undefined;
  const openIndex = open && openPage ? openPage.records.findIndex((r) => r.id === open.record.id) : -1;
  const openAt = (formatKey: string, rec: ExtractRecord, cell: string | null) => {
    const page = pages[formatKey];
    const at = page ? page.records.findIndex((r) => r.id === rec.id) : -1;
    setOpen({ formatKey, record: rec, number: page && at >= 0 ? page.offset + at + 1 : 0, focus: { cell, nonce: Date.now() } });
  };
  const step = (by: 1 | -1) => {
    const next = open && openPage?.records[openIndex + by];
    if (open && next) openAt(open.formatKey, next, null);
  };

  const download = (key: string, name: string) => {
    const day = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Manila" });
    sheet.open(`${name} · extract`, () => extractApi.xlsxPreview(runId, key), () => extractApi.xlsx(runId, key),
      `${fileSafe(name)} extract ${day}.xlsx`);
  };

  const wide = useWide();
  const panel = run && open ? (
    <RecordPanel
      key={open.record.id}
      record={open.record}
      snapshot={run.snapshots[open.formatKey]}
      number={openPage && openIndex >= 0 ? openPage.offset + openIndex + 1 : open.number}
      fileName={fileNames.get(open.record.file_id) ?? ""}
      focus={open.focus}
      modal={!wide}
      onClose={closePanel}
      onEditStart={onEditStart}
      onEditFailed={endEdit}
      onSaved={(rec) => onSaved(open.formatKey, rec)}
      onBusy={onBusy}
      onPrev={openPage && openIndex > 0 ? () => step(-1) : undefined}
      onNext={openPage && openIndex >= 0 && openIndex < openPage.records.length - 1 ? () => step(1) : undefined}
    />
  ) : null;

  const anyChoose = run?.files.some((f) => f.status === "choose") ?? false;
  const allFailed = !!run && run.files.length > 0 && run.files.every((f) => f.status === "error");

  return (
    <div className="space-y-4">
      <RunHeader run={run} formats={formats} reviewOnly={reviewOnly} onFilter={setFilter} onBack={() => onBack()} />

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

          <div className={open ? "md:grid md:grid-cols-2 md:items-start md:gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]" : ""}>
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
                    openId={open?.record.id ?? null}
                    onOpen={(rec, cell) => openAt(f.format_key, rec, cell)}
                    onPage={(offset) => request(f.format_key, offset, review.current)}
                    onRetry={() => request(f.format_key, offsets.current[f.format_key] ?? 0, review.current)}
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
