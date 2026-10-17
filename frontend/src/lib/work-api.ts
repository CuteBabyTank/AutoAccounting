// Work board, client health, tasks, firm settings and notifications.
import api from "@/lib/api";
import type {
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

export const workApi = {
  board: (filters: BoardFilters) => api.get<Board>("/accounting/work/board", { params: filters }).then((r) => r.data),
  /** Only the keys present are changed (null assignee unassigns, "" status goes back to automatic). */
  updateItem: (body: WorkItemInput) => api.put<WorkCard>("/accounting/work/items", body).then((r) => r.data),
  people: () => api.get<Person[]>("/accounting/work/people").then((r) => r.data),
  settings: () => api.get<FirmSettings>("/accounting/work/settings").then((r) => r.data),
  saveSettings: (body: { approve_before_close: boolean; deadline_days: number }) =>
    api.put<FirmSettings>("/accounting/work/settings", body).then((r) => r.data),
  health: (companyId: string) =>
    api.get<CompanyHealth>(`/accounting/companies/${companyId}/health`).then((r) => r.data),
  tasks: (filters: TaskFilters) => api.get<Task[]>("/accounting/tasks", { params: filters }).then((r) => r.data),
  createTask: (body: TaskInput) => api.post<Task>("/accounting/tasks", body).then((r) => r.data),
  updateTask: (id: string, body: Partial<TaskInput>) =>
    api.patch<Task>(`/accounting/tasks/${id}`, body).then((r) => r.data),
  deleteTask: (id: string) => api.delete(`/accounting/tasks/${id}`),
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
