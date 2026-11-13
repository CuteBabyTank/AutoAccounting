"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useDropzone } from "react-dropzone";
import type { AxiosError } from "axios";
import { ArrowCounterClockwise, FileText, Spinner, Trash, UploadSimple, X } from "@phosphor-icons/react";
import FieldChips, { FOCUS, LABEL_MAX, type BuilderField } from "@/components/extract/FieldChips";
import MissingFields from "@/components/extract/MissingFields";
import CheckList, { checkFields } from "@/components/extract/CheckList";
import { confirmDialog } from "@/components/ui/Dialogs";
import { extractApi } from "@/lib/extract-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { ExtractCheck, ExtractDraftField, ExtractField, ExtractFormat, ExtractFormatInput } from "@/types/extract";

const ACCEPT = { "application/pdf": [".pdf"], "image/png": [".png"], "image/jpeg": [".jpg", ".jpeg"] };
const MAX_FILE_MB = 50; // backend MAX_FILE_SIZE_MB
const SAMPLE_PAGES = 5; // backend builder.SAMPLE_PAGES
const DESCRIPTION_MAX = 200;
const FRESH_MS = 2400;

interface Props {
  mode: "new" | "edit";
  format?: ExtractFormat;
  onClose: () => void;
  onSaved: (format: ExtractFormat) => void;
  /** The format was deleted, or the firm's copy of a built-in reset to the original. */
  onDeleted: (format: ExtractFormat) => void;
}

type Sample = { draftId: string; fileName: string; pages: number; asksLeft: number };

const requiredKeys = (checks: ExtractCheck[]) =>
  new Set(checks.filter((c) => c.kind === "required" && c.field).map((c) => c.field as string));

function toField(f: ExtractField | ExtractDraftField, picked: boolean, required: Set<string>): BuilderField {
  return {
    key: f.key,
    label: f.label,
    original: f.label,
    value: "value" in f ? f.value : null,
    scope: f.scope,
    picked,
    required: f.required || required.has(f.key),
  };
}

const status = (e: unknown) => (e as AxiosError)?.response?.status;

/** Build or edit a format: drop a sample, pick the fields the reader found, review the checks, name it, save. */
export default function FormatBuilder({ mode, format, onClose, onSaved, onDeleted }: Props) {
  const editing = mode === "edit" && !!format;
  // A built-in the firm hasn't changed is copied from a draft, so its sample is required; other edits may skip it.
  const needsSample = !editing || format.builtin;

  const [fields, setFields] = useState<BuilderField[]>(() =>
    editing ? format.fields.map((f) => toField(f, true, requiredKeys(format.checks))) : [],
  );
  const [checks, setChecks] = useState<ExtractCheck[]>(() => (editing ? format.checks : []));
  const [off, setOff] = useState<ReadonlySet<string>>(new Set());
  const [name, setName] = useState(editing ? format.name : "");
  const [description, setDescription] = useState(editing ? format.description : "");
  const [sample, setSample] = useState<Sample | null>(null);
  const [reading, setReading] = useState<string | null>(null); // file name while the reader works
  const [elapsed, setElapsed] = useState(0);
  const [sampleError, setSampleError] = useState("");
  const [asking, setAsking] = useState(false);
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [nameError, setNameError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [dirty, setDirty] = useState(false);

  const panelRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const confirming = useRef(false);

  const locked = needsSample && !sample;
  const hasFields = fields.length > 0;
  const picked = fields.filter((f) => f.picked);
  const busy = !!reading || asking || saving;

  // Focus moves into the dialog and back to what opened it; a read or ask in flight is dropped on close.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => {
      abortRef.current?.abort();
      opener?.focus?.();
    };
  }, []);

  useEffect(() => {
    if (!reading) return;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [reading]);

  useEffect(() => {
    if (!fresh.size) return;
    const timer = setTimeout(() => setFresh(new Set()), FRESH_MS);
    return () => clearTimeout(timer);
  }, [fresh]);

  const change = () => setDirty(true);

  const readSample = useCallback(
    async (file: File) => {
      if (file.size > MAX_FILE_MB * 1024 * 1024) {
        setSampleError(`"${file.name}" is over the ${MAX_FILE_MB} MB limit.`);
        return;
      }
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setSampleError("");
      setReading(file.name);
      panelRef.current?.focus(); // the button that was clicked goes away while the sample is read
      try {
        const draft = await extractApi.createDraft(file, editing ? format.key : undefined, ctrl.signal);
        const required = requiredKeys(draft.checks);
        // Picks, renames and Required flags made before this sample carry over for the fields it still has.
        setFields((prev) => {
          const before = new Map(prev.map((f) => [f.key, f]));
          return draft.fields.map((f) => {
            const next = toField(f, f.picked, required);
            const old = before.get(f.key);
            return old ? { ...next, label: old.label, picked: old.picked, required: old.required } : next;
          });
        });
        setChecks(draft.checks);
        setSample({ draftId: draft.id, fileName: file.name, pages: draft.page_count, asksLeft: draft.asks_left });
        setName((current) => current || draft.name.slice(0, LABEL_MAX));
        setDirty(true);
      } catch (e) {
        if (ctrl.signal.aborted) return;
        setSampleError(apiErrorMessage(e, "We couldn't read this sample. Try another file."));
      } finally {
        if (abortRef.current === ctrl) abortRef.current = null;
        if (!ctrl.signal.aborted) setReading(null);
      }
    },
    [editing, format],
  );

  const { getRootProps, getInputProps, isDragActive, open: chooseFile } = useDropzone({
    onDrop: (files) => files[0] && readSample(files[0]),
    onDropRejected: () => setSampleError("Drop one PDF, PNG or JPG file."),
    accept: ACCEPT,
    multiple: false,
    noClick: true,
    noKeyboard: true,
    disabled: busy,
  });

  async function findMissing(note: string): Promise<string[]> {
    if (!sample) return [];
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const result = await extractApi.askMissing(sample.draftId, note, ctrl.signal);
      const required = requiredKeys(result.checks);
      setFields((prev) => [...prev, ...result.added.map((f) => toField(f, true, required))]);
      setChecks(result.checks);
      setSample({ ...sample, asksLeft: result.asks_left });
      if (result.added.length) {
        setFresh(new Set(result.added.map((f) => f.key)));
        setDirty(true);
      }
      return result.not_found;
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null;
    }
  }

  const setField = (key: string, patch: Partial<BuilderField>) => {
    setFields((prev) => prev.map((f) => (f.key === key ? { ...f, ...patch } : f)));
    change();
  };

  async function ask(title: string, message: string, confirmLabel: string): Promise<boolean> {
    confirming.current = true;
    try {
      return await confirmDialog({ title, message, confirmLabel, danger: true });
    } finally {
      confirming.current = false;
    }
  }

  async function requestClose() {
    if (confirming.current || saving) return;
    if (reading) {
      if (!(await ask("Stop reading this sample?", "The sample is still being read. Close anyway?", "Stop and close")))
        return;
    } else if (dirty || asking) {
      if (!(await ask("Discard your changes?", "This format hasn't been saved.", "Discard"))) return;
    }
    onClose();
  }

  // Escape closes (with the confirm) wherever focus is; a rename's own Escape stops it first.
  const closeRef = useRef(requestClose);
  closeRef.current = requestClose;
  useEffect(() => {
    const onEscape = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || confirming.current) return;
      // Kept from window: a confirm opened by this key would otherwise see it there and close at once.
      e.preventDefault();
      e.stopPropagation();
      closeRef.current();
    };
    document.addEventListener("keydown", onEscape);
    return () => document.removeEventListener("keydown", onEscape);
  }, []);

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "Tab" || !panelRef.current) return;
    const items = Array.from(
      panelRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]):not([type="file"]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ),
    );
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === panelRef.current)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  }

  async function save() {
    if (saving || !picked.length || !name.trim()) return;
    const keys = new Set(picked.map((f) => f.key));
    const body: ExtractFormatInput = {
      ...(sample ? { draft_id: sample.draftId } : {}),
      name: name.trim(),
      description: description.trim(),
      picks: picked.map((f) => ({ key: f.key, label: f.label.trim() || f.original, required: f.required })),
      check_ids: checks
        .filter((c) => c.kind !== "required" && !off.has(c.id) && checkFields(c).every((k) => keys.has(k)))
        .map((c) => c.id),
    };
    setSaving(true);
    setNameError("");
    setSaveError("");
    try {
      const saved =
        editing && !format.builtin
          ? await extractApi.updateFormat(format.key, body)
          : await extractApi.saveFormat(body);
      onSaved(saved);
    } catch (e) {
      const message = apiErrorMessage(e, "Couldn't save the format");
      if (status(e) === 409) setNameError(message);
      else setSaveError(message);
      setSaving(false);
    }
  }

  async function remove() {
    if (!editing || saving) return;
    const reset = format.edited;
    const ok = await ask(
      reset ? "Reset to the original?" : "Delete this format?",
      reset
        ? `Your firm's changes to ${format.name} are removed and the built-in format comes back. Past extracts keep what they used.`
        : `${format.name} is removed for everyone in your firm. Past extracts keep what they used.`,
      reset ? "Reset" : "Delete",
    );
    if (!ok) return;
    setSaving(true);
    setSaveError("");
    try {
      await extractApi.deleteFormat(format.key);
      onDeleted(format);
    } catch (e) {
      setSaveError(apiErrorMessage(e, reset ? "Couldn't reset the format" : "Couldn't delete the format"));
      setSaving(false);
    }
  }

  const dropTitle = !editing
    ? "Drop a sample document"
    : format.builtin
      ? "Drop a sample to make your firm's own version"
      : "Drop a sample to find more fields";
  const canSave = !busy && !locked && picked.length > 0 && !!name.trim();
  const btn = `rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-60 ${FOCUS}`;

  // Portaled to <body> so the app header and Casper can't sit over it; below the confirm dialogs (z-100).
  return createPortal(
    <div
      className="overlay-enter fixed inset-0 z-[90] flex items-stretch justify-center bg-black/40 sm:items-center sm:p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget && !reading) requestClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="extract-builder-title"
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="modal-enter flex h-full w-full flex-col bg-[var(--bg-secondary)] shadow-2xl outline-none sm:h-auto sm:max-h-[90vh] sm:max-w-2xl sm:rounded-xl sm:border sm:border-[var(--border)]"
      >
        <header className="flex items-start gap-3 border-b border-[var(--border)] px-4 py-3 sm:px-5">
          <div className="min-w-0 flex-1">
            <h2 id="extract-builder-title" className="truncate text-base font-semibold text-[var(--text-primary)]">
              {editing ? `Edit ${format.name}` : "Add a format"}
            </h2>
            <p className="text-xs text-[var(--text-secondary)]">
              {editing && format.builtin
                ? "Your firm gets its own copy; the built-in stays as it is."
                : "Pick the fields to read from every document like this one."}
            </p>
          </div>
          <button
            type="button"
            onClick={requestClose}
            disabled={saving}
            aria-label="Close"
            className={`rounded-lg p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] ${FOCUS}`}
          >
            <X size={18} />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-4 py-4 sm:px-5">
          {/* 1. The sample */}
          <section aria-label="Sample document">
            {reading ? (
              <div role="status" aria-live="polite" className="rounded-xl border border-[var(--accent)] bg-[var(--accent-subtle)] px-4 py-5">
                <p className="aa-shimmer text-sm font-semibold">Reading your sample…</p>
                <p className="mt-1 truncate text-xs text-[var(--text-secondary)]">
                  {reading} · {elapsed < 60 ? `${elapsed}s. This can take up to a minute.` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s. Still reading; longer samples take a little more time.`}
                </p>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[var(--border)]">
                  <div
                    className="h-full w-full rounded-full motion-safe:animate-[aa-shimmer_1.6s_linear_infinite]"
                    style={{
                      background: "linear-gradient(90deg, transparent 0%, var(--accent) 50%, transparent 100%)",
                      backgroundSize: "250% 100%",
                    }}
                  />
                </div>
              </div>
            ) : sample ? (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                <FileText size={16} className="shrink-0 text-[var(--text-secondary)]" aria-hidden />
                <span className="min-w-0 truncate text-[var(--text-secondary)]">
                  Read from <span className="font-medium text-[var(--text-primary)]">{sample.fileName}</span>
                  {sample.pages > SAMPLE_PAGES && ` (first ${SAMPLE_PAGES} of ${sample.pages} pages)`}
                </span>
                <button
                  type="button"
                  onClick={chooseFile}
                  disabled={busy}
                  className={`rounded text-sm font-medium text-[var(--accent)] hover:underline disabled:opacity-50 ${FOCUS}`}
                >
                  Use another sample
                </button>
                <input {...getInputProps()} />
              </div>
            ) : (
              <div
                {...getRootProps({
                  className: `flex flex-col items-center rounded-xl border border-dashed text-center transition-colors ${
                    hasFields ? "gap-1 px-4 py-4" : "gap-2 px-4 py-10"
                  } ${isDragActive ? "border-[var(--accent)] bg-[var(--accent-subtle)]" : "border-[var(--border)] bg-[var(--bg-card)]"}`,
                })}
              >
                <input {...getInputProps()} />
                <UploadSimple size={hasFields ? 20 : 28} className="text-[var(--text-secondary)]" aria-hidden />
                <p className="text-sm font-semibold text-[var(--text-primary)]">
                  {isDragActive ? "Drop to read it" : dropTitle}
                </p>
                <p className="text-xs text-[var(--text-secondary)]">
                  {editing && !format.builtin ? "Optional. " : ""}One PDF, PNG or JPG. We read the first {SAMPLE_PAGES} pages.
                </p>
                <button
                  type="button"
                  onClick={chooseFile}
                  className={`mt-1 inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] ${FOCUS}`}
                >
                  <UploadSimple size={16} aria-hidden /> Choose a file
                </button>
              </div>
            )}
            {sampleError && (
              <div role="alert" className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-[var(--alert-error-border)] bg-[var(--alert-error-bg)] px-3 py-2 text-sm text-[var(--alert-error-text)]">
                <span className="min-w-0 flex-1">{sampleError}</span>
                <button type="button" onClick={chooseFile} className={`shrink-0 font-medium underline ${FOCUS}`}>
                  Try another file
                </button>
              </div>
            )}
          </section>

          {/* 2. Fields */}
          {hasFields && (
            <section aria-labelledby="extract-fields-title">
              <h3 id="extract-fields-title" className="mb-1 text-sm font-semibold text-[var(--text-primary)]">
                Fields to read
              </h3>
              <FieldChips
                fields={fields}
                locked={locked || !!reading}
                fresh={fresh}
                onToggle={(key) => {
                  setFields((prev) => prev.map((f) => (f.key === key ? { ...f, picked: !f.picked } : f)));
                  change();
                }}
                onRename={(key, label) => setField(key, { label: label.slice(0, LABEL_MAX) })}
                onRequired={(key, required) => setField(key, { required })}
                onPickAll={() => {
                  setFields((prev) => prev.map((f) => ({ ...f, picked: true })));
                  change();
                }}
                onClear={() => {
                  setFields((prev) => prev.map((f) => ({ ...f, picked: false })));
                  change();
                }}
              />
              {sample && !reading && (
                <MissingFields asksLeft={sample.asksLeft} onFind={findMissing} onBusy={setAsking} />
              )}
            </section>
          )}

          {/* 3. Checks */}
          {hasFields && (
            <CheckList
              checks={checks}
              fields={fields}
              off={off}
              locked={locked || !!reading}
              onToggle={(id) => {
                setOff((prev) => {
                  const next = new Set(prev);
                  if (next.has(id)) next.delete(id);
                  else next.add(id);
                  return next;
                });
                change();
              }}
              onRequired={(key, required) => setField(key, { required })}
            />
          )}

          {/* 4. Name */}
          {hasFields && (
            <section className="grid gap-3 sm:grid-cols-2" aria-label="Name and description">
              <div>
                <label htmlFor="extract-format-name" className="block text-sm font-medium text-[var(--text-primary)]">
                  Name
                </label>
                <input
                  id="extract-format-name"
                  value={name}
                  maxLength={LABEL_MAX}
                  disabled={locked}
                  aria-invalid={!!nameError}
                  aria-describedby={nameError ? "extract-format-name-error" : undefined}
                  onChange={(e) => {
                    setName(e.target.value);
                    setNameError("");
                    change();
                  }}
                  placeholder="e.g. Supplier invoice"
                  className={`mt-1 w-full rounded-lg border bg-[var(--input-bg)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)] disabled:opacity-60 ${
                    nameError ? "border-[var(--alert-error-border)]" : "border-[var(--input-border)]"
                  }`}
                />
                {nameError && (
                  <p id="extract-format-name-error" role="alert" className="mt-1 text-xs text-[var(--alert-error-text)]">
                    {nameError}
                  </p>
                )}
              </div>
              <div>
                <label htmlFor="extract-format-description" className="block text-sm font-medium text-[var(--text-primary)]">
                  Description <span className="font-normal text-[var(--text-tertiary)]">(optional)</span>
                </label>
                <input
                  id="extract-format-description"
                  value={description}
                  maxLength={DESCRIPTION_MAX}
                  disabled={locked}
                  onChange={(e) => {
                    setDescription(e.target.value);
                    change();
                  }}
                  placeholder="What it's for"
                  className="mt-1 w-full rounded-lg border border-[var(--input-border)] bg-[var(--input-bg)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)] disabled:opacity-60"
                />
              </div>
            </section>
          )}
        </div>

        <footer className="border-t border-[var(--border)] px-4 py-3 sm:px-5">
          {saveError && (
            <p role="alert" className="mb-2 text-sm text-[var(--alert-error-text)]">
              {saveError}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {editing && format.edited && (
              <button
                type="button"
                onClick={remove}
                disabled={busy}
                className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-2 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-60 ${FOCUS}`}
              >
                <ArrowCounterClockwise size={16} aria-hidden /> Reset to original
              </button>
            )}
            {editing && !format.builtin && !format.edited && (
              <button
                type="button"
                onClick={remove}
                disabled={busy}
                className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-2 text-sm font-medium text-[var(--error)] hover:bg-[var(--bg-hover)] disabled:opacity-60 ${FOCUS}`}
              >
                <Trash size={16} aria-hidden /> Delete format
              </button>
            )}
            <div className="ml-auto flex gap-2">
              <button
                type="button"
                onClick={requestClose}
                disabled={saving}
                className={`${btn} border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]`}
              >
                Cancel
              </button>
              {hasFields && (
                <button
                  type="button"
                  onClick={save}
                  disabled={!canSave}
                  title={locked ? "Drop a sample first" : !picked.length ? "Pick at least one field" : undefined}
                  className={`${btn} inline-flex items-center gap-1.5 bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)]`}
                >
                  {saving && <Spinner size={14} className="animate-spin" aria-hidden />}
                  {editing ? "Save changes" : "Save format"}
                </button>
              )}
            </div>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
