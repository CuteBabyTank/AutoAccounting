// Accounting API client (companies, uploads, periods, books). Auth/team/admin calls live in lib/api.ts.
import api from "@/lib/api";
import type {
  AADocument,
  Account,
  AnnualInputs,
  AnnualPeriod,
  Asset,
  AssetPatch,
  OpeningAssetInput,
  AtcDatabank,
  AuditFilters,
  AuditPage,
  BankConfirm,
  BankMonth,
  BankOverview,
  BankRule,
  BankStatement,
  ReconcileResult,
  Company,
  CompanyInput,
  ConfirmAssignment,
  DocumentPatch,
  DuplicatePair,
  AlphalistStatus,
  BooksYear,
  EmployeeData,
  EmployeesYear,
  PayrollImport,
  PayrollPreview,
  JournalEntry,
  JournalEntryInput,
  PaymentLinks,
  Folder,
  Output,
  Period,
  PeriodInputs,
  Prepare,
  Scope,
  TreeCompany,
  Upload,
} from "@/types/accounting";

export const accountingApi = {
  // Bank statements: lines, matches, reconciliation
  bankOverview: (companyId: string) =>
    api.get<BankOverview>(`/accounting/companies/${companyId}/bank`).then((r) => r.data),
  bankMonth: (companyId: string, account: string, month: string) =>
    api.get<BankMonth>(`/accounting/companies/${companyId}/bank/lines`, { params: { account, month } }).then((r) => r.data),
  confirmBankLine: (lineId: string, body: BankConfirm = {}) =>
    api.post<BankMonth>(`/accounting/bank-lines/${lineId}/confirm`, body).then((r) => r.data),
  rejectBankLine: (lineId: string, reason = "") =>
    api.post<BankMonth>(`/accounting/bank-lines/${lineId}/reject`, { reason }).then((r) => r.data),
  excludeBankLine: (lineId: string, reason = "") =>
    api.post<BankMonth>(`/accounting/bank-lines/${lineId}/exclude`, { reason }).then((r) => r.data),
  rematchBank: (companyId: string) =>
    api.post<BankOverview>(`/accounting/companies/${companyId}/bank/rematch`).then((r) => r.data),
  setStatementAccount: (statementId: string, accountCode: string) =>
    api.patch<BankStatement>(`/accounting/bank-statements/${statementId}`, { account_code: accountCode }).then((r) => r.data),
  reconcileBank: (companyId: string, accountCode: string, monthStart: string) =>
    api
      .post<ReconcileResult>(`/accounting/companies/${companyId}/bank/reconcile`, {
        account_code: accountCode,
        month_start: monthStart,
      })
      .then((r) => r.data),
  reconciliationFile: (id: string) =>
    api.get<Blob>(`/accounting/bank-reconciliations/${id}/file`, { responseType: "blob" }).then((r) => r.data),
  bankRules: (companyId: string) =>
    api.get<BankRule[]>(`/accounting/companies/${companyId}/bank/rules`).then((r) => r.data),
  deleteBankRule: (id: string) => api.delete(`/accounting/bank-rules/${id}`).then(() => undefined),
  /** Audit log: newest first, firm-scoped; filter by company, person, Manila calendar days, entity. */
  auditEvents: (filters: AuditFilters) =>
    api.get<AuditPage>("/accounting/audit-events", { params: filters }).then((r) => r.data),
  listCompanies: (q = "") =>
    api.get<Company[]>("/accounting/companies", { params: q ? { q } : {} }).then((r) => r.data),
  createCompany: (data: CompanyInput) =>
    api.post<Company>("/accounting/companies", data).then((r) => r.data),
  updateCompany: (id: string, data: CompanyInput) =>
    api.put<Company>(`/accounting/companies/${id}`, data).then((r) => r.data),
  upload: (files: File[], companyId?: string) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    if (companyId) fd.append("company_id", companyId);
    return api
      .post<Upload>("/accounting/uploads", fd, { headers: { "Content-Type": "multipart/form-data" } })
      .then((r) => r.data);
  },
  getUpload: (id: string) => api.get<Upload>(`/accounting/uploads/${id}`).then((r) => r.data),
  /** Latest drop of mine still waiting for company confirmation (null if none). */
  pendingUpload: () => api.get<Upload | null>("/accounting/uploads/pending").then((r) => r.data),
  confirmUpload: (id: string, assignments: ConfirmAssignment[]) =>
    api.post<Upload>(`/accounting/uploads/${id}/confirm`, { assignments }).then((r) => r.data),
  /** Read again the files of a finished upload that failed (AI busy, out of quota, timeout). */
  retryUpload: (id: string) => api.post<Upload>(`/accounting/uploads/${id}/retry`).then((r) => r.data),
  tree: () => api.get<TreeCompany[]>("/accounting/tree").then((r) => r.data),
  folder: (companyId: string, year: number | null, quarter: number | null) =>
    api
      .get<Folder>("/accounting/folders", {
        params: year != null && quarter != null
          ? { company_id: companyId, year, quarter }
          : { company_id: companyId },
      })
      .then((r) => r.data),
  updateDocument: (id: string, patch: DocumentPatch) =>
    api.patch<AADocument>(`/accounting/documents/${id}`, patch).then((r) => r.data),
  /** Possible duplicates touching one folder (year + quarter, or undated when both are null), or the whole company. */
  duplicates: (companyId: string, folder?: { year: number | null; quarter: number | null }) =>
    api
      .get<DuplicatePair[]>("/accounting/duplicates", {
        params: !folder
          ? { company_id: companyId }
          : folder.year != null && folder.quarter != null
            ? { company_id: companyId, year: folder.year, quarter: folder.quarter }
            : { company_id: companyId, undated: true },
      })
      .then((r) => r.data),
  /** Keep both: the pair is never offered as a duplicate again. */
  notDuplicate: (id: string, otherId: string, reason = "") =>
    api.post(`/accounting/documents/${id}/not-duplicate`, { other_id: otherId, reason }).then(() => undefined),
  deleteDocument: (id: string) => api.delete(`/accounting/documents/${id}`).then(() => undefined),
  pageImage: (fileId: string, page: number) =>
    api
      .get<Blob>(`/accounting/files/${fileId}/pages/${page}`, { responseType: "blob" })
      .then((r) => r.data),
  period: (companyId: string, year: number, quarter: number) =>
    api.get<Period>(`/accounting/periods/${companyId}/${year}/${quarter}`).then((r) => r.data),
  savePeriodInputs: (companyId: string, year: number, quarter: number, inputs: PeriodInputs) =>
    api.put<Period>(`/accounting/periods/${companyId}/${year}/${quarter}/inputs`, inputs).then((r) => r.data),
  setFiled: (companyId: string, year: number, quarter: number, filed: boolean, filedOn?: string) =>
    api
      .put<Period>(`/accounting/periods/${companyId}/${year}/${quarter}/filed`, {
        filed,
        ...(filedOn ? { filed_on: filedOn } : {}),
      })
      .then((r) => r.data),
  setFormFiled: (
    companyId: string,
    year: number,
    quarter: number,
    form: string,
    filed: boolean,
    outputId?: string,
    filedOn?: string,
  ) =>
    api
      .put<Period>(`/accounting/periods/${companyId}/${year}/${quarter}/filed-forms/${form}`, {
        filed,
        ...(outputId ? { output_id: outputId } : {}),
        ...(filedOn ? { filed_on: filedOn } : {}),
      })
      .then((r) => r.data),
  prepare: (outputId: string, scope: Scope) =>
    api.get<Prepare>(`/accounting/outputs/${outputId}/prepare`, { params: { scope } }).then((r) => r.data),
  pdfs: (outputId: string, forms: string[], clean: boolean) =>
    api
      .post<Blob>(`/accounting/outputs/${outputId}/pdfs`, { forms, clean }, { responseType: "blob" })
      .then((r) => ({ blob: r.data, zip: String(r.headers["content-type"] ?? "").includes("zip") })),
  generate: (companyId: string, year: number, quarter: number) =>
    api.post<Output>(`/accounting/periods/${companyId}/${year}/${quarter}/generate`).then((r) => r.data),
  output: (id: string) => api.get<Output>(`/accounting/outputs/${id}`).then((r) => r.data),
  outputFile: (id: string, kind: "xlsx" | "pdf", opts: { clean?: boolean; form?: string } = {}) =>
    api
      .get<Blob>(`/accounting/outputs/${id}/${kind}`, {
        params: { clean: opts.clean ?? false, ...(opts.form ? { form: opts.form } : {}) },
        responseType: "blob",
      })
      .then((r) => r.data),
  annualPeriod: (companyId: string, year: number) =>
    api.get<AnnualPeriod>(`/accounting/periods/${companyId}/${year}/annual`).then((r) => r.data),
  saveAnnualInputs: (companyId: string, year: number, inputs: AnnualInputs) =>
    api.put<AnnualPeriod>(`/accounting/periods/${companyId}/${year}/annual/inputs`, inputs).then((r) => r.data),
  setAnnualFiled: (companyId: string, year: number, filed: boolean) =>
    api.put<AnnualPeriod>(`/accounting/periods/${companyId}/${year}/annual/filed`, { filed }).then((r) => r.data),
  generateAnnual: (companyId: string, year: number) =>
    api.post<Output>(`/accounting/periods/${companyId}/${year}/annual/generate`).then((r) => r.data),
  assets: (companyId: string, year?: number) =>
    api
      .get<Asset[]>(`/accounting/companies/${companyId}/assets`, { params: year ? { year } : {} })
      .then((r) => r.data),
  updateAsset: (id: string, patch: AssetPatch, year?: number) =>
    api.patch<Asset>(`/accounting/assets/${id}`, patch, { params: year ? { year } : {} }).then((r) => r.data),
  addOpeningAsset: (companyId: string, input: OpeningAssetInput, year?: number) =>
    api
      .post<Asset>(`/accounting/companies/${companyId}/assets`, input, { params: year ? { year } : {} })
      .then((r) => r.data),
  deleteOpeningAsset: (id: string) => api.delete(`/accounting/assets/${id}`).then(() => undefined),
  accounts: (companyId: string) =>
    api.get<Account[]>(`/accounting/companies/${companyId}/accounts`).then((r) => r.data),
  addAccount: (companyId: string, data: { code: string; name: string; parent_code: string }) =>
    api.post<Account>(`/accounting/companies/${companyId}/accounts`, data).then((r) => r.data),
  updateAccount: (id: string, patch: { name?: string; active?: boolean; bank_account_no?: string }) =>
    api.patch<Account>(`/accounting/accounts/${id}`, patch).then((r) => r.data),
  journalEntries: (companyId: string, year: number) =>
    api
      .get<JournalEntry[]>(`/accounting/companies/${companyId}/journal-entries`, { params: { year } })
      .then((r) => r.data),
  createJournalEntry: (companyId: string, data: JournalEntryInput) =>
    api.post<JournalEntry>(`/accounting/companies/${companyId}/journal-entries`, data).then((r) => r.data),
  updateJournalEntry: (id: string, data: JournalEntryInput) =>
    api.put<JournalEntry>(`/accounting/journal-entries/${id}`, data).then((r) => r.data),
  deleteJournalEntry: (id: string) => api.delete(`/accounting/journal-entries/${id}`).then(() => undefined),
  employees: (companyId: string, year: number) =>
    api.get<EmployeesYear>(`/accounting/companies/${companyId}/employees/${year}`).then((r) => r.data),
  previewPayroll: (companyId: string, year: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post<PayrollPreview>(`/accounting/companies/${companyId}/employees/${year}/import/preview`, fd).then((r) => r.data);
  },
  importPayroll: (companyId: string, year: number, file: File, mapping: Record<string, string>) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mapping", JSON.stringify(mapping));
    return api.post<PayrollImport>(`/accounting/companies/${companyId}/employees/${year}/import`, fd).then((r) => r.data);
  },
  addEmployee: (companyId: string, year: number, data: EmployeeData) =>
    api.post<EmployeesYear>(`/accounting/companies/${companyId}/employees/${year}`, data).then((r) => r.data),
  updateEmployee: (id: string, data: EmployeeData) =>
    api.put<EmployeesYear>(`/accounting/employees/${id}`, data).then((r) => r.data),
  deleteEmployee: (id: string) => api.delete<EmployeesYear>(`/accounting/employees/${id}`).then((r) => r.data),
  alphalistXlsx: (companyId: string, year: number) =>
    api.get<Blob>(`/accounting/companies/${companyId}/employees/${year}/alphalist.xlsx`, { responseType: "blob" }).then((r) => r.data),
  zip2316: (companyId: string, year: number) =>
    api.get<Blob>(`/accounting/companies/${companyId}/employees/${year}/2316.zip`, { responseType: "blob" }).then((r) => r.data),
  alphalistStatus: (year: number) =>
    api.get<AlphalistStatus[]>("/accounting/alphalist-status", { params: { year } }).then((r) => r.data),
  booksYear: (companyId: string, year: number) =>
    api.get<BooksYear>(`/accounting/companies/${companyId}/books/${year}`).then((r) => r.data),
  closeBooksMonth: (companyId: string, monthStart: string, overrideReason = "") =>
    api
      .post<BooksYear>(`/accounting/companies/${companyId}/books/close`, {
        month_start: monthStart,
        override_reason: overrideReason,
      })
      .then((r) => r.data),
  reopenBooksMonth: (companyId: string, reason = "") =>
    api.post<BooksYear>(`/accounting/companies/${companyId}/books/reopen`, { reason }).then((r) => r.data),
  bindBooksYear: (companyId: string, year: number) =>
    api.post<BooksYear>(`/accounting/companies/${companyId}/books/${year}/bind`).then((r) => r.data),
  booksFile: (companyId: string, year: number, book: string, monthStart?: string) =>
    api
      .get<Blob>(`/accounting/companies/${companyId}/books/${year}/file`, {
        params: monthStart ? { book, month_start: monthStart } : { book },
        responseType: "blob",
      })
      .then((r) => r.data),
  atcDatabank: (companyId: string) =>
    api.get<AtcDatabank>(`/accounting/companies/${companyId}/atc-databank`).then((r) => r.data),
  setSupplierAtc: (companyId: string, tin: string, ewtAtc: string, name = "") =>
    api
      .put<AtcDatabank>(`/accounting/companies/${companyId}/atc-databank/suppliers/${tin}`, { ewt_atc: ewtAtc, name })
      .then((r) => r.data),
  setAccountAtc: (companyId: string, account: string, ewtAtc: string) =>
    api
      .put<AtcDatabank>(`/accounting/companies/${companyId}/atc-databank/accounts/${account}`, { ewt_atc: ewtAtc })
      .then((r) => r.data),
  useAtcSuggestions: (companyId: string) =>
    api.post<AtcDatabank>(`/accounting/companies/${companyId}/atc-databank/use-suggestions`).then((r) => r.data),
  getDocument: (id: string) => api.get<AADocument>(`/accounting/documents/${id}`).then((r) => r.data),
  documentPayments: (docId: string) =>
    api.get<PaymentLinks>(`/accounting/documents/${docId}/payments`).then((r) => r.data),
  outgoing2307s: (id: string) =>
    api.get<Blob>(`/accounting/outputs/${id}/2307s`, { responseType: "blob" }).then((r) => r.data),
};
