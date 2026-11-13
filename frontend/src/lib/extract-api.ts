// Extract tab client (backend routers/accounting_extract.py, under /api/accounting/extract).
import api, { seg } from "@/lib/api";
import type { WorkbookSheet } from "@/types/accounting";
import type {
  ExtractDraft,
  ExtractEdit,
  ExtractFile,
  ExtractFormat,
  ExtractFormatInput,
  ExtractMissingResult,
  ExtractRecord,
  ExtractRecordPage,
  ExtractRun,
  ExtractRunSummary,
} from "@/types/extract";

const BASE = "/accounting/extract";
const MULTIPART = { headers: { "Content-Type": "multipart/form-data" } };

export const extractApi = {
  /** Built-ins first (an edited one in its place), then the firm's own formats by name. */
  formats: () => api.get<ExtractFormat[]>(`${BASE}/formats`).then((r) => r.data),
  /** Read a sample and propose a format; `formatKey` merges it onto an existing format (editing). Managers only. */
  createDraft: (file: File, formatKey?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (formatKey) fd.append("format_key", formatKey);
    return api.post<ExtractDraft>(`${BASE}/drafts`, fd, MULTIPART).then((r) => r.data);
  },
  askMissing: (draftId: string, note: string) =>
    api.post<ExtractMissingResult>(`${BASE}/drafts/${seg(draftId)}/missing`, { note }).then((r) => r.data),
  saveFormat: (body: ExtractFormatInput) => api.post<ExtractFormat>(`${BASE}/formats`, body).then((r) => r.data),
  updateFormat: (id: string, body: ExtractFormatInput) =>
    api.put<ExtractFormat>(`${BASE}/formats/${seg(id)}`, body).then((r) => r.data),
  /** Delete a firm format; for the firm's copy of a built-in this resets it to the original. */
  deleteFormat: (id: string) => api.delete(`${BASE}/formats/${seg(id)}`).then(() => undefined),

  /** Drop files against a format key or "auto"; they are read in the background. */
  createRun: (files: File[], formatKey: string) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("format_key", formatKey);
    return api.post<{ id: string }>(`${BASE}/runs`, fd, MULTIPART).then((r) => r.data);
  },
  runs: () => api.get<ExtractRunSummary[]>(`${BASE}/runs`).then((r) => r.data),
  run: (id: string) => api.get<ExtractRun>(`${BASE}/runs/${seg(id)}`).then((r) => r.data),
  /** One page of a run's records (limit at most 200); `formatKey` is needed when the run used several formats. */
  records: (runId: string, opts: { formatKey?: string; offset?: number; limit?: number; reviewOnly?: boolean } = {}) =>
    api
      .get<ExtractRecordPage>(`${BASE}/runs/${seg(runId)}/records`, {
        params: {
          ...(opts.formatKey ? { format_key: opts.formatKey } : {}),
          offset: opts.offset ?? 0,
          limit: opts.limit ?? 100,
          ...(opts.reviewOnly ? { review_only: true } : {}),
        },
      })
      .then((r) => r.data),
  editRecord: (id: string, edits: ExtractEdit[]) =>
    api.patch<ExtractRecord>(`${BASE}/records/${seg(id)}`, { edits }).then((r) => r.data),
  /** Pick the format for a file auto detect wasn't sure about (status "choose"). */
  pickFileFormat: (fileId: string, formatKey: string) =>
    api.put<ExtractFile>(`${BASE}/files/${seg(fileId)}/format`, { format_key: formatKey }).then((r) => r.data),
  deleteRun: (id: string) => api.delete(`${BASE}/runs/${seg(id)}`).then(() => undefined),
  pageImage: async (fileId: string, page: number): Promise<Blob> => {
    const get = () =>
      api.get<Blob>(`${BASE}/files/${seg(fileId)}/pages/${seg(page)}`, { responseType: "blob" }).then((r) => r.data);
    try {
      return await get();
    } catch (err) {
      // 503 = the renderer was momentarily full; one short retry, then let the caller show its blank state.
      if ((err as { response?: { status?: number } })?.response?.status !== 503) throw err;
      await new Promise((resolve) => setTimeout(resolve, 600 + Math.random() * 400));
      return get();
    }
  },
  /** The run's records of one format as a workbook (opened in WorkbookPreview first). */
  xlsx: (runId: string, formatKey?: string) =>
    api
      .get<Blob>(`${BASE}/runs/${seg(runId)}/xlsx`, {
        params: formatKey ? { format_key: formatKey } : {},
        responseType: "blob",
      })
      .then((r) => r.data),
  xlsxPreview: (runId: string, formatKey?: string) =>
    api
      .get<{ sheets: WorkbookSheet[] }>(`${BASE}/runs/${seg(runId)}/xlsx`, {
        params: { ...(formatKey ? { format_key: formatKey } : {}), preview: true },
      })
      .then((r) => r.data.sheets),
};
