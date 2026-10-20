import type { SearchItem } from "@/types/search";

/** One server-sent event of an assistant turn (backend `services/accounting/assistant/loop.py`). */
export type AssistantEvent =
  | { type: "start" }
  | { type: "thought"; text: string }
  | { type: "clarify"; question: string }
  | { type: "action"; tool: string; args: Record<string, unknown>; label?: string }
  | { type: "observation"; tool: string; ok: boolean; summary: string }
  | {
      type: "final";
      answer: string;
      sources: SearchItem[];
      tools_used: string[];
      grounded: boolean;
      ungrounded_numbers: string[];
    }
  | { type: "error"; message: string };

/** One line of the thinking trail: the model's plan, a lookup, or the figure check at the end. */
export interface AssistantStep {
  kind?: "thought" | "tool" | "check";
  tool: string;
  /** While running: what it's doing now; once done: what came back. */
  summary: string;
  ok: boolean | null; // null while it runs
}

export interface AssistantMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  at?: number;          // when it was sent / when the answer began (ms)
  doneAt?: number;      // when the answer finished (ms)
  model?: string;
  steps?: AssistantStep[];
  sources?: SearchItem[];
  ungrounded?: string[];
  clarification?: boolean;
  error?: boolean;
  pending?: boolean;
}

export interface AssistantInfo {
  model: string;
  provider: string;
  ready: boolean;
  local: boolean;
}
