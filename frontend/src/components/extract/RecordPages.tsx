"use client";

import { useEffect, useMemo, useState } from "react";
import PageViewer, { type FieldBoxes } from "@/components/accounting/PageViewer";
import { extractApi } from "@/lib/extract-api";

const MAX_PAGES = 10;   // pages loaded per record (a longer record shows its first ten)

interface Props {
  fileId: string;
  start: number;
  end: number;
  fields: FieldBoxes;
}

/** A record's pages in the shared viewer (zoom, pinch, field boxes). A page the renderer couldn't give is skipped
 *  (the client already retried a busy renderer once); each image keeps its file page, so boxes stay on theirs. */
export default function RecordPages({ fileId, start, end, fields }: Props) {
  const [loaded, setLoaded] = useState<{ n: number; url: string }[]>([]);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const urls: string[] = [];
    setLoaded([]);
    setFailed(false);
    (async () => {
      for (let p = start; p <= Math.min(end, start + MAX_PAGES - 1); p++) {
        try {
          const blob = await extractApi.pageImage(fileId, p);
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          urls.push(url);
          setLoaded((prev) => [...prev, { n: p, url }]);
        } catch {
          if (!cancelled) setFailed(true);
        }
      }
    })();
    return () => {
      cancelled = true;
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [fileId, start, end]);
  const images = useMemo(() => loaded.map((p) => p.url), [loaded]);
  const pageNumbers = useMemo(() => loaded.map((p) => p.n), [loaded]);
  if (failed && loaded.length === 0) {
    return (
      <p className="flex h-full min-h-[12rem] items-center justify-center rounded-lg border border-[var(--border)] px-4 text-center text-sm text-[var(--text-secondary)]">
        This page couldn&apos;t be shown. Close the record and open it again to retry.
      </p>
    );
  }
  return <PageViewer images={images} pageNumbers={pageNumbers} firstPage={start} fields={fields} className="h-full" />;
}
