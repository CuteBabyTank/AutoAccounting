// Work board, client health, tasks, firm settings and notifications.
import api, { seg } from "@/lib/api";
import type {
  AutoAssignResult,
  WorkHistory,
  WorkHistoryFilters,
  Board,
  BoardFilters,
  CompanyHealth,
  FirmSettings,
  Notifications,
  Person,
  Task,
  TaskFilters,
  TaskInput,
  WorkCard,
  WorkItemInput,
} from "@/types/work";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A company id taken from a URL or an event: only a UUID is accepted (anything else is ignored). */
export function safeId(value: unknown): string | null {
  return typeof value === "string" && UUID_RE.test(value) ? value.toLowerCase() : null;
}

export const workApi = {
  board: (filters: BoardFilters) => api.get<Board>("/accounting/work/board", { params: filters }).then((r) => r.data),
  /** Only the keys present are changed (null assignee unassigns, "" status goes back to automatic). */
  updateItem: (body: WorkItemInput) => api.put<WorkCard>("/accounting/work/items", body).then((r) => r.data),
  setHandler: (companyId: string, handlerId: string | null) =>
    api.put<{ handler_id: string | null }>(`/accounting/work/companies/${seg(companyId)}/handler`, { handler_id: handlerId }).then((r) => r.data),
  autoAssign: (filters: Pick<BoardFilters, "start" | "end" | "company_id">) =>
    api.post<AutoAssignResult>("/accounting/work/auto-assign", null, { params: filters }).then((r) => r.data),
  history: (filters: WorkHistoryFilters) =>
    api.get<WorkHistory>("/accounting/work/history", { params: filters }).then((r) => r.data),
  people: () => api.get<Person[]>("/accounting/work/people").then((r) => r.data),
  settings: () => api.get<FirmSettings>("/accounting/work/settings").then((r) => r.data),
  saveSettings: (body: Partial<Pick<FirmSettings, "organization_name" | "approve_before_close" | "deadline_days" | "auto_assign">>) =>
    api.put<FirmSettings>("/accounting/work/settings", body).then((r) => r.data),
  health: (companyId: string) =>
    api.get<CompanyHealth>(`/accounting/companies/${seg(companyId)}/health`).then((r) => r.data),
  tasks: (filters: TaskFilters) => api.get<Task[]>("/accounting/tasks", { params: filters }).then((r) => r.data),
  createTask: (body: TaskInput) => api.post<Task>("/accounting/tasks", body).then((r) => r.data),
  updateTask: (id: string, body: Partial<TaskInput>) =>
    api.patch<Task>(`/accounting/tasks/${seg(id)}`, body).then((r) => r.data),
  deleteTask: (id: string) => api.delete(`/accounting/tasks/${seg(id)}`),
  notifications: () => api.get<Notifications>("/accounting/notifications").then((r) => r.data),
  readNotifications: (keys: string[], all = false) =>
    api.post<Notifications>("/accounting/notifications/read", { keys, all }).then((r) => r.data),
  dismissNotifications: (keys: string[], all = false) =>
    api.post<Notifications>("/accounting/notifications/dismiss", { keys, all }).then((r) => r.data),
};

/** Firm settings are read in several panels (filing buttons); fetch once per page load. */
let settingsCache: Promise<FirmSettings> | null = null;
export function firmSettings(refresh = false): Promise<FirmSettings> {
  if (!settingsCache || refresh) {
    settingsCache = workApi.settings().catch((e) => {
      settingsCache = null;
      throw e;
    });
  }
  return settingsCache;
}

/** The Documents page listens for this to open a company's Overview without a reload. */
export const OPEN_COMPANY_EVENT = "aa:open-company";
