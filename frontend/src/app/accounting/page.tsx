"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { MagnifyingGlass, Spinner, UploadSimple } from "@phosphor-icons/react";
import CompanyForm from "@/components/accounting/CompanyForm";
import CompanyPicker from "@/components/accounting/CompanyPicker";
import DocumentPanel from "@/components/accounting/DocumentPanel";
import FileGrid from "@/components/accounting/FileGrid";
import FolderTree from "@/components/accounting/FolderTree";
import BooksPanel from "@/components/accounting/BooksPanel";
import AnnualPanel from "@/components/accounting/AnnualPanel";
import AlphalistChecklist from "@/components/accounting/AlphalistChecklist";
import EmployeesPanel from "@/components/accounting/EmployeesPanel";
import AtcDatabankPanel from "@/components/accounting/AtcDatabankPanel";
import AuditLogPanel from "@/components/accounting/AuditLogPanel";
import BankPanel from "@/components/accounting/BankPanel";
import ContactsPanel from "@/components/accounting/ContactsPanel";
import CompanyOverviewPanel from "@/components/accounting/CompanyOverviewPanel";
import PeriodPanel from "@/components/accounting/PeriodPanel";
import ReportsPanel from "@/components/accounting/ReportsPanel";
import ReclassifyPanel from "@/components/accounting/ReclassifyPanel";
import ImportPanel from "@/components/accounting/ImportPanel";
import AppendPrompt from "@/components/accounting/AppendPrompt";
import UploadReviewDialog from "@/components/accounting/UploadReviewDialog";
import DuplicateBanner from "@/components/accounting/DuplicateBanner";
import GettingStarted from "@/components/guide/GettingStarted";
import Hint from "@/components/guide/Hint";
import GuideTour, { GuideButton } from "@/components/guide/GuideTour";
import { DOCUMENTS_TOUR } from "@/components/guide/tours";
import { accountingApi } from "@/lib/accounting-api";
import { OPEN_COMPANY_EVENT, safeId } from "@/lib/work-api";
import { OPEN_TARGET_EVENT, parseTarget } from "@/lib/search-nav";
import { teamApi } from "@/lib/api";
import { useGuide } from "@/lib/guides";
import { apiErrorMessage } from "@/lib/accounting-format";
import { useAuth } from "@/lib/auth";
import type {
  AADocument,
  AffectedPeriod,
  Company,
  CompanyInput,
  ConfirmAssignment,
  Folder,
  FolderRef,
  TreeCompany,
  Upload,
} from "@/types/accounting";

const PICKER_KEY = "aa:lastPicker";
const ACCEPT = { "application/pdf": [".pdf"], "image/png": [".png"], "image/jpeg": [".jpg", ".jpeg"] };
const BUSY: Upload["status"][] = ["detecting", "confirming", "extracting"];

export default function AccountingPage() {
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "enterprise" || user?.role === "manager";

  const [companies, setCompanies] = useState<Company[]>([]);
  const [tree, setTree] = useState<TreeCompany[]>([]);
  const [search, setSearch] = useState("");
  const [picker, setPicker] = useState("auto");
  const [selected, setSelected] = useState<FolderRef | null>(null);
  const [folder, setFolder] = useState<Folder | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [openDoc, setOpenDoc] = useState<AADocument | null>(null);
  // the page to show first (a bank line's statement page from a report drill-down)
  const [openDocFocus, setOpenDocFocus] = useState<{ id: string; page: number } | null>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [companyForm, setCompanyForm] = useState<{ initial?: Partial<CompanyInput>; id?: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [append, setAppend] = useState<AffectedPeriod[] | null>(null);
  const [periodRefresh, setPeriodRefresh] = useState(0);
  const [memberCount, setMemberCount] = useState<number | null>(null);
  const [deepContact, setDeepContact] = useState<string | null>(null);
  const guide = useGuide("documents");

  // Deep links from the work board, notifications and search: /accounting?company=<id>&view=…&doc=<id>
  // (lib/search-nav parseTarget: only UUIDs and known shapes are accepted; panels load through the firm-scoped API).
  useEffect(() => {
    const openTarget = (params: URLSearchParams) => {
      const t = parseTarget(params);
      if (t.ref) setSelected(t.ref);
      setDeepContact(t.contactId);
      if (t.docId) {
        accountingApi
          .getDocument(t.docId)
          .then(setOpenDoc)
          .catch((e) => setError(apiErrorMessage(e, "Couldn't open the document")));
      }
    };
    openTarget(new URLSearchParams(window.location.search));
    const openCompany = (e: Event) => {
      const id = safeId((e as CustomEvent<unknown>).detail);
      if (id) setSelected({ companyId: id, year: null, quarter: null, view: "overview" });
    };
    const onTarget = (e: Event) => {
      const detail = (e as CustomEvent<unknown>).detail;
      if (typeof detail === "string") openTarget(new URLSearchParams(detail));
    };
    window.addEventListener(OPEN_COMPANY_EVENT, openCompany);
    window.addEventListener(OPEN_TARGET_EVENT, onTarget);
    return () => {
      window.removeEventListener(OPEN_COMPANY_EVENT, openCompany);
      window.removeEventListener(OPEN_TARGET_EVENT, onTarget);
    };
  }, []);

  useEffect(() => {
    try {
      setPicker(localStorage.getItem(PICKER_KEY) || "auto");
    } catch {
      // storage unavailable (private mode) — keep auto-detect
    }
  }, []);

  const choosePicker = (value: string) => {
    setPicker(value);
    try {
      localStorage.setItem(PICKER_KEY, value);
    } catch {
      // not persisted; still works for this visit
    }
  };

  const loadCompanies = useCallback(async () => setCompanies(await accountingApi.listCompanies()), []);
  const loadTree = useCallback(async () => setTree(await accountingApi.tree()), []);
  const loadFolder = useCallback(async (ref: FolderRef | null) => {
    // The Annual, Books and ATC databank nodes have no document folder of their own.
    setFolder(ref && ref.quarter !== 0 && !ref.view ? await accountingApi.folder(ref.companyId, ref.year, ref.quarter) : null);
  }, []);

  useEffect(() => {
    Promise.all([loadCompanies(), loadTree()]).catch((e) => setError(apiErrorMessage(e, "Couldn't load your documents")));
  }, [loadCompanies, loadTree]);

  // Only for the getting-started checklist; platform admins outside a firm get an error and skip that step.
  useEffect(() => {
    if (!canManage) return;
    teamApi.members().then((m) => setMemberCount(m.length)).catch(() => setMemberCount(null));
  }, [canManage]);

  // Resume a drop that is still waiting for company confirmation (e.g. after "Decide later" + reload).
  useEffect(() => {
    accountingApi
      .pendingUpload()
      .then((pending) => {
        if (pending) setUpload((current) => current ?? pending);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setCategory(null);
    loadFolder(selected).catch((e) => setError(apiErrorMessage(e, "Couldn't open the folder")));
  }, [selected, loadFolder]);

  // Poll while the server is working on the active upload.
  const uploadId = upload?.id;
  const uploadStatus = upload?.status;
  useEffect(() => {
    if (!uploadId || !uploadStatus || !BUSY.includes(uploadStatus)) return;
    const timer = setInterval(() => {
      accountingApi.getUpload(uploadId).then(setUpload).catch((e) => setError(apiErrorMessage(e)));
    }, 2000);
    return () => clearInterval(timer);
  }, [uploadId, uploadStatus]);

  // React once to each status change.
  const lastStatus = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!upload || upload.status === lastStatus.current) return;
    lastStatus.current = upload.status;
    if (upload.status === "awaiting_confirmation") setReviewOpen(true);
    if (upload.status === "failed") setError("Processing failed. Try uploading the files again.");
    if (upload.status === "done") {
      const filed = upload.files.filter((f) => f.status === "extracted").length;
      const failed = upload.files.filter((f) => f.status === "error").length;
      const dupes = upload.files.filter((f) => f.status === "duplicate").length;
      const parts = [`${filed} file${filed === 1 ? "" : "s"} filed`];
      if (dupes) parts.push(`${dupes} already uploaded`);
      if (failed) parts.push(`${failed} couldn't be read`);
      setNotice(parts.join(" · "));
      if (upload.affected_periods?.length) setAppend(upload.affected_periods);
      setPeriodRefresh((n) => n + 1);
      loadTree().catch(() => undefined);
      loadFolder(selected).catch(() => undefined);
    }
  }, [upload, loadTree, loadFolder, selected]);

  const retryable = upload?.status === "done" && upload.files.some((f) => f.status === "error" && f.company_id);
  const retryFailed = async () => {
    if (!upload) return;
    setError("");
    setNotice("");
    try {
      setUpload(await accountingApi.retryUpload(upload.id));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't retry the failed files"));
    }
  };

  const target = picker !== "auto" ? picker : selected?.companyId ?? null;
  const targetName = companies.find((c) => c.id === target)?.registered_name;

  const onDrop = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      if (upload && (BUSY.includes(upload.status) || upload.status === "awaiting_confirmation")) {
        setError("Finish the current upload before dropping more files.");
        return;
      }
      setError("");
      setNotice("");
      try {
        setUpload(await accountingApi.upload(files, target ?? undefined));
      } catch (e) {
        setError(apiErrorMessage(e, "Upload failed"));
      }
    },
    [target, upload],
  );

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    onDropRejected: () => setError("Only PDF, PNG and JPG files can be dropped here."),
    accept: ACCEPT,
    noClick: true,
    noKeyboard: true,
    // Files dropped anywhere on the page upload, except over a dialog or the import screen (it takes its own file).
    noDrag: !!openDoc || reviewOpen || !!companyForm || selected?.view === "import",
  });

  const filteredTree = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return tree;
    const digits = q.replace(/\D/g, "");
    return tree.filter((c) => c.registered_name.toLowerCase().includes(q) || (digits.length > 0 && c.tin.includes(digits)));
  }, [tree, search]);

  async function confirm(assignments: ConfirmAssignment[]) {
    if (!upload) return;
    setUpload(await accountingApi.confirmUpload(upload.id, assignments));
    setReviewOpen(false);
  }

  async function companySaved() {
    setCompanyForm(null);
    await Promise.all([loadCompanies(), loadTree()]);
    // A drop waiting on its company picks up where it left off, with the new company matched by TIN.
    if (upload?.status === "awaiting_confirmation") setReviewOpen(true);
  }

  const editCompany = (id: string) => {
    const c = companies.find((x) => x.id === id);
    if (c) setCompanyForm({ initial: c, id });
  };

  const refreshAfterDocChange = () => {
    loadFolder(selected).catch(() => undefined);
    loadTree().catch(() => undefined);
    setPeriodRefresh((n) => n + 1);
  };

  return (
    <div {...getRootProps({ className: "lp relative min-h-screen" })}>
      <input {...getInputProps()} />
      {isDragActive && (
        <div className="pointer-events-none fixed inset-0 z-30 flex items-center justify-center bg-[var(--accent-subtle)]/80 p-6">
          <div className="rounded-xl border-2 border-dashed border-[var(--accent)] bg-[var(--bg-secondary)] px-8 py-6 text-center text-sm font-semibold text-[var(--text-primary)] shadow-lg">
            {targetName ? `Drop to file under ${targetName}` : "Drop to auto-detect the company"}
          </div>
        </div>
      )}
      <div className="p-4 sm:p-8 page-enter">
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <div className="mr-auto min-w-[16rem] flex-1">
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">Documents</h1>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              Drop a client&apos;s receipts and invoices. They&apos;re matched to the company and filed by quarter.
            </p>
          </div>
          <GuideButton open={guide.open} onClick={guide.toggle} />
          <div className="flex items-center gap-1">
            <CompanyPicker companies={companies} value={picker} onChange={choosePicker} />
            <Hint align="left">
              Auto-detect reads each document&apos;s TIN and name to find the company. Pick a company instead when every file
              you&apos;re about to drop belongs to one client; it&apos;s filled in for you when you confirm.
            </Hint>
          </div>
        </div>

        <GuideTour open={guide.open} onClose={guide.dismiss} label="Documents" slides={DOCUMENTS_TOUR} />
        <GettingStarted
          tree={tree}
          canManage={canManage}
          memberCount={memberCount}
          onAddCompany={() => setCompanyForm({})}
          onUpload={open}
          onOpenQuarter={(q, companyId) => setSelected({ companyId, year: q.year, quarter: q.quarter })}
        />

        {error && (
          <div className="mb-4 rounded-lg border border-[var(--alert-error-border)] bg-[var(--alert-error-bg)] px-4 py-2 text-sm text-[var(--alert-error-text)]">
            {error}
          </div>
        )}
        {notice && (
          <div className="mb-4 flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--accent-subtle)] px-4 py-2 text-sm text-[var(--text-primary)]">
            {notice}
            {retryable && (
              <button className="font-semibold underline" onClick={retryFailed}>Try the failed files again</button>
            )}
          </div>
        )}
        {upload && BUSY.includes(upload.status) && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-2 text-sm text-[var(--text-primary)]">
            <Spinner size={16} className="animate-spin" />
            {upload.status === "detecting" ? "Detecting companies" : "Reading and filing documents"} ·{" "}
            {upload.processed_files}/{upload.total_files}
          </div>
        )}
        {upload?.status === "awaiting_confirmation" && !reviewOpen && (
          <div className="mb-4 flex items-center gap-3 rounded-lg border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] px-4 py-2 text-sm text-[var(--alert-warning-text)]">
            Your last drop is waiting for you to confirm the company.
            <button className="font-semibold underline" onClick={() => setReviewOpen(true)}>Review now</button>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-[250px_minmax(0,1fr)]">
          <aside className="h-fit rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-3">
            <label className="relative mb-2 block">
              <span className="sr-only">Search companies or TINs</span>
              <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search companies or TINs"
                className="w-full rounded-full border border-[var(--border)] bg-[var(--bg-secondary)] py-1.5 pl-8 pr-3 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </label>
            <FolderTree
              tree={filteredTree}
              selected={selected}
              onSelect={(ref) => {
                setDeepContact(null);
                setSelected(ref);
              }}
              canManage={canManage}
              onAddCompany={() => setCompanyForm({})}
            />
          </aside>

          <section className="relative min-h-[420px] rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
            {folder && <DuplicateBanner folder={folder} onResolved={refreshAfterDocChange} />}
            {selected?.view !== "import" && (
              <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-dashed border-[var(--border)] px-4 py-3">
                <UploadSimple size={20} className="shrink-0 text-[var(--text-secondary)]" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-[var(--text-primary)]">Drop receipts, invoices or scans anywhere on this page</p>
                  <p className="text-xs text-[var(--text-secondary)]">
                    {targetName
                      ? `They'll be filed under ${targetName.replace(/\.$/, "")}.`
                      : "We'll detect the company from each document's TIN and name."}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={open}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)]"
                >
                  <UploadSimple size={16} /> Upload files
                </button>
              </div>
            )}
            {folder && folder.year !== null && folder.quarter !== null && (
              <PeriodPanel
                companyId={folder.company.id}
                year={folder.year}
                quarter={folder.quarter}
                refreshKey={periodRefresh}
                onChanged={() => loadTree().catch(() => undefined)}
                onEditCompany={() => editCompany(folder.company.id)}
              />
            )}
            {selected?.quarter === 0 && selected.year !== null && (
              <AnnualPanel
                companyId={selected.companyId}
                companyName={tree.find((c) => c.id === selected.companyId)?.registered_name ?? ""}
                year={selected.year}
                refreshKey={periodRefresh}
                onChanged={() => loadTree().catch(() => undefined)}
              />
            )}
            {selected?.view === "books" && selected.year !== null && (() => {
              const company = tree.find((c) => c.id === selected.companyId);
              return company?.books_start ? (
                <BooksPanel
                  key={`${selected.companyId}-${selected.year}`}
                  companyId={selected.companyId}
                  year={selected.year}
                  booksStart={company.books_start}
                  fiscalYearEndMonth={company.fiscal_year_end_month}
                  canManage={canManage}
                  onChanged={() => loadTree().catch(() => undefined)}
                />
              ) : null;
            })()}
            {selected?.view === "employees" && selected.year !== null && (
              <EmployeesPanel
                key={`${selected.companyId}-${selected.year}`}
                companyId={selected.companyId}
                companyName={tree.find((c) => c.id === selected.companyId)?.registered_name ?? ""}
                year={selected.year}
                canManage={canManage}
              />
            )}
            {selected?.view === "atc" && (
              <AtcDatabankPanel
                key={selected.companyId}
                companyId={selected.companyId}
                companyName={tree.find((c) => c.id === selected.companyId)?.registered_name ?? ""}
                onChanged={() => {
                  loadTree().catch(() => undefined);
                  setPeriodRefresh((n) => n + 1);
                }}
              />
            )}
            {selected?.view === "bank" && selected.month && (
              <BankPanel
                key={`${selected.companyId}-${selected.bankAccount}-${selected.month}`}
                companyId={selected.companyId}
                account={selected.bankAccount ?? ""}
                month={selected.month}
                canManage={canManage}
                onChanged={() => {
                  loadTree().catch(() => undefined);
                  setPeriodRefresh((n) => n + 1);
                }}
              />
            )}
            {(selected?.view === "customers" || selected?.view === "suppliers") && (
              <ContactsPanel
                key={`${selected.companyId}-${selected.view}-${deepContact ?? ""}`}
                companyId={selected.companyId}
                companyName={tree.find((c) => c.id === selected.companyId)?.registered_name ?? ""}
                role={selected.view === "customers" ? "customer" : "supplier"}
                initialContactId={deepContact}
                canManage={canManage}
                onOpenDocument={(id) =>
                  accountingApi
                    .getDocument(id)
                    .then(setOpenDoc)
                    .catch((e) => setError(apiErrorMessage(e, "Couldn't open the document")))
                }
              />
            )}
            {selected?.view === "reports" && (() => {
              const company = tree.find((c) => c.id === selected.companyId);
              return company?.books_start ? (
                <ReportsPanel
                  key={selected.companyId}
                  companyId={selected.companyId}
                  companyName={company.registered_name}
                  fiscalYearEndMonth={company.fiscal_year_end_month}
                  onOpenDocument={(id, page) =>
                    accountingApi
                      .getDocument(id)
                      .then((d) => {
                        setOpenDocFocus(page ? { id: d.id, page } : null);
                        setOpenDoc(d);
                      })
                      .catch((e) => setError(apiErrorMessage(e, "Couldn't open the document")))
                  }
                />
              ) : (
                <p className="py-6 text-sm text-[var(--text-secondary)]">Set a Books start on the company to see its reports.</p>
              );
            })()}
            {selected?.view === "reclassify" && (() => {
              const company = tree.find((c) => c.id === selected.companyId);
              return company?.books_start ? (
                <ReclassifyPanel
                  key={selected.companyId}
                  companyId={selected.companyId}
                  companyName={company.registered_name}
                  fiscalYearEndMonth={company.fiscal_year_end_month}
                  onOpenDocument={(id) =>
                    accountingApi
                      .getDocument(id)
                      .then(setOpenDoc)
                      .catch((e) => setError(apiErrorMessage(e, "Couldn't open the document")))
                  }
                  onChanged={() => {
                    loadTree().catch(() => undefined);
                    setPeriodRefresh((n) => n + 1);
                  }}
                />
              ) : (
                <p className="py-6 text-sm text-[var(--text-secondary)]">Set a Books start on the company to reclassify its postings.</p>
              );
            })()}
            {selected?.view === "import" && (() => {
              const company = tree.find((c) => c.id === selected.companyId);
              return company?.books_start ? (
                <ImportPanel
                  key={selected.companyId}
                  companyId={selected.companyId}
                  companyName={company.registered_name}
                  onChanged={() => {
                    loadTree().catch(() => undefined);
                    setPeriodRefresh((n) => n + 1);
                  }}
                />
              ) : (
                <p className="py-6 text-sm text-[var(--text-secondary)]">Set a Books start on the company to import opening balances and journals.</p>
              );
            })()}
            {selected?.view === "overview" && (
              <CompanyOverviewPanel
                key={selected.companyId}
                companyId={selected.companyId}
                companyName={tree.find((c) => c.id === selected.companyId)?.registered_name ?? ""}
                companies={companies}
              />
            )}
            {selected?.view === "audit" && (
              <AuditLogPanel
                key={selected.companyId}
                companyId={selected.companyId}
                companyName={tree.find((c) => c.id === selected.companyId)?.registered_name ?? ""}
              />
            )}
            {folder ? (
              <FileGrid
                folder={folder}
                category={category}
                onCategory={setCategory}
                onOpen={setOpenDoc}
                onBulkResolved={refreshAfterDocChange}
                onEditCompany={canManage ? () => editCompany(folder.company.id) : undefined}
              />
            ) : selected?.quarter === 0 || selected?.view ? null : (
              <>
                <p className="py-10 text-center text-sm text-[var(--text-secondary)]">
                  {tree.length === 0
                    ? "Nothing filed yet. Drop a client's documents anywhere on this page and they'll show up on the left, sorted by company and quarter."
                    : "Open a company on the left and pick a quarter to see its documents and returns."}
                </p>
                <AlphalistChecklist onOpen={(companyId, year) => setSelected({ companyId, year, quarter: null, view: "employees" })} />
              </>
            )}

          </section>
        </div>
      </div>

      {reviewOpen && upload?.status === "awaiting_confirmation" && (
        <UploadReviewDialog
          upload={upload}
          companies={companies}
          canManage={canManage}
          onCompanyCreated={() => {
            loadCompanies().catch(() => undefined);
            loadTree().catch(() => undefined);
          }}
          onConfirm={confirm}
          onClose={() => setReviewOpen(false)}
        />
      )}

      {companyForm && (
        <CompanyForm
          initial={companyForm.initial}
          companyId={companyForm.id}
          onClose={() => setCompanyForm(null)}
          onSaved={companySaved}
        />
      )}

      {openDoc && (
        <DocumentPanel
          doc={openDoc}
          focusPage={openDocFocus?.id === openDoc.id ? openDocFocus.page : undefined}
          onClose={() => setOpenDoc(null)}
          onChanged={(d) => {
            setOpenDoc(d);
            refreshAfterDocChange();
          }}
          onDeleted={() => {
            setOpenDoc(null);
            refreshAfterDocChange();
          }}
        />
      )}
      {append && (
        <AppendPrompt
          periods={append}
          onGenerate={async (p) => {
            await accountingApi.generate(p.company_id, p.year, p.quarter);
            await loadTree();
            setSelected({ companyId: p.company_id, year: p.year, quarter: p.quarter });
            setPeriodRefresh((n) => n + 1);
          }}
          onReview={(p) => {
            setAppend(null);
            setSelected({ companyId: p.company_id, year: p.year, quarter: p.quarter });
          }}
          onClose={() => setAppend(null)}
        />
      )}
    </div>
  );
}
