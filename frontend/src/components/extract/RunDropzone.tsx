"use client";

import { useCallback, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Spinner, UploadSimple } from "@phosphor-icons/react";
import { extractApi } from "@/lib/extract-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { prepareDrop } from "@/lib/photo-shrink";

const ACCEPT = { "application/pdf": [".pdf"], "image/png": [".png"], "image/jpeg": [".jpg", ".jpeg"] };
// Same limits as the Documents drop (backend MAX_FILE_SIZE_MB / MAX_BATCH_SIZE, Cloudflare's 100 MB body cap).
const MAX_FILE_MB = 50;
const MAX_FILES = 200;
const MAX_DROP_MB = 95;

function dropProblem(files: File[]): string | null {
  const MB = 1024 * 1024;
  if (files.length > MAX_FILES) return `Drop at most ${MAX_FILES} files at a time (this drop has ${files.length}).`;
  const big = files.find((f) => f.size > MAX_FILE_MB * MB);
  if (big) return `"${big.name}" is over the ${MAX_FILE_MB} MB limit per file.`;
  const total = files.reduce((sum, f) => sum + f.size, 0);
  if (total > MAX_DROP_MB * MB)
    return `This drop is ${Math.ceil(total / MB)} MB; drop up to ${MAX_DROP_MB} MB at a time by splitting it into smaller drops.`;
  return null;
}

interface Props {
  formatKey: string;
  formatName: string;
  /** Why dropping is off (no format to read with yet), or null. */
  disabledHint: string | null;
  onCreated: (runId: string) => void;
  onError: (message: string) => void;
}

/** Drop files to read them with the picked format; the run opens once the files are stored. */
export default function RunDropzone({ formatKey, formatName, disabledHint, onCreated, onError }: Props) {
  const [busy, setBusy] = useState("");
  const working = useRef(false);
  const disabled = !!disabledHint || !!busy;

  const onDrop = useCallback(
    async (files: File[]) => {
      if (!files.length || working.current) return;
      const early = files.length > MAX_FILES ? dropProblem(files) : null;
      if (early) return onError(early);
      onError("");
      working.current = true;
      try {
        // Photos are shrunk on this device first (smaller, faster uploads); the server still checks everything.
        const drop = await prepareDrop(files, (done, total) =>
          setBusy(total > 1 ? `Shrinking photos ${done} of ${total}…` : "Shrinking photo…"),
        );
        const problem = dropProblem(drop.files);
        if (problem) return onError(problem);
        setBusy(drop.files.length > 1 ? `Uploading ${drop.files.length} files…` : "Uploading…");
        const run = await extractApi.createRun(drop.files, formatKey);
        onCreated(run.id);
      } catch (e) {
        onError(apiErrorMessage(e, "Upload failed"));
      } finally {
        working.current = false;
        setBusy("");
      }
    },
    [formatKey, onCreated, onError],
  );

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    onDropRejected: () => onError("Only PDF, PNG and JPG files can be dropped here."),
    accept: ACCEPT,
    noClick: true,
    noKeyboard: true,
    disabled,
  });

  return (
    <div
      {...getRootProps({
        className: `flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-dashed px-4 py-3 transition-colors ${
          isDragActive ? "border-[var(--accent)] bg-[var(--accent-subtle)]" : "border-[var(--border)] bg-[var(--bg-secondary)]"
        }`,
      })}
    >
      <input {...getInputProps()} />
      {busy ? (
        <Spinner size={20} className="shrink-0 animate-spin text-[var(--accent)]" />
      ) : (
        <UploadSimple size={20} className="shrink-0 text-[var(--text-secondary)]" />
      )}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-[var(--text-primary)]">
          {busy || (isDragActive ? "Drop to read them" : "Drop receipts, invoices or scans here")}
        </p>
        <p className="text-xs text-[var(--text-secondary)]">
          {disabledHint ??
            (formatKey === "auto"
              ? "We'll pick the format for each file. PDF, PNG or JPG."
              : `Read as ${formatName}. PDF, PNG or JPG.`)}
        </p>
      </div>
      <button
        type="button"
        onClick={open}
        disabled={disabled}
        className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60"
      >
        <UploadSimple size={16} /> Upload files
      </button>
    </div>
  );
}
