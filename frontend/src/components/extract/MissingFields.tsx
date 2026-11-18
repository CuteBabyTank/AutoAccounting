"use client";

import { useEffect, useRef, useState } from "react";
import { Spinner } from "@phosphor-icons/react";
import { apiErrorMessage } from "@/lib/accounting-format";
import { FOCUS } from "@/components/extract/FieldChips";

const NOTE_MAX = 200;

interface Props {
  asksLeft: number;
  /** Look for the named fields on the sample; resolves with the names not found, throws the server's refusal. */
  onFind: (note: string) => Promise<string[]>;
  onBusy: (busy: boolean) => void;
}

/** "Missing fields?": a link that opens a one-line note box for field names the reader missed. Closed by default. */
export default function MissingFields({ asksLeft, onFind, onBusy }: Props) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  if (asksLeft <= 0 && !open) return null;

  async function find() {
    const text = note.trim();
    if (!text || busy) return;
    setBusy(true);
    onBusy(true);
    setError("");
    setNotFound([]);
    try {
      setNotFound(await onFind(text));
      setNote("");
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't look for those fields"));
    } finally {
      setBusy(false);
      onBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`mt-3 rounded text-sm font-medium text-[var(--accent)] underline-offset-2 hover:underline ${FOCUS}`}
      >
        Missing fields?
      </button>
    );
  }

  return (
    <div className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-3">
      <label htmlFor="extract-missing" className="block text-sm font-medium text-[var(--text-primary)]">
        Which fields did we miss?
      </label>
      <form
        className="mt-1.5 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          find();
        }}
      >
        <input
          id="extract-missing"
          ref={inputRef}
          value={note}
          maxLength={NOTE_MAX}
          disabled={busy || asksLeft <= 0}
          placeholder="e.g. PO number, delivery date"
          aria-describedby="extract-missing-help"
          onChange={(e) => setNote(e.target.value.replace(/[\r\n]+/g, " "))}
          className="min-w-0 flex-1 rounded-lg border border-[var(--input-border)] bg-[var(--input-bg)] px-3 py-1.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)] disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={busy || !note.trim() || asksLeft <= 0}
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60 ${FOCUS}`}
        >
          {busy && <Spinner size={14} className="animate-spin" aria-hidden />}
          {busy ? "Looking…" : "Find"}
        </button>
      </form>
      <p id="extract-missing-help" className="mt-1.5 flex flex-wrap justify-between gap-x-3 text-xs text-[var(--text-secondary)]">
        <span>Type only the field names, separated by commas</span>
        <span>{asksLeft === 1 ? "1 try left" : `${asksLeft} tries left`}</span>
      </p>
      {error && (
        <p role="alert" className="mt-2 text-sm text-[var(--alert-error-text)]">
          {error}
        </p>
      )}
      {notFound.length > 0 && (
        <p className="mt-2 text-sm text-[var(--text-secondary)]">Not found on this document: {notFound.join(", ")}</p>
      )}
    </div>
  );
}
