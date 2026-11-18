// The assistant's chat turn is a server-sent event stream, so it uses fetch (axios can't read a stream in the browser).
import api, { API_URL, TOKEN_KEY } from "@/lib/api";
import { markFeaturesStale } from "@/lib/features";
import type { AssistantAction, AssistantEvent, AssistantInfo } from "@/types/assistant";

/** The model answering (shown in the composer). */
export async function assistantInfo(): Promise<AssistantInfo> {
  return (await api.get<AssistantInfo>("/accounting/assistant/info")).data;
}

/** "qwen3:4b-instruct" → "Qwen3 4B Instruct"; a hosted name like "qwen-plus" → "Qwen Plus". */
export function modelLabel(model: string): string {
  return model
    .replace(/^[a-z0-9-]+\//i, "") // a router's vendor prefix: "qwen/qwen3.7-flash"
    .split(/[:\-_/]+/)
    .filter(Boolean)
    .map((w) => (/^\d+[a-z]$/i.test(w) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}

export interface HistoryMessage {
  role: "user" | "assistant";
  text: string;
}

/** Messages the server reads back (it keeps the newest that fit its own budget). */
export const HISTORY_SENT = 12;
export const ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024;
export const ATTACHMENT_ACCEPT = ".xlsx,.pdf,.jpg,.jpeg,.heic";

export function attachmentError(files: File[]): string | null {
  if (files.length > 5) return "Attach at most 5 files per message.";
  if (files.some((file) => !/\.(xlsx|pdf|jpe?g|heic)$/i.test(file.name))) {
    return "Choose XLSX, PDF, JPG/JPEG or HEIC files.";
  }
  if (files.some((file) => file.size === 0)) return "Empty files can't be attached.";
  if (files.reduce((sum, file) => sum + file.size, 0) > ATTACHMENT_MAX_BYTES) {
    return "Attachments must total at most 5 MB per message.";
  }
  return null;
}

async function encodeAttachment(file: File): Promise<{ name: string; data: string }> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 8192) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  }
  return { name: file.name, data: btoa(binary) };
}

async function errorText(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // not JSON
  }
  return "The assistant couldn't answer just now. Please try again.";
}

/** Run one turn; each parsed event goes to `onEvent`. Resolves when the stream ends. */
export async function streamChat(
  question: string,
  history: HistoryMessage[],
  onEvent: (e: AssistantEvent) => void,
  signal: AbortSignal,
  write = false,
  companyId: string | null = null,
  files: File[] = [],
): Promise<void> {
  const invalid = attachmentError(files);
  if (invalid) throw new Error(invalid);
  const token = typeof window !== "undefined" ? sessionStorage.getItem(TOKEN_KEY) : null;
  const attachments = await Promise.all(files.map(encodeAttachment));
  signal.throwIfAborted();
  if (typeof window !== "undefined" && sessionStorage.getItem(TOKEN_KEY) !== token) {
    throw new Error("Your account changed while preparing the message. Send it again from the current account.");
  }
  const res = await fetch(`${API_URL}/api/accounting/assistant/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ question, history: history.slice(-HISTORY_SENT), write,
      ...(attachments.length ? { attachments } : {}), ...(companyId ? { company_id: companyId } : {}) }),
    signal,
  });
  if (!res.ok || !res.body) {
    if (res.status === 401) sessionStorage.removeItem(TOKEN_KEY);
    const message = await errorText(res);
    if (res.status === 503 && message.includes("turned off for maintenance")) markFeaturesStale();
    onEvent({ type: "error", message });
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      for (const line of frame.split("\n")) {
        if (!line.startsWith("data:")) continue;
        try {
          onEvent(JSON.parse(line.slice(5).trim()) as AssistantEvent);
        } catch {
          // a malformed frame: skip it
        }
      }
    }
  }
}

/** Run a proposed change (the stored, server-checked version of what the card shows). */
export async function confirmAction(id: string): Promise<AssistantAction> {
  return (await api.post<AssistantAction>(`/accounting/assistant/actions/${id}/confirm`)).data;
}

export async function cancelAction(id: string): Promise<AssistantAction> {
  return (await api.post<AssistantAction>(`/accounting/assistant/actions/${id}/cancel`)).data;
}

/** Undo a change, or restore what it deleted (within 7 days). */
export async function undoAction(id: string): Promise<AssistantAction> {
  return (await api.post<AssistantAction>(`/accounting/assistant/actions/${id}/undo`)).data;
}

/** Casper's changes in the last 7 days, newest first. */
export async function listActions(): Promise<AssistantAction[]> {
  return (await api.get<AssistantAction[]>("/accounting/assistant/actions")).data;
}
