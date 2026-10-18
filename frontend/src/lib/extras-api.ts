// Workstream 10 extras: recurring entries, write-offs, cash forecast, checklist templates.
import api, { seg } from "@/lib/api";
import type { CashForecast, RecurringEntry, RecurringInput, RecurringPosted, WriteOffCandidates, WriteOffResult } from "@/types/extras";

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
  writeOffCandidates: (companyId: string, params: { as_of: string; min_days: number; max_balance?: string }) =>
    api.get<WriteOffCandidates>(`/accounting/companies/${seg(companyId)}/writeoffs/candidates`, { params }).then((r) => r.data),
  writeOff: (companyId: string, body: { entry_date: string; item_ids: string[]; account: string; reason: string }) =>
    api.post<WriteOffResult>(`/accounting/companies/${seg(companyId)}/writeoffs`, body).then((r) => r.data),
  cashForecast: (companyId: string, params: { as_of?: string; weeks?: number } = {}) =>
    api.get<CashForecast>(`/accounting/companies/${seg(companyId)}/cash-forecast`, { params }).then((r) => r.data),
};
