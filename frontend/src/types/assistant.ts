import type { SearchItem } from "@/types/search";

export interface AssistantUsage {
  prompt: number;
  completion: number;
  cached: number;
  calls: number;
}

export interface AssistantDailyUsage {
  turns: number;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
}

/** One server-sent event of an assistant turn (backend `services/accounting/assistant/loop.py`). */
export type AssistantEvent =
  | { type: "start" }
  | { type: "thought"; text: string }
  | { type: "clarify"; question: string; replies?: string[]; usage?: AssistantUsage }
  | { type: "action"; tool: string; args: Record<string, unknown>; label?: string }
  | { type: "observation"; tool: string; ok: boolean; summary: string }
  | {
      type: "final";
      usage?: AssistantUsage;
      answer: string;
      sources: SearchItem[];
      tools_used: string[];
      grounded: boolean;
      ungrounded_numbers: string[];
      /** One-tap answers when it ends by asking something: "Yes", or the companies to choose from. */
      replies?: string[];
    }
  | { type: "error"; message: string; usage?: AssistantUsage }
  /** Casper proposes one change; nothing happens until the person presses Confirm. */
  | { type: "proposal"; action: AssistantAction };

export type AssistantActionStatus = "proposed" | "applied" | "failed" | "cancelled" | "expired" | "undone";

/** A change Casper proposed (backend `aa_assistant_actions`). Undo / restore is open until `undo_until`. */
export interface AssistantAction {
  id: string;
  kind: string;
  summary: string;
  details: { label: string; value: string }[];
  destructive: boolean;
  status: AssistantActionStatus;
  error: string;
  company_name: string;
  created_at: string;
  expires_at: string;
  applied_at: string | null;
  undo_until: string | null;
  undone_at: string | null;
  can_confirm: boolean;
  can_undo: boolean;
  user_name: string;
}

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
  replies?: string[];
  error?: boolean;
  pending?: boolean;
  /** Casper asking whether a question is about the company open on screen (answered with one click). */
  ask?: { companyId: string; companyName: string; question: string; answered?: "yes" | "no" | "other" };
  /** Changes Casper proposed in this answer, kept current after Confirm / Undo. */
  actions?: AssistantAction[];
}

export interface AssistantInfo {
  model: string;
  provider: string;
  ready: boolean;
  local: boolean;
  day?: string;
  usage?: { user: AssistantDailyUsage; firm?: AssistantDailyUsage };
  caps?: { user: number; firm: number };
  /** Whether this person may turn on write mode; `reason` says why not. */
  write?: { allowed: boolean; reason: string };
}
