// Accounting API client (companies, uploads, periods, books). Auth/team/admin calls live in lib/api.ts.
import api, { seg } from "@/lib/api";
import type { StatementType } from "@/types/extras";
import type {
  BulkResolveResult,
  Certificate,
  CertificateEdits,
  ImportKind,
  ImportOptions,
  ImportPreview,
  ImportBatches,
  ImportResult,
  ImportUndo,
  OpeningItems,
  OpeningItem,
  CoaTemplate,
  ReclassifyInput,
  ReclassifyList,
  ReclassifyPreview,
  CompanyKpis,
  ManagementPack,
  Postings,
  Report,
  ReportKind,
  ReportParams,
  ReportSource,
  AADocument,
  Account,
  AnnualInputs,
  AnnualPeriod,
  Asset,
  AssetPatch,
  OpeningAssetInput,
  AtcDatabank,
  Aging,
  ContactDetail,
  ContactList,
  ContactPatch,
  Cwt2307,
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
    api.get<BankOverview>(`/accounting/companies/${seg(companyId)}/bank`).then((r) => r.data),
  bankMonth: (companyId: string, account: string, month: string) =>
    api.get<BankMonth>(`/accounting/companies/${seg(companyId)}/bank/lines`, { params: { account, month } }).then((r) => r.data),
  confirmBankLine: (lineId: string, body: BankConfirm = {}) =>
    api.post<BankMonth>(`/accounting/bank-lines/${seg(lineId)}/confirm`, body).then((r) => r.data),
  rejectBankLine: (lineId: string, reason = "") =>
    api.post<BankMonth>(`/accounting/bank-lines/${seg(lineId)}/reject`, { reason }).then((r) => r.data),
  excludeBankLine: (lineId: string, reason = "") =>
    api.post<BankMonth>(`/accounting/bank-lines/${seg(lineId)}/exclude`, { reason }).then((r) => r.data),
  rematchBank: (companyId: string) =>
    api.post<BankOverview>(`/accounting/companies/${seg(companyId)}/bank/rematch`).then((r) => r.data),
  setStatementAccount: (statementId: string, accountCode: string) =>
    api.patch<BankStatement>(`/accounting/bank-statements/${seg(statementId)}`, { account_code: accountCode }).then((r) => r.data),
  reconcileBank: (companyId: string, accountCode: string, monthStart: string) =>
    api
      .post<ReconcileResult>(`/accounting/companies/${seg(companyId)}/bank/reconcile`, {
        account_code: accountCode,
        month_start: monthStart,
      })
      .then((r) => r.data),
  reconciliationFile: (id: string) =>
    api.get<Blob>(`/accounting/bank-reconciliations/${seg(id)}/file`, { responseType: "blob" }).then((r) => r.data),
  bankRules: (companyId: string) =>
    api.get<BankRule[]>(`/accounting/companies/${seg(companyId)}/bank/rules`).then((r) => r.data),
  deleteBankRule: (id: string) => api.delete(`/accounting/bank-rules/${seg(id)}`).then(() => undefined),
  /** Audit log: newest first, firm-scoped; filter by company, person, Manila calendar days, entity. */
  auditEvents: (filters: AuditFilters) =>
    api.get<AuditPage>("/accounting/audit-events", { params: filters }).then((r) => r.data),
  listCompanies: (q = "") =>
    api.get<Company[]>("/accounting/companies", { params: q ? { q } : {} }).then((r) => r.data),
  createCompany: (data: CompanyInput & { coa_template?: string }) =>
    api.post<Company>("/accounting/companies", data).then((r) => r.data),
  coaTemplates: () => api.get<CoaTemplate[]>("/accounting/coa-templates").then((r) => r.data),
  saveCoaTemplate: (companyId: string, name: string, description = "") =>
    api.post<CoaTemplate>(`/accounting/companies/${seg(companyId)}/coa-template`, { name, description }).then((r) => r.data),
  deleteCoaTemplate: (id: string) => api.delete(`/accounting/coa-templates/${seg(id)}`).then(() => undefined),
  reclassifyCandidates: (companyId: string, params: { start: string; end: string; account: string; atc?: string }) =>
    api.get<ReclassifyList>(`/accounting/companies/${seg(companyId)}/reclassify`, { params }).then((r) => r.data),
  reclassifyPreview: (companyId: string, body: ReclassifyInput) =>
    api.post<ReclassifyPreview>(`/accounting/companies/${seg(companyId)}/reclassify/preview`, body).then((r) => r.data),
  reclassify: (companyId: string, body: ReclassifyInput) =>
    api.post<ReclassifyPreview>(`/accounting/companies/${seg(companyId)}/reclassify`, body).then((r) => r.data),
  bulkResolve: (body: { document_ids: string[]; reason_code: string; action: "reviewed" | "exclude"; reason: string }) =>
    api.post<BulkResolveResult>("/accounting/documents/bulk-resolve", body).then((r) => r.data),
  updateCompany: (id: string, data: CompanyInput) =>
    api.put<Company>(`/accounting/companies/${seg(id)}`, data).then((r) => r.data),
  upload: (files: File[], companyId?: string) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    if (companyId) fd.append("company_id", companyId);
    return api
      .post<Upload>("/accounting/uploads", fd, { headers: { "Content-Type": "multipart/form-data" } })
      .then((r) => r.data);
  },
  getUpload: (id: string) => api.get<Upload>(`/accounting/uploads/${seg(id)}`).then((r) => r.data),
  /** Latest drop of mine still waiting for company confirmation (null if none). */
  pendingUpload: () => api.get<Upload | null>("/accounting/uploads/pending").then((r) => r.data),
  confirmUpload: (id: string, assignments: ConfirmAssignment[]) =>
    api.post<Upload>(`/accounting/uploads/${seg(id)}/confirm`, { assignments }).then((r) => r.data),
  /** Read again the files of a finished upload that failed (AI busy, out of quota, timeout). */
  retryUpload: (id: string) => api.post<Upload>(`/accounting/uploads/${seg(id)}/retry`).then((r) => r.data),
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
    api.patch<AADocument>(`/accounting/documents/${seg(id)}`, patch).then((r) => r.data),
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
    api.post(`/accounting/documents/${seg(id)}/not-duplicate`, { other_id: otherId, reason }).then(() => undefined),
  deleteDocument: (id: string) => api.delete(`/accounting/documents/${seg(id)}`).then(() => undefined),
  pageImage: (fileId: string, page: number) =>
    api
      .get<Blob>(`/accounting/files/${seg(fileId)}/pages/${seg(page)}`, { responseType: "blob" })
      .then((r) => r.data),
  period: (companyId: string, year: number, quarter: number) =>
    api.get<Period>(`/accounting/periods/${seg(companyId)}/${seg(year)}/${seg(quarter)}`).then((r) => r.data),
  savePeriodInputs: (companyId: string, year: number, quarter: number, inputs: PeriodInputs) =>
    api.put<Period>(`/accounting/periods/${seg(companyId)}/${seg(year)}/${seg(quarter)}/inputs`, inputs).then((r) => r.data),
  setFiled: (companyId: string, year: number, quarter: number, filed: boolean, filedOn?: string) =>
    api
      .put<Period>(`/accounting/periods/${seg(companyId)}/${seg(year)}/${seg(quarter)}/filed`, {
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
      .put<Period>(`/accounting/periods/${seg(companyId)}/${seg(year)}/${seg(quarter)}/filed-forms/${seg(form)}`, {
        filed,
        ...(outputId ? { output_id: outputId } : {}),
        ...(filedOn ? { filed_on: filedOn } : {}),
      })
      .then((r) => r.data),
  prepare: (outputId: string, scope: Scope) =>
    api.get<Prepare>(`/accounting/outputs/${seg(outputId)}/prepare`, { params: { scope } }).then((r) => r.data),
  pdfs: (outputId: string, forms: string[], clean: boolean) =>
    api
      .post<Blob>(`/accounting/outputs/${seg(outputId)}/pdfs`, { forms, clean }, { responseType: "blob" })
      .then((r) => ({ blob: r.data, zip: String(r.headers["content-type"] ?? "").includes("zip") })),
  generate: (companyId: string, year: number, quarter: number) =>
    api.post<Output>(`/accounting/periods/${seg(companyId)}/${seg(year)}/${seg(quarter)}/generate`).then((r) => r.data),
  output: (id: string) => api.get<Output>(`/accounting/outputs/${seg(id)}`).then((r) => r.data),
  outputFile: (id: string, kind: "xlsx" | "pdf", opts: { clean?: boolean; form?: string } = {}) =>
    api
      .get<Blob>(`/accounting/outputs/${seg(id)}/${seg(kind)}`, {
        params: { clean: opts.clean ?? false, ...(opts.form ? { form: opts.form } : {}) },
        responseType: "blob",
      })
      .then((r) => r.data),
  annualPeriod: (companyId: string, year: number) =>
    api.get<AnnualPeriod>(`/accounting/periods/${seg(companyId)}/${seg(year)}/annual`).then((r) => r.data),
  saveAnnualInputs: (companyId: string, year: number, inputs: AnnualInputs) =>
    api.put<AnnualPeriod>(`/accounting/periods/${seg(companyId)}/${seg(year)}/annual/inputs`, inputs).then((r) => r.data),
  setAnnualFiled: (companyId: string, year: number, filed: boolean) =>
    api.put<AnnualPeriod>(`/accounting/periods/${seg(companyId)}/${seg(year)}/annual/filed`, { filed }).then((r) => r.data),
  generateAnnual: (companyId: string, year: number) =>
    api.post<Output>(`/accounting/periods/${seg(companyId)}/${seg(year)}/annual/generate`).then((r) => r.data),
  assets: (companyId: string, year?: number) =>
    api
      .get<Asset[]>(`/accounting/companies/${seg(companyId)}/assets`, { params: year ? { year } : {} })
      .then((r) => r.data),
  updateAsset: (id: string, patch: AssetPatch, year?: number) =>
    api.patch<Asset>(`/accounting/assets/${seg(id)}`, patch, { params: year ? { year } : {} }).then((r) => r.data),
  addOpeningAsset: (companyId: string, input: OpeningAssetInput, year?: number) =>
    api
      .post<Asset>(`/accounting/companies/${seg(companyId)}/assets`, input, { params: year ? { year } : {} })
      .then((r) => r.data),
  deleteOpeningAsset: (id: string) => api.delete(`/accounting/assets/${seg(id)}`).then(() => undefined),
  accounts: (companyId: string) =>
    api.get<Account[]>(`/accounting/companies/${seg(companyId)}/accounts`).then((r) => r.data),
  addAccount: (companyId: string, data: { code: string; name: string; parent_code: string }) =>
    api.post<Account>(`/accounting/companies/${seg(companyId)}/accounts`, data).then((r) => r.data),
  updateAccount: (id: string, patch: { name?: string; active?: boolean; locked?: boolean; bank_account_no?: string }) =>
    api.patch<Account>(`/accounting/accounts/${seg(id)}`, patch).then((r) => r.data),
  journalEntries: (companyId: string, year: number) =>
    api
      .get<JournalEntry[]>(`/accounting/companies/${seg(companyId)}/journal-entries`, { params: { year } })
      .then((r) => r.data),
  createJournalEntry: (companyId: string, data: JournalEntryInput) =>
    api.post<JournalEntry>(`/accounting/companies/${seg(companyId)}/journal-entries`, data).then((r) => r.data),
  updateJournalEntry: (id: string, data: JournalEntryInput) =>
    api.put<JournalEntry>(`/accounting/journal-entries/${seg(id)}`, data).then((r) => r.data),
  deleteJournalEntry: (id: string) => api.delete(`/accounting/journal-entries/${seg(id)}`).then(() => undefined),
  employees: (companyId: string, year: number) =>
    api.get<EmployeesYear>(`/accounting/companies/${seg(companyId)}/employees/${seg(year)}`).then((r) => r.data),
  previewPayroll: (companyId: string, year: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post<PayrollPreview>(`/accounting/companies/${seg(companyId)}/employees/${seg(year)}/import/preview`, fd).then((r) => r.data);
  },
  importPayroll: (companyId: string, year: number, file: File, mapping: Record<string, string>) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mapping", JSON.stringify(mapping));
    return api.post<PayrollImport>(`/accounting/companies/${seg(companyId)}/employees/${seg(year)}/import`, fd).then((r) => r.data);
  },
  addEmployee: (companyId: string, year: number, data: EmployeeData) =>
    api.post<EmployeesYear>(`/accounting/companies/${seg(companyId)}/employees/${seg(year)}`, data).then((r) => r.data),
  updateEmployee: (id: string, data: EmployeeData) =>
    api.put<EmployeesYear>(`/accounting/employees/${seg(id)}`, data).then((r) => r.data),
  deleteEmployee: (id: string) => api.delete<EmployeesYear>(`/accounting/employees/${seg(id)}`).then((r) => r.data),
  alphalistXlsx: (companyId: string, year: number) =>
    api.get<Blob>(`/accounting/companies/${seg(companyId)}/employees/${seg(year)}/alphalist.xlsx`, { responseType: "blob" }).then((r) => r.data),
  zip2316: (companyId: string, year: number, edits: CertificateEdits = {}) =>
    api
      .post<Blob>(`/accounting/companies/${seg(companyId)}/employees/${seg(year)}/2316.zip`, { edits }, { responseType: "blob" })
      .then((r) => r.data),
  certificates2316: (companyId: string, year: number) =>
    api.get<Certificate[]>(`/accounting/companies/${seg(companyId)}/employees/${seg(year)}/2316/certificates`).then((r) => r.data),
  preview2316: (companyId: string, year: number, employee: string, values: Record<string, string>) =>
    api
      .post<Blob>(`/accounting/companies/${seg(companyId)}/employees/${seg(year)}/2316/preview`, { id: employee, values }, {
        responseType: "blob",
      })
      .then((r) => r.data),
  alphalistStatus: (year: number) =>
    api.get<AlphalistStatus[]>("/accounting/alphalist-status", { params: { year } }).then((r) => r.data),
  booksYear: (companyId: string, year: number) =>
    api.get<BooksYear>(`/accounting/companies/${seg(companyId)}/books/${seg(year)}`).then((r) => r.data),
  closeBooksMonth: (companyId: string, monthStart: string, overrideReason = "") =>
    api
      .post<BooksYear>(`/accounting/companies/${seg(companyId)}/books/close`, {
        month_start: monthStart,
        override_reason: overrideReason,
      })
      .then((r) => r.data),
  reopenBooksMonth: (companyId: string, reason = "") =>
    api.post<BooksYear>(`/accounting/companies/${seg(companyId)}/books/reopen`, { reason }).then((r) => r.data),
  bindBooksYear: (companyId: string, year: number) =>
    api.post<BooksYear>(`/accounting/companies/${seg(companyId)}/books/${seg(year)}/bind`).then((r) => r.data),
  booksFile: (companyId: string, year: number, book: string, monthStart?: string) =>
    api
      .get<Blob>(`/accounting/companies/${seg(companyId)}/books/${seg(year)}/file`, {
        params: monthStart ? { book, month_start: monthStart } : { book },
        responseType: "blob",
      })
      .then((r) => r.data),
  atcDatabank: (companyId: string) =>
    api.get<AtcDatabank>(`/accounting/companies/${seg(companyId)}/atc-databank`).then((r) => r.data),
  setSupplierAtc: (companyId: string, tin: string, ewtAtc: string, name = "") =>
    api
      .put<AtcDatabank>(`/accounting/companies/${seg(companyId)}/atc-databank/suppliers/${seg(tin)}`, { ewt_atc: ewtAtc, name })
      .then((r) => r.data),
  setAccountAtc: (companyId: string, account: string, ewtAtc: string) =>
    api
      .put<AtcDatabank>(`/accounting/companies/${seg(companyId)}/atc-databank/accounts/${seg(account)}`, { ewt_atc: ewtAtc })
      .then((r) => r.data),
  useAtcSuggestions: (companyId: string) =>
    api.post<AtcDatabank>(`/accounting/companies/${seg(companyId)}/atc-databank/use-suggestions`).then((r) => r.data),
  getDocument: (id: string) => api.get<AADocument>(`/accounting/documents/${seg(id)}`).then((r) => r.data),
  documentPayments: (docId: string) =>
    api.get<PaymentLinks>(`/accounting/documents/${seg(docId)}/payments`).then((r) => r.data),
  outgoing2307s: (id: string, edits: CertificateEdits = {}) =>
    api.post<Blob>(`/accounting/outputs/${seg(id)}/2307s`, { edits }, { responseType: "blob" }).then((r) => r.data),
  certificates2307: (id: string) =>
    api.get<Certificate[]>(`/accounting/outputs/${seg(id)}/2307s/certificates`).then((r) => r.data),
  preview2307: (id: string, certificate: string, values: Record<string, string>) =>
    api
      .post<Blob>(`/accounting/outputs/${seg(id)}/2307s/preview`, { id: certificate, values }, { responseType: "blob" })
      .then((r) => r.data),
  /** A return's PDF with unsaved hand edits (edited items highlighted). */
  previewForm: (id: string, form: string, values: Record<string, string>) =>
    api.post<Blob>(`/accounting/outputs/${seg(id)}/preview`, { form, values }, { responseType: "blob" }).then((r) => r.data),
  /** Save hand edits to a form as the period's next version. */
  saveFormEdits: (id: string, form: string, values: Record<string, string>) =>
    api.post<Output>(`/accounting/outputs/${seg(id)}/edits`, { form, values }).then((r) => r.data),
  // Customers / suppliers
  contacts: (companyId: string, role: "customer" | "supplier", asOf: string) =>
    api.get<ContactList>(`/accounting/companies/${seg(companyId)}/contacts`, { params: { role, as_of: asOf } }).then((r) => r.data),
  contact: (contactId: string, asOf: string) =>
    api.get<ContactDetail>(`/accounting/contacts/${seg(contactId)}`, { params: { as_of: asOf } }).then((r) => r.data),
  updateContact: (contactId: string, patch: ContactPatch, asOf: string) =>
    api.patch<ContactDetail>(`/accounting/contacts/${seg(contactId)}`, patch, { params: { as_of: asOf } }).then((r) => r.data),
  mergeContact: (contactId: string, into: string, reason: string, asOf: string) =>
    api.post<ContactDetail>(`/accounting/contacts/${seg(contactId)}/merge`, { into, reason }, { params: { as_of: asOf } }).then((r) => r.data),
  markCwt2307: (documentId: string, status: "pending" | "received" | "auto", certificateId: string | null = null, reason = "") =>
    api
      .put<Cwt2307>(`/accounting/documents/${seg(documentId)}/cwt-2307`, { status, certificate_id: certificateId, reason })
      .then((r) => r.data),
  aging: (companyId: string, kind: "ar" | "ap", asOf: string) =>
    api.get<Aging>(`/accounting/companies/${seg(companyId)}/aging`, { params: { kind, as_of: asOf } }).then((r) => r.data),
  agingFile: (companyId: string, kind: "ar" | "ap", asOf: string, format: "xlsx" | "pdf") =>
    api
      .get<Blob>(`/accounting/companies/${seg(companyId)}/aging`, { params: { kind, as_of: asOf, format }, responseType: "blob" })
      .then((r) => r.data),
  customerStatement: (contactId: string, asOf: string, type: StatementType = "open_item", start?: string) =>
    api
      .get<Blob>(`/accounting/contacts/${seg(contactId)}/statement`, {
        params: { as_of: asOf, type, ...(type !== "open_item" && start ? { start } : {}) },
        responseType: "blob",
      })
      .then((r) => r.data),
  outputAging: (outputId: string, kind: "ar" | "ap") =>
    api.get<Blob>(`/accounting/outputs/${seg(outputId)}/aging`, { params: { kind }, responseType: "blob" }).then((r) => r.data),
  // Reports (live from the books)
  report: (companyId: string, kind: ReportKind, params: ReportParams) =>
    api.get<Report>(`/accounting/companies/${seg(companyId)}/reports/${seg(kind)}`, { params }).then((r) => r.data),
  reportFile: (companyId: string, kind: ReportKind, params: ReportParams, format: "xlsx" | "pdf") =>
    api
      .get<Blob>(`/accounting/companies/${seg(companyId)}/reports/${seg(kind)}/export`, {
        params: { ...params, format },
        responseType: "blob",
      })
      .then((r) => r.data),
  reportPostings: (companyId: string, codes: string[], start: string | null, end: string) =>
    api
      .get<Postings>(`/accounting/companies/${seg(companyId)}/report-postings`, {
        params: { codes: codes.join(","), end, ...(start ? { start } : {}) },
      })
      .then((r) => r.data),
  reportSource: (companyId: string, entryId: string) =>
    api
      .get<ReportSource>(`/accounting/companies/${seg(companyId)}/report-source`, { params: { entry_id: entryId } })
      .then((r) => r.data),
  kpis: (companyId: string, start?: string, end?: string) =>
    api
      .get<CompanyKpis>(`/accounting/companies/${seg(companyId)}/kpis`, { params: { ...(start ? { start } : {}), ...(end ? { end } : {}) } })
      .then((r) => r.data),
  pack: (companyId: string, year: number, quarter: number) =>
    api.get<ManagementPack>(`/accounting/companies/${seg(companyId)}/pack/${seg(year)}/${seg(quarter)}`).then((r) => r.data),
  savePackNotes: (companyId: string, year: number, quarter: number, notes: string) =>
    api
      .put<ManagementPack>(`/accounting/companies/${seg(companyId)}/pack/${seg(year)}/${seg(quarter)}/notes`, { notes })
      .then((r) => r.data),
  generatePack: (companyId: string, year: number, quarter: number) =>
    api.post<ManagementPack>(`/accounting/companies/${seg(companyId)}/pack/${seg(year)}/${seg(quarter)}`).then((r) => r.data),
  packFile: (companyId: string, year: number, quarter: number, format: "pdf" | "docx") =>
    api
      .get<Blob>(`/accounting/companies/${seg(companyId)}/pack/${seg(year)}/${seg(quarter)}/file`, {
        params: { format },
        responseType: "blob",
      })
      .then((r) => r.data),
  importPreview: (companyId: string, kind: ImportKind, file: File, options: ImportOptions) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("options", JSON.stringify(options));
    return api.post<ImportPreview>(`/accounting/companies/${seg(companyId)}/imports/${seg(kind)}/preview`, fd).then((r) => r.data);
  },
  importConfirm: (companyId: string, kind: ImportKind, file: File, options: ImportOptions) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("options", JSON.stringify(options));
    return api.post<ImportResult>(`/accounting/companies/${seg(companyId)}/imports/${seg(kind)}`, fd).then((r) => r.data);
  },
  importBatches: (companyId: string) =>
    api.get<ImportBatches>(`/accounting/companies/${seg(companyId)}/imports/batches`).then((r) => r.data),
  undoImport: (batchId: string) =>
    api.post<ImportUndo>(`/accounting/import-batches/${seg(batchId)}/undo`).then((r) => r.data),
  importTemplate: (kind: ImportKind, format: "csv" | "xlsx") =>
    api.get<Blob>(`/accounting/imports/templates/${seg(kind)}`, { params: { format }, responseType: "blob" }).then((r) => r.data),
  openingItems: (companyId: string) =>
    api.get<OpeningItems>(`/accounting/companies/${seg(companyId)}/opening-items`).then((r) => r.data),
  payOpeningItem: (id: string, body: { paid_on: string | null; paid_via?: string; paid_account?: string }) =>
    api.patch<OpeningItem>(`/accounting/opening-items/${seg(id)}`, body).then((r) => r.data),
  deleteOpeningItem: (id: string) => api.delete(`/accounting/opening-items/${seg(id)}`).then(() => undefined),
};
