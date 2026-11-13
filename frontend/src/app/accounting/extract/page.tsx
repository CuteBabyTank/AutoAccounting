"use client";

import { useCallback, useEffect, useState } from "react";
import FormatPicker, { AUTO } from "@/components/extract/FormatPicker";
import RunDropzone from "@/components/extract/RunDropzone";
import RunHistory, { appendPage, mergeFirstPage, when } from "@/components/extract/RunHistory";
import FormatBuilder from "@/components/extract/FormatBuilder";
import RunTable from "@/components/extract/RunTable";
import { confirmDialog } from "@/components/ui/Dialogs";
import { extractApi } from "@/lib/extract-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { useAuth } from "@/lib/auth";
import type { ExtractFormat, ExtractRunSummary } from "@/types/extract";

const HISTORY_POLL_MS = 4000;
const RUNS_PAGE = 50;

type Builder = { mode: "new" } | { mode: "edit"; format: ExtractFormat } | null;

export default function ExtractPage() {
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "enterprise" || user?.role === "manager";

  const [formats, setFormats] = useState<ExtractFormat[]>([]);
  const [formatsLoaded, setFormatsLoaded] = useState(false);
  const [formatKey, setFormatKey] = useState(AUTO);
  const [runs, setRuns] = useState<ExtractRunSummary[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [runsLoaded, setRunsLoaded] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [openRunId, setOpenRunId] = useState<string | null>(null);
  const [builder, setBuilder] = useState<Builder>(null);
  const [error, setError] = useState("");

  /** `prefer` picks the format to select from the fresh list (after a save or reset), else the selection stays. */
  const loadFormats = useCallback(
    (prefer?: (list: ExtractFormat[]) => string) =>
      extractApi
        .formats()
        .then((list) => {
          setFormats(list);
          // A format deleted elsewhere falls back to Auto detect.
          setFormatKey((current) => {
            const key = prefer ? prefer(list) : current;
            return key === AUTO || list.some((f) => f.key === key) ? key : AUTO;
          });
        })
        .catch((e) => setError(apiErrorMessage(e, "Couldn't load your formats")))
        .finally(() => setFormatsLoaded(true)),
    [],
  );
  /** Refresh the first page only, keeping runs loaded by "Show more" past it. */
  const refreshRuns = useCallback(
    () =>
      extractApi.runs(0, RUNS_PAGE).then((page) => {
        setRuns((shown) => mergeFirstPage(shown, page.runs, RUNS_PAGE));
        setRunsTotal(page.total);
      }),
    [],
  );
  const loadRuns = useCallback(
    () =>
      refreshRuns()
        .catch((e) => setError(apiErrorMessage(e, "Couldn't load past extracts")))
        .finally(() => setRunsLoaded(true)),
    [refreshRuns],
  );

  async function loadMoreRuns() {
    setLoadingMore(true);
    try {
      const page = await extractApi.runs(runs.length, RUNS_PAGE);
      setRuns((shown) => appendPage(shown, page.runs));
      setRunsTotal(page.total);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't load more past extracts"));
    } finally {
      setLoadingMore(false);
    }
  }

  useEffect(() => {
    loadFormats();
    loadRuns();
  }, [loadFormats, loadRuns]);

  // Past extracts still reading refresh until they finish (counts and status change).
  const anyReading = runs.some((r) => r.status === "reading");
  useEffect(() => {
    if (!anyReading || openRunId) return;
    const timer = setInterval(() => refreshRuns().catch(() => undefined), HISTORY_POLL_MS);
    return () => clearInterval(timer);
  }, [anyReading, openRunId, refreshRuns]);

  const selected = formats.find((f) => f.key === formatKey) ?? null;
  const disabledHint = !formatsLoaded
    ? "Loading formats…"
    : formats.length === 0
      ? canManage ? "Add a format first." : "No formats yet. Ask your firm owner or a manager to add one."
      : null;

  const onCreated = useCallback(
    (id: string) => {
      setOpenRunId(id);
      loadRuns();
    },
    [loadRuns],
  );

  async function deleteRun(run: ExtractRunSummary) {
    const ok = await confirmDialog({
      title: "Delete this extract?",
      message: `${run.format_name} from ${when(run.created_at)}. Its files and records are removed.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    setError("");
    try {
      await extractApi.deleteRun(run.id);
      if (openRunId === run.id) setOpenRunId(null);
      setRuns((shown) => shown.filter((r) => r.id !== run.id));
      setRunsTotal((n) => Math.max(0, n - 1));
      await loadRuns();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't delete the extract"));
    }
  }

  return (
    <div className="lp relative min-h-screen">
      <div className={`p-4 sm:p-8 page-enter ${openRunId ? "max-w-[100rem]" : "max-w-6xl"}`}>
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Extract</h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Read any pile of documents into a table you can check and download as Excel.
          </p>
        </div>

        <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
          <FormatPicker
            formats={formats}
            value={formatKey}
            onChange={setFormatKey}
            canManage={canManage}
            onAdd={() => setBuilder({ mode: "new" })}
            onEdit={(format) => setBuilder({ mode: "edit", format })}
          />
          <div className="min-w-0 flex-1">
            <RunDropzone
              formatKey={selected ? selected.key : AUTO}
              formatName={selected?.name ?? ""}
              disabledHint={disabledHint}
              onCreated={onCreated}
              onError={setError}
            />
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-[var(--alert-error-border)] bg-[var(--alert-error-bg)] px-4 py-2 text-sm text-[var(--alert-error-text)]">
            {error}
          </div>
        )}

        {openRunId ? (
          <RunTable
            key={openRunId}
            runId={openRunId}
            onBack={(message) => {
              setOpenRunId(null);
              setError(message ?? "");
              loadRuns(); // hand edits change the red / yellow counts
            }}
            onChanged={loadRuns}
          />
        ) : (
          <RunHistory
            runs={runs}
            total={runsTotal}
            loaded={runsLoaded}
            loadingMore={loadingMore}
            onMore={loadMoreRuns}
            userId={user?.id ?? null}
            canManage={canManage}
            onOpen={(id) => {
              setError("");
              setOpenRunId(id);
            }}
            onDelete={deleteRun}
          />
        )}
      </div>

      {builder && (
        <FormatBuilder
          mode={builder.mode}
          format={builder.mode === "edit" ? builder.format : undefined}
          onClose={() => setBuilder(null)}
          onSaved={(format) => {
            setBuilder(null);
            loadFormats(() => format.key);
          }}
          onDeleted={(format) => {
            // A reset copy gives its place back to the built-in (formats keep the built-ins' order first).
            const place = formats.findIndex((f) => f.key === format.key);
            setBuilder(null);
            loadFormats((list) => (format.edited && list[place]?.builtin ? list[place].key : AUTO));
          }}
        />
      )}
    </div>
  );
}
