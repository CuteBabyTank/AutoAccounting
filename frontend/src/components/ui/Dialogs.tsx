"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

// In-app replacements for window.confirm / window.prompt: `await confirmDialog({...})` resolves true / false,
// `await promptDialog({...})` the typed text or null. <DialogHost /> is mounted once in Providers; requests queue.

type Base = { title: string; message?: string; confirmLabel?: string; cancelLabel?: string; danger?: boolean };
export type ConfirmOptions = Base;
export type PromptOptions = Base & { defaultValue?: string; placeholder?: string; inputMode?: "text" | "decimal" };

type Request = { id: number } & (
  | { kind: "confirm"; options: ConfirmOptions; resolve: (ok: boolean) => void }
  | { kind: "prompt"; options: PromptOptions; resolve: (value: string | null) => void }
);

let queue: Request[] = [];
let nextId = 0;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function push(request: Omit<Request, "id">) {
  queue = [...queue, { ...request, id: ++nextId } as Request];
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => push({ kind: "confirm", options, resolve }));
}

export function promptDialog(options: PromptOptions): Promise<string | null> {
  return new Promise((resolve) => push({ kind: "prompt", options, resolve }));
}

const BTN = "rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-60";

export function DialogHost() {
  const current = useSyncExternalStore(subscribe, () => queue[0], () => undefined);
  if (!current) return null;
  // Keyed per request so the input's value and focus start fresh for each one.
  return <Dialog key={current.id} request={current} />;
}

function Dialog({ request }: { request: Request }) {
  const { options } = request;
  const [value, setValue] = useState(request.kind === "prompt" ? (request.options.defaultValue ?? "") : "");
  const confirmRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const close = (ok: boolean) => {
    queue = queue.slice(1);
    if (request.kind === "confirm") request.resolve(ok);
    else request.resolve(ok ? value : null);
    emit();
  };

  useEffect(() => {
    const restore = document.activeElement as HTMLElement | null;
    if (inputRef.current) inputRef.current.select();
    else confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      restore?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4" onClick={() => close(false)}>
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="aa-dialog-title"
        aria-describedby={options.message ? "aa-dialog-message" : undefined}
        onClick={(e) => e.stopPropagation()}
        className="page-enter w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-5 shadow-2xl"
      >
        <h2 id="aa-dialog-title" className="text-base font-semibold text-[var(--text-primary)]">
          {options.title}
        </h2>
        {options.message && (
          <p id="aa-dialog-message" className="mt-1.5 text-sm leading-relaxed text-[var(--text-secondary)]">
            {options.message}
          </p>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            close(true);
          }}
        >
          {request.kind === "prompt" && (
            <input
              ref={inputRef}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={request.options.placeholder}
              inputMode={request.options.inputMode}
              aria-labelledby="aa-dialog-title"
              className="mt-3 w-full rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
            />
          )}
          <div className="mt-5 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => close(false)}
              className={`${BTN} border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]`}
            >
              {options.cancelLabel ?? "Cancel"}
            </button>
            <button
              ref={confirmRef}
              type="submit"
              className={`${BTN} text-white ${
                options.danger ? "bg-[var(--error)] hover:opacity-90" : "bg-[var(--accent)] hover:bg-[var(--accent-hover)]"
              }`}
            >
              {options.confirmLabel ?? "OK"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
