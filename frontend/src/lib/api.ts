import axios from "axios";
import type { Account, AdminFeatures, BudgetOperation, FirmUsage, Member, UserRole } from "@/types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Encode one interpolated URL path segment, so an id can never add path parts ("../", "?", "#"). */
export const seg = (value: string | number): string => encodeURIComponent(value);

export const TOKEN_KEY = "autoaccounting_token";

const api = axios.create({
  baseURL: `${API_URL}/api`,
});

api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Graceful 429 handling: a burst of edits can briefly trip the per-user
    // rate limit. Retry once after a short, capped backoff so a transient spike
    // doesn't surface as a failed action. Honors Retry-After but caps the wait.
    const config = error.config as
      | (typeof error.config & { _retried429?: boolean })
      | undefined;
    if (error.response?.status === 429 && config && !config._retried429) {
      config._retried429 = true;
      const retryAfter = Number(error.response.headers?.["retry-after"]);
      const waitMs = Math.min(Number.isFinite(retryAfter) ? retryAfter : 1, 5) * 1000;
      await new Promise((resolve) => setTimeout(resolve, waitMs));
      return api(config);
    }
    // A file request (responseType "blob") gets its JSON error back as a Blob: parse it so callers see `detail`.
    const data = error.response?.data;
    if (typeof Blob !== "undefined" && data instanceof Blob && data.type.includes("json")) {
      try {
        error.response.data = JSON.parse(await data.text());
      } catch {
        // leave the Blob; callers fall back to their own message
      }
    }
    // A feature the platform admin just switched off: re-read the switches so its screens hide.
    if (error.response?.status === 503 && typeof window !== "undefined") {
      const detail = (error.response.data as { detail?: unknown } | undefined)?.detail;
      if (typeof detail === "string" && detail.includes("turned off for maintenance")) {
        window.dispatchEvent(new Event("aa:features-stale"));
      }
    }
    if (error.response?.status === 401 && typeof window !== "undefined") {
      sessionStorage.removeItem(TOKEN_KEY);
      // Don't hard-redirect here — AuthGate handles routing.
    }
    return Promise.reject(error);
  }
);

export default api;

/** Firm staff (owner + managers). */
export const teamApi = {
  usage: () => api.get<FirmUsage>("/team/usage").then((r) => r.data),
  members: () => api.get<Member[]>("/team/members").then((r) => r.data),
  add: (email: string) => api.post<Member>("/team/members", { email }).then((r) => r.data),
  setActive: (id: string, is_active: boolean) =>
    api.put<Member>(`/team/members/${seg(id)}`, { is_active }).then((r) => r.data),
  remove: (id: string) => api.delete(`/team/members/${seg(id)}`).then(() => undefined),
  promote: (id: string) => api.post<Member>(`/team/members/${seg(id)}/promote-manager`).then((r) => r.data),
  demote: (id: string) => api.post<Member>(`/team/members/${seg(id)}/demote`).then((r) => r.data),
};

/** Platform admin. */
export const adminApi = {
  accounts: () => api.get<Account[]>("/admin/accounts").then((r) => r.data),
  promoteFirm: (id: string, organization_name: string) =>
    api.post(`/admin/users/${seg(id)}/promote-firm`, { organization_name }).then((r) => r.data),
  setRole: (id: string, role: Exclude<UserRole, "admin">, enterprise_id?: string) =>
    api.put(`/admin/users/${seg(id)}/role`, { role, enterprise_id }).then((r) => r.data),
  toggleActive: (id: string) => api.put(`/admin/users/${seg(id)}/toggle-active`).then((r) => r.data),
  pageRate: () => api.get<{ page_rate: number | null }>("/admin/page-rate").then((r) => r.data),
  setPageRate: (page_rate: number | null) =>
    api.put<{ page_rate: number | null }>("/admin/page-rate", { page_rate }).then((r) => r.data),
  adjustBudget: (firmId: string, operation: BudgetOperation, amount: number) =>
    api.post<{ budget: number }>(`/admin/firms/${seg(firmId)}/budget`, { operation, amount }).then((r) => r.data),
  features: () => api.get<AdminFeatures>("/admin/features").then((r) => r.data),
  setFeature: (key: string, enabled: boolean) =>
    api.put<AdminFeatures>(`/admin/features/${seg(key)}`, { enabled }).then((r) => r.data),
  setFirmFeature: (firmId: string, key: string, enabled: boolean | null) =>
    api.put<AdminFeatures>(`/admin/firms/${seg(firmId)}/features/${seg(key)}`, { enabled }).then((r) => r.data),
  allFeaturesOn: () => api.post<AdminFeatures>("/admin/features/all-on").then((r) => r.data),
};

