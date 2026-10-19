export type UserRole = "admin" | "enterprise" | "manager" | "employee" | "unverified";

export interface User {
  id: string;
  email: string;
  nickname?: string | null;
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
