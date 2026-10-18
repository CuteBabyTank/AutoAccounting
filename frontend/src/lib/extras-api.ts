// Workstream 10 extras: recurring entries, write-offs, cash forecast, checklist templates.
import api, { seg } from "@/lib/api";
import type { RecurringEntry, RecurringInput, RecurringPosted } from "@/types/extras";

export const extrasApi = {
  recurring: (companyId: string) =>
    api.get<RecurringEntry[]>(`/accounting/companies/${seg(companyId)}/recurring-entries`).then((r) => r.data),
  createRecurring: (companyId: string, body: RecurringInput) =>
    api.post<RecurringEntry>(`/accounting/companies/${seg(companyId)}/recurring-entries`, body).then((r) => r.data),
  updateRecurring: (id: string, body: RecurringInput) =>
    api.put<RecurringEntry>(`/accounting/recurring-entries/${seg(id)}`, body).then((r) => r.data),
  deleteRecurring: (id: string) => api.delete(`/accounting/recurring-entries/${seg(id)}`).then(() => undefined),
  postRecurring: (id: string) =>
    api.post<RecurringPosted>(`/accounting/recurring-entries/${seg(id)}/post`).then((r) => r.data),
};
