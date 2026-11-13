"use client";

import { useEffect, useState } from "react";
import { CaretLeft, CaretRight, MagnifyingGlassMinus, MagnifyingGlassPlus, Spinner } from "@phosphor-icons/react";
import { extractApi } from "@/lib/extract-api";

interface Props {
  fileId: string;
  start: number;
  end: number;
}

type Shown = { status: "loading" } | { status: "error"; message: string } | { status: "ok"; url: string };

/** The record's pages, one at a time (the client retries a busy renderer once; then Retry is offered). */
export default function PageViewer({ fileId, start, end }: Props) {
  const [page, setPage] = useState(start);
  const [attempt, setAttempt] = useState(0);
  const [zoom, setZoom] = useState(false);
  const [shown, setShown] = useState<Shown>({ status: "loading" });
  const current = Math.min(Math.max(page, start), end);

  useEffect(() => {
    let alive = true;
    let url = "";
    setShown({ status: "loading" });
    extractApi
      .pageImage(fileId, current)
      .then((blob) => {
        if (!alive) return;
        url = URL.createObjectURL(blob);
        setShown({ status: "ok", url });
      })
      .catch((e: { response?: { status?: number } }) => {
        if (!alive) return;
        const busy = e?.response?.status === 503;
        setShown({ status: "error", message: busy ? "The page viewer is busy right now." : "This page couldn't be shown." });
      });
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [fileId, current, attempt]);

  const many = end > start;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 pb-2 text-xs text-[var(--text-secondary)]">
        {many ? (
          <>
            <button type="button" aria-label="Previous page" disabled={current <= start}
              onClick={() => setPage(current - 1)}
              className="rounded-md border border-[var(--border)] p-1 hover:bg-[var(--bg-hover)] disabled:opacity-40">
              <CaretLeft size={12} />
            </button>
            <span className="tabular-nums">Page {current} ({current - start + 1} of {end - start + 1})</span>
            <button type="button" aria-label="Next page" disabled={current >= end}
              onClick={() => setPage(current + 1)}
              className="rounded-md border border-[var(--border)] p-1 hover:bg-[var(--bg-hover)] disabled:opacity-40">
              <CaretRight size={12} />
            </button>
          </>
        ) : (
          <span className="tabular-nums">Page {current}</span>
        )}
        <button type="button" onClick={() => setZoom((z) => !z)} aria-pressed={zoom}
          aria-label={zoom ? "Fit the page" : "Zoom in"}
          className="ml-auto rounded-md border border-[var(--border)] p-1 hover:bg-[var(--bg-hover)]">
          {zoom ? <MagnifyingGlassMinus size={12} /> : <MagnifyingGlassPlus size={12} />}
        </button>
      </div>
      <div className="min-h-[12rem] flex-1 overflow-auto rounded-lg border border-[var(--border)] bg-[var(--bg-primary)]">
        {shown.status === "loading" && (
          <p className="flex h-full min-h-[12rem] items-center justify-center gap-2 text-sm text-[var(--text-secondary)]">
            <Spinner size={14} className="animate-spin" /> Loading page
          </p>
        )}
        {shown.status === "error" && (
          <div className="flex h-full min-h-[12rem] flex-col items-center justify-center gap-2 px-4 text-center text-sm text-[var(--text-secondary)]">
            <p>{shown.message}</p>
            <button type="button" onClick={() => setAttempt((n) => n + 1)}
              className="rounded-lg border border-[var(--border)] px-3 py-1 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]">
              Retry
            </button>
          </div>
        )}
        {shown.status === "ok" && (
          // eslint-disable-next-line @next/next/no-img-element -- a blob URL of the page, not a static asset
          <img src={shown.url} alt={`Page ${current}`} className={zoom ? "max-w-none w-[200%]" : "w-full"} />
        )}
      </div>
    </div>
  );
}
