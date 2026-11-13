export type UserRole = "admin" | "enterprise" | "manager" | "employee" | "unverified";

export interface User {
  id: string;
  email: string;
  nickname?: string | null;
  /** Profile picture as a data: URI (small WebP). */
  avatar?: string | null;
  role: UserRole;
  organization_name?: string | null;
  is_active: boolean;
  enterprise_id?: string | null;
  pages_used?: number | null;
  budget?: number | null;
  created_at: string;
}

/** A member of the caller's firm (Team page). */
export interface Member {
  id: string;
  email: string;
  nickname?: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  /** What this person can use (Team page); empty = full access, no level = the firm's Casper default. */
  access?: MemberAccess;
  access_summary?: string;
  can_edit_access?: boolean;
}

export type AssistantLevel = "off" | "read" | "write";

export interface MemberAccess {
  off: string[];
  assistant?: AssistantLevel | null;
}

/** One area a firm owner can turn on or off for a person. */
export interface AccessArea {
  key: string;
  label: string;
  group: string;
  description: string;
}

export interface FirmUsage {
  organization_name?: string | null;
  pages_used: number;
  year: number;
  month: number;
  budget: number;
  billing_enabled: boolean;
}

/** One row of the platform-admin account list. */
export interface Account {
  id: string;
  email: string;
  nickname?: string | null;
  role: UserRole;
  is_active: boolean;
  organization_name?: string | null;
  enterprise_id?: string | null;
  enterprise_email?: string | null;
  pages_used: number;
  budget: number;
  created_at: string;
}

export type BudgetOperation = "add" | "subtract" | "set";

/** Platform admin's maintenance switches: global state per feature, and each firm's overrides. */
export interface AdminFeatures {
  features: { key: string; label: string; group: string; description: string; enabled: boolean }[];
  overrides: Record<string, Record<string, boolean>>;
}

/** One firm's Extract format as the platform admin sees it (read only). */
export interface AdminExtractFormat {
  id: string;
  firm: string;
  name: string;
  base_key: string | null;
  version: number;
  deleted: boolean;
  updated_at: string | null;
  updated_by: string;
  fields: { key: string; label: string; type: string; scope: "header" | "row"; required: boolean; description: string }[];
  checks: { id: string; kind: string; level: "red" | "yellow"; sentence: string }[];
  prompt: string;
}
