"use client";

import { useEffect, useState } from "react";
import { firmSettings } from "@/lib/work-api";

export const FILING_LOCKED_TITLE = "Your firm has managers approve filings: a manager or the firm owner marks returns filed.";

/** False when the firm requires managers to mark returns filed and this person isn't one (the API enforces it too). */
export function useCanFile(): boolean {
  const [canFile, setCanFile] = useState(true);
  useEffect(() => {
    firmSettings().then((s) => setCanFile(s.can_file)).catch(() => undefined);
  }, []);
  return canFile;
}
