"use client";

import { useState } from "react";
import { Question, Spinner, WarningCircle } from "@phosphor-icons/react";
import { extractApi } from "@/lib/extract-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { ExtractFile, ExtractFileStatus, ExtractRun } from "@/types/extract";

const SHOWN = 6;
const WORKING: Record<string, string> = { queued: "Waiting", detecting: "Finding the format", reading: "Reading" };
const isWorking = (s: ExtractFileStatus) => s === "queued" || s === "detecting" || s === "reading";

interface Props {
  run: ExtractRun;
  /** A file got its format: the run reads again (the parent resumes polling). */
  onPicked: (file: ExtractFile) => void;
}

/** Files that still need something: being read, waiting for a format pick, or couldn't be read. */
export default function RunFiles({ run, onPicked }: Props) {
  const [all, setAll] = useState(false);
  const choose = run.files.filter((f) => f.status === "choose");
  const working = run.files.filter((f) => isWorking(f.status));
  const failed = run.files.filter((f) => f.status === "error");
  if (choose.length + working.length + failed.length === 0) return null;

  const rest = [...working, ...failed];
  const shown = all ? rest : rest.slice(0, SHOWN);
  const formats = Object.entries(run.snapshots).map(([key, s]) => ({ key, name: s.name }));

  return (
    <div className="space-y-2">
      {choose.length > 0 && (
        <ul className="divide-y divide-[var(--border)] rounded-xl border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)]">
          {choose.map((f) => (
            <ChooseRow key={f.id} file={f} formats={formats} onPicked={onPicked} />
          ))}
        </ul>
      )}
      {rest.length > 0 && (
        <ul className="divide-y divide-[var(--border)] rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)]">
          {shown.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
              <span className="min-w-0 flex-1 basis-40 truncate text-[var(--text-primary)]" title={f.name}>{f.name}</span>
              {f.status === "error" ? (
                <span className="inline-flex min-w-0 items-start gap-1 text-xs text-[var(--alert-error-text)]">
                  <WarningCircle size={13} className="mt-px shrink-0" aria-hidden /> {f.error || "Couldn't read this file"}
                </span>
              ) : (
                <span className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
                  <span className="relative h-1 w-16 overflow-hidden rounded-full bg-[var(--border)]" aria-hidden>
                    <span className="absolute inset-y-0 left-0 w-1/2 animate-pulse rounded-full bg-[var(--accent)]" />
                  </span>
                  {WORKING[f.status]}
                </span>
              )}
            </li>
          ))}
          {rest.length > SHOWN && (
            <li className="px-4 py-1.5">
              <button type="button" onClick={() => setAll((v) => !v)}
                className="text-xs font-medium text-[var(--accent)] hover:underline">
                {all ? "Show fewer" : `Show ${rest.length - SHOWN} more`}
              </button>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

function ChooseRow({ file, formats, onPicked }: {
  file: ExtractFile;
  formats: { key: string; name: string }[];
  onPicked: (file: ExtractFile) => void;
}) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function read() {
    if (!key) return;
    setBusy(true);
    setError("");
    try {
      onPicked(await extractApi.pickFileFormat(file.id, key));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't start reading this file"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2 text-sm">
      <span className="flex min-w-0 flex-1 basis-48 items-center gap-1.5">
        <Question size={14} className="shrink-0 text-[var(--alert-warning-icon)]" aria-hidden />
        <span className="min-w-0">
          <span className="block truncate font-medium text-[var(--text-primary)]" title={file.name}>{file.name}</span>
          <span className="block text-xs text-[var(--alert-warning-text)]">We couldn&apos;t tell what this is.</span>
        </span>
      </span>
      <select
        value={key}
        onChange={(e) => setKey(e.target.value)}
        aria-label={`Format for ${file.name}`}
        className="min-w-0 max-w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-2 py-1.5 text-sm text-[var(--text-primary)]"
      >
        <option value="">Pick a format…</option>
        {formats.map((f) => (
          <option key={f.key} value={f.key}>{f.name}</option>
        ))}
      </select>
      <button
        type="button"
        disabled={!key || busy}
        onClick={read}
        className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
      >
        {busy && <Spinner size={12} className="animate-spin" />} Read
      </button>
      {error && <p className="w-full text-xs text-[var(--alert-error-text)]">{error}</p>}
    </li>
  );
}
