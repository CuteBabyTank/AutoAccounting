import type { SearchItem } from "@/types/search";

/** One server-sent event of an assistant turn (backend `services/accounting/assistant/loop.py`). */
export type AssistantEvent =
  | { type: "start" }
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

export interface AssistantStep {
  tool: string;
  summary: string;
  ok: boolean | null; // null while it runs
}

export interface AssistantMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  steps?: AssistantStep[];
  sources?: SearchItem[];
  ungrounded?: string[];
  clarification?: boolean;
  error?: boolean;
  pending?: boolean;
}
