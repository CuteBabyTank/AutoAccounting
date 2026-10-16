# QuickBooks Online Accountant: feature catalogue

Reference for AutoAccounting planning. Captured 2026-10-16 by walking every page of QuickBooks Online **Accountant**
(company subscription **Advanced**, region PH, home currency PHP) in the `MFS_Test` company after loading the Q4 2026
test pack. Every page, menu, form, settings panel and report area below was opened. Nothing was saved, except the test
data described in `../plans/2026-10-16-quickbooks-parity-plan.md`, and two zero-balance accounts QBO added on its own
("System Administration" in the audit log): *Reconciliation Discrepancies* and *Inventory Shrinkage*. A second pass
re-opened every nav, gear-menu and Accountant-tools URL and confirmed the catalogue below.

Each feature lists **what it is**, then **what it does** in practice, plus the URL where useful. The last column of each
table, **AA**, is a one-word read on AutoAccounting: ✅ have · 🟡 partial · ❌ missing · ⛔ out of scope.

---

## 0. Global shell (on every page)

| Feature | What it does | AA |
|---|---|---|
| **Left nav: Your practice** | Firm-level area: Clients, Work, Team, Training, Apps. | 🟡 |
| **Left nav: Bookmarks** | User-pinned pages (pencil icon to edit). | ❌ |
| **Left nav: Your books** | Per-client areas: Client overview, Dashboards, Tasks, Transactions, Advanced accounting, Sales, Expenses, Reports, Employees, Time, Inventory, Projects, Financial planning, Workflow automation, Taxes. Each section has a flyout submenu. **Menu settings** lets the user hide or reorder sections. | ✅ (different shape) |
| **+ New** | One launcher for ~30 transaction types, grouped Customers / Suppliers / Team / Projects / Other (see §4). | 🟡 (Upload + JE form) |
| **Go to QuickBooks ▾** | Client switcher: jump into any client company's books. The accountant stays signed in once across all clients. | ✅ (company picker) |
| **Accountant tools** | Quick links (Chart of accounts, Journal entries, Reconcile, Reports, Voided/deleted transactions, Close books, New window) and Tools (Reclassify transactions, Reports options, Write off invoices, COA templates). | 🟡 |
| **Global search** ("Navigate. Find transactions, contacts, help, reports…") | Type-ahead across transactions (type, number, name, date, amount, paid status), contacts, reports and help. **Advanced transactions search** gives the full filter screen. Results were thumb-rated. | ❌ |
| **Business feed** | Firm feed of tasks and alerts; currently routes to Tasks. | ❌ |
| **Help** | Side panel: help-article search filtered by product, "people like you viewed" suggestions, Contact us. | ⛔ |
| **Apps (grid icon)** | "My apps": installed integrations. | ⛔ |
| **Notifications (bell)** | Inbox / Recommended tabs, list or filter view, alerts. | ❌ |
| **Gear menu** | Settings (Company settings, Custom form styles, Default report settings, Chart of accounts, Mobile app, Additional info) · Lists (All lists, Products & services, Recurring transactions, Attachments, Custom fields, Rules) · Tools (Manage workflows, Reclassify, Import data, Export data, Reconcile, Budgeting, Audit log, Merge duplicate clients, Share screen, Transfer clients) · Your company (What's new, Subscriptions & billing, Your team, Sample company, Feedback, Privacy, Switch company). | — |
| **Give feedback / Take tour / video tutorials** | On nearly every page; guided tours on forms and the bank feed. | 🟡 (page guides exist) |
| **Privacy toggle** | On dashboards: hides all amounts (screen-share safe). | ❌ |
| **"Leave site?" protection** | Forms warn on unsaved changes. | ✅ |

---

## 1. Your practice (firm level)

| Feature | What it does | AA |
|---|---|---|
| **Clients** (`/app/clients`) | Client list with two views. **Overview**: client/contact, email/phone, banking status, lead accountant, actions (open books); filter by client type (subscription etc.), lead accountant, search. **Bookkeeping**: per-client **books review** status and lead, with "start month-end reviews". **Client invitations** tab. Bulk-edit client numbers. **Customise** columns. **Add client**. | 🟡 |
| **Work** (`/app/work`) | Practice-management board: **Projects** and **All tasks** across clients, filter by client, due date, status; columns client, project, due date, status, tasks done, assigned to. **Manage templates** (reusable checklists such as monthly close), **Create project**, notification settings. | ❌ |
| **Team** (`/app/usermgt`) | Firm users: name, email, status, role; **Roles** tab (custom roles); **Configure Single Sign-On (SSO)**; transfer primary admin; add user. | ✅ (team page; SSO = Google) |
| **Training** | ProAdvisor training/certification hub. | ⛔ |
| **Apps** (`/app/appcenter/allapps`, `/clientapps`, `/firmapps`) | App marketplace: client apps vs firm apps, categories, industries, featured, popular, editors' picks, free; e.g. Double (AI month-end close), Dext (receipt/invoice capture), Fathom, Syft (reporting and consolidations). Note: these are AutoAccounting's direct competitors in the capture layer. | ⛔ |
| **Merge duplicate clients / Transfer clients / Share screen** | Gear → Tools; firm housekeeping and remote support. | ⛔ |
| **Subscriptions and billing** (`/app/yourAccount`) | Accountant-billed vs client-billed subscriptions, billing details, payment method, VAT-registered toggle and VAT ID for the invoice; **Tax location** tab. | 🟡 (page-rate billing) |

---

## 2. Client overview & dashboards

| Feature | What it does | AA |
|---|---|---|
| **Client overview** (`/app/overview`) | Accountant health check for one client. **Company setup** (subscription, sales tax status). **Banking activity** per account: bank balance, in QuickBooks, **unaccepted** count, **unreconciled** count, **reconciled through** date ("Never reconciled"). **Common issues**: undeposited funds (uncleared), uncategorised asset/income/expense counts, A/R aging >90 days, A/P aging >90 days, opening balance equity, **negative asset and liability accounts** (it flagged our Cash on hand). **Transaction volume** over a date range. Print/export. | ❌ (strong idea) |
| **Get things done** (`/app/homepage`) | Shortcuts (add product/service, customer, sales receipt, receipt, supplier, expense, bill, pay bill), bank-accounts widget (bank vs book balance, "Reviewed", go to registers), see all activity. | 🟡 |
| **Business overview** (`/app/business-overview`) | Widget dashboard: **Cash flow** (12-month line of cash balance, projected balance, threshold; money in/out toggle), **Profit & loss** (net profit last month vs prior, income/expense bars), **Expenses** (spending last 30 days by account, change vs prior period), **Bank accounts**, **Invoices** (unpaid/overdue/not due/paid/deposited), **Sales**. **Customise**: drag, resize, add/remove widgets. | ❌ |
| **Cash flow** (`/app/cashflowoverview`) | Today's cash across bank and card accounts; cash-flow chart with projection and threshold; **Monthly outlook**: money in (overdue/open invoices, paid this month) and money out (overdue/open bills, paid); **Coming up** calendar of due invoices and bills; loans upsell; insights. | ❌ |
| **Planner** (`/app/cashflowplanner`) | Cash-flow forecast from past trends, add planned in/out items, what-if scenarios without touching the books. | ⛔ |
| **Tasks** (`/app/taskmanager`) | To-dos linked to invoices/bills; columns task, status, **priority**, due date, assigned to, created by. | ❌ |

---

## 3. Transactions

| Feature | What it does | AA |
|---|---|---|
| **Bank transactions / bank feed** (`/app/banking`) | One tile per bank or card account (bank balance vs in-QuickBooks, items to review, edit). Tabs **For review / Categorised / Excluded**. Filters (dates, type), search by description/cheque no./amount, print, export, column settings. Per line: **Categorise** (payee, account or product/service, memo, **Split** across lines, attach file, **Create a rule**, **Exclude**), **Match** (suggested matches with "N matches found"; **Find other matches** opens an advanced matcher where you tick several invoices or bills, enter partial amounts and "resolve the difference"), **Record as transfer** (pairs a line with its mirror in another account), **Record as credit card payment**. **Batch**: Accept / Edit / Exclude N selected. The Categorised tab shows what each line was added to or matched with, the rule used, and **Undo**. Paired-transfer confirmation banner. Two UIs ("Try new banking page"); the new one's Match buttons did not respond in our run. | ❌ (P1) |
| **Link account ▾** | Connect a bank via feeds; **Upload from file**: CSV, QFX, QBO, OFX, TXT **and PDF/JPG/PNG/HEIC statements** ("our team of global experts reviews some statements"); Manage connections. | ❌ |
| **Bank file upload wizard** | Pick account → is row 1 a header → one or two amount columns → date format → map Date/Description/Amount/Cheque no. → choose rows → keep or **reverse signs** → import → "accept your transactions". | ❌ |
| **App transactions** (`/app/apptransactions`) | Sales-channel connectors (Shopify, Squarespace, Wix, Etsy, eBay, Amazon, WooCommerce) feeding transactions. | ⛔ |
| **Rules** (`/app/olbrules`) | **Bank rules** and **App rules**. New rule: name; money in/out; which accounts; **All/Any** conditions on bank text, description or amount (contains / doesn't contain / is exactly / greater/less than); **Test rule**; **Priority** order; **Preview** of affected lines; actions: transaction type (expense, transfer, cheque), payee, category, **split by percentage or amount**, class/location, memo, **Auto-post** (skip review). **Import rules / Export rules** (move rules between clients). | 🟡 (ATC/supplier databank) |
| **Reconcile** (`/app/reconcile`) | Choose account; beginning balance (from the last reconcile), **statement ending balance and date**; enter **service charge** (date, amount, expense account) and **interest earned** (date, amount, income account); then tick cleared items until the difference is 0. **Summary** tab: saved reconciliation reports per account (print/export). **History by account**. Links to Chart of accounts and Register. | ❌ (P1) |
| **Account register** (`/app/register?accountId=`) | Account history: running balance, **cleared status** (blank/C/R), inline entry with a type switcher (Cheque, Deposit, Sales receipt, Receive payment, Bill payment, Refund, Expense, Transfer, Journal entry; Ctrl-Alt-N), splits, filters, print/export, column settings; bank balance vs ending balance. | 🟡 (GL in books) |
| **Chart of accounts** (`/app/chartofaccounts`) | List with type, detail type, QuickBooks balance, bank balance; filter by name/number and type; **Run report**; **Edit mode** (bulk inline edit); batch make inactive; print/export. **New account**: name, type grouped Asset (cash & equivalents, A/R, current, fixed, non-current), Liability (credit card, A/P, current, non-current), Equity, Income (income, other income), Expense (cost of sales, expenses, other expense); detail type; **subaccount of**; **opening balance + as-of date**; description; **Lock account** (prevent posting); a live **"New account preview"** showing where it lands on the BS/P&L. Row actions: Account history, Edit, Run report (QuickReport), Reconcile, Create subaccount, Link account, **Make inactive (reduces usage)**. Optional **account numbers** (setting). | ✅ |
| **Recurring transactions** (`/app/recurring`) | Templates: name, type (**Scheduled** auto-creates, **Reminder** prompts, **Unscheduled** = saved template), transaction type, interval, previous/next date, customer/supplier, amount. **Reminder list**. Every form has **Make recurring**. | ❌ |

---

## 4. Transaction forms (+ New)

Common to most forms: attachments (20 MB each, "show existing" picks from the library), memo, **Make recurring**, print,
Save / Save and new / Save and close, **More** (copy, void, delete, transaction journal, **audit history**), autosave
warnings, numbering (custom transaction numbers setting), and a **customer/billable** column on expense lines.

| Form | What it does | AA |
|---|---|---|
| **Invoice** (`/app/invoice`) | Tabs Edit / **Email view** / **PDF view**. Customer (bill-to, ship-to), invoice no., terms, invoice date, due date (auto from terms); lines: service date, product/service, SKU, description, qty, rate, amount; **Edit totals** (discount, deposit, shipping); customer payment options (online card/bank); note to customer; memo on statement; **balance due can be hidden**. **Manage** panel: Customisation (show/hide fields and columns, edit labels, company registration number, custom fields), Payment options, Design (template, colours, logo, fonts), Scheduling (recurring, print later, send later). Review and send (email), share link, print/download. | ⛔ (we read invoices, we don't issue them) |
| **Receive payment** (`/app/recvpayment`) | Customer, **find by invoice no.**, date, method, ref, deposit-to; outstanding invoices with an editable payment column (partial pay); **Credits** section applies credit notes; amount to apply / to credit (overpayment); email receipt. | ❌ (P1 A/R) |
| **Statement** (`/app/statements`) | Statement date, **type** (balance forward / open item / transaction statement), customer balance-status filter, date range, recipients with emails and balances; print, save and send. Setting: aging table at the bottom. | ❌ |
| **Estimate** (`/app/estimate`) | Estimate no., date, **expiration**, **accepted by / accepted date**, status, lines, discounts and fees; **e-signature** acceptance; converts to invoice; **progress invoicing** (partial invoices from one estimate). | ⛔ |
| **Sales order** | Bill-to, SO no., date, terms, due date, lines (copy/delete row), **deposit request**, internal memo; converts to invoice or PO, kept linked. | ⛔ |
| **Credit note** | Customer credit, auto-applied via Receive payment (it was **not** auto-applied in our run until a payment form was opened). | 🟡 |
| **Sales receipt** | Cash sale: customer, payment method, deposit-to (or Undeposited funds), lines. | ✅ (cash sales from docs) |
| **Refund receipt** | Customer refund: payment method, **refund from** account, lines, messages, total refunded. | ❌ |
| **Delayed charge / Delayed credit** | Non-posting items that drop onto the customer's next invoice. | ⛔ |
| **Expense** (`/app/expense`) | **"Autofill this expense"** (generative-AI extraction from PDF/PNG/JPEG/HEIC or **Snap photos**, "review before you save"); payee, payment account (shows live balance), date, payment method, ref no.; category lines (category, description, amount, customer) and item lines; memo; attachments. | ✅ (core pipeline, deeper) |
| **Cheque** | Payee, bank account (balance), mailing address, date, **cheque no.** (duplicate-number warning), lines; print cheque. | 🟡 |
| **Bill** (`/app/bill`) | **"Autofill this bill"** (same AI, drag and drop or snap); supplier, mailing address, terms, bill date, due date, bill no.; category and item lines; **Mark as paid** after saving (pick account and date); recurring; approval routing (workflow). | ✅ (pipeline) |
| **Pay bills** (`/app/paybills`) | Pay many bills at once: payment account (balance), payment date, ref no., due-date filter; per bill: status, approval, open balance, **credit applied**, payment amount; total; print cheques. **Manage recurring bills**. | ❌ (P1 A/P) |
| **Purchase order** | Supplier (email/cc/bcc), status OPEN/closed, ship-to, ship via, PO date, due date, lines, message to supplier; copy to bill or item receipt. | ⛔ |
| **Item receipt** | Receive inventory before the bill arrives; matched later. | ⛔ |
| **Supplier credit** | Supplier, amount, date, ref, lines; consumed in Pay bills. | 🟡 |
| **Credit card credit** | Refund to a credit card. | 🟡 |
| **Pay down credit card** | Which card, payee, amount, date, paid-from account. | ❌ |
| **Bank deposit** | Deposit-to account, date; **add funds from Undeposited funds** (customer payments waiting to be banked); other lines (received from, account, method, ref, amount); track returns; **cash back** (account, memo, amount); print deposit slip. | ❌ |
| **Transfer** | From/to accounts (live balances), amount, date, memo. | ❌ |
| **Journal entry** (`/app/journal`) | Date, **auto-incremented journal no.**, **"Is adjusting journal entry?"** flag (drives the Adjusted TB and adjusting-JE reports), lines account/debit/credit/description/name with running totals, **Import** (CSV JE import), memo, attachments, recurring. | ✅ (`JournalEntryForm.tsx`; no AJE flag) |
| **Inventory adjustment** | **Autofill (beta AI)** from a document; adjustment type (quantity or value), date, ref, **reason**, adjustment account; items with qty on hand → new qty → change. | ⛔ |
| **Single time activity / Weekly timesheet / Review time** | Time capture for billing and payroll. | ⛔ |
| **Project / Task** | Create a project for a customer; quick task. | ❌ (Task) |

---

## 5. Sales & customers

| Feature | What it does | AA |
|---|---|---|
| **Sales overview** (`/app/incomeoverview`) | Quick-action tiles (customer, product, estimate, invoice, recurring invoice, receive payment, sales receipt, bank deposit, create statement); **income over time** chart with prior-year compare; invoice funnel (unpaid/overdue/not due, paid last 30 days, not deposited/deposited). | ❌ |
| **All sales** (`/app/sales`) | KPI strip (estimates, unbilled income, overdue invoices, open invoices and credits, recently paid) that filters the list; filters by type, date, customer, status, delivery method, errors; columns date/type/no./customer/memo/amount/**status** (Paid, Partially paid with amount due, Closed, Applied); row actions (receive payment, print, send); batch actions; new transaction. | 🟡 |
| **Invoices** (`/app/invoices`) | Funnel bar (₱ unpaid, overdue, not due, paid, deposited); status chips like "Due in 17 days" or "Partially paid ₱81,476.80 due"; batch actions (send, print, reminders). | ❌ |
| **Customers** (`/app/customers`) | Same KPI strip; columns name, company, phone, **open balance**; row action Create invoice / Receive payment; batch email, statements, make inactive; import/export. | ❌ (P1) |
| **Customer detail** (`/app/customerdetail`) | Left rail of recent customers with balances; header contact card; **financial summary** (open balance, overdue); tabs **Transaction list**, **Statements**, **Recurring transactions**, **Projects**, **Customer details**, **Notes**, **Tasks**, **Conversations** (email threads). Edit ▾: **Make inactive**, **Merge contacts**. New transaction ▾: invoice, payment, estimate, sales order, sales receipt, credit note, delayed charge, time activity, statement. | ❌ (P1) |
| **Customer form** | Name parts, display name, company, email, phone, cc/bcc, mobile, fax, other, website; **sub-customer** (bill with parent); billing/shipping address; notes and attachments; payments (primary method, **terms**, invoice language); additional info (**tax registration / TIN**, **opening balance + as-of**); custom fields. | 🟡 (TIN on docs) |
| **Products & services** (`/app/items`) | Search by name/SKU/category, type and stock filters, customisable columns; More ▾ **Manage categories**, Run reports, **Starting value**; New ▾ Service / Inventory item / Non-inventory item / **Bundle** / **Batch import** (spreadsheet grid with column mapping and "overwrite existing"). Item form: name, image, SKU, category, **valuation method FIFO or moving-average cost**, qty on hand and as-of, reorder point, inventory asset account, sales description/price/income account, purchase description/cost/preferred supplier/expense account. | ⛔ |

---

## 6. Expenses & suppliers

| Feature | What it does | AA |
|---|---|---|
| **Expenses list** (`/app/expenses`) | Every money-out transaction (expense, bill, bill payment, cheque…); date filter; columns no., payee, category (**inline-editable category dropdown** on single-line rows), total before tax, tax, total, bill approval; row ▾ print, copy, delete, **void**; New transaction ▾ time activity, bill, expense, cheque, PO, supplier credit, credit card credit, pay down card, **Import bills**; Pay bills. | 🟡 |
| **Bills** (`/app/bills`) | Tabs **For review** (AI inbox: "Upload files to create bills automatically", columns bill, **source**, supplier, bill no., date, category, due date, amount), **Unpaid** (status "Due in N days" / overdue, **Mark as paid**), **Paid**. Add bill ▾: Create bill, **Create recurring bill**, **Upload multiple bills**. Pay bills ▾ Manage recurring bills. | 🟡 (review queue is ours) |
| **Purchase orders** | PO list and lifecycle (open → closed via bill/item receipt). | ⛔ |
| **Suppliers** (`/app/vendors`) | KPI strip (unbilled POs, overdue, **open bills**, **paid last 30 days**); open balance per supplier; row Create bill / Make payment. | ❌ (P1) |
| **Supplier detail** (`/app/vendordetail`) | Left rail of all suppliers with balances; company, billing address, **Bill Pay ACH info**, notes; summary (open balance, overdue); tabs Transaction list (with Mark as paid), Supplier details, Notes. | ❌ (P1) |
| **Supplier form** | Contact fields, address, notes/attachments, **Business ID no.** (TIN), billing rate, **terms**, **default expense category** (auto-categorises new bills), opening balance + as-of, custom fields. | 🟡 (ATC databank) |

---

## 7. Advanced accounting

| Feature | What it does | AA |
|---|---|---|
| **Revenue recognition** (`/app/revenue-recognition`) | ASC 606 schedules that defer and recognise revenue automatically (thousands of JEs), rules, period controls, report. | ⛔ |
| **Fixed assets** (`/app/fixed-assets`) | Asset register, **add one or many assets**, automatic depreciation, fixed-asset reports. | ✅ (`assets.py`) |
| **Prepaid expenses** (`/app/accruals`) | Amortisation schedules for prepayments: creation date, source transaction, period start, periods, next amortisation, total, current balance, status (**Draft** → active), **amortisation waterfall**. QBO **auto-drafted** a 13-period schedule from our ₱1,515 prepaid-load receipt, which was wrong. | ❌ |

---

## 8. Reports

### 8.1 Report tabs

| Tab | What it does | AA |
|---|---|---|
| **Standard reports** (`/app/standardreports`) | Catalogue grouped by section, star = favourite, ⋮ per report (customise, schedule, add to management report); **AI financial summary** card ("I generated a financial summary for September…", *Review summary*); **Custom report builder** (beta) entry; type-ahead report search. | 🟡 |
| **Custom reports** (`/app/customreports`) | Saved customisations: name, created by, last modified by, date range, **access** (who can see it), **email schedule**, actions. | ❌ |
| **Management reports** (`/app/managementreports`) | Packaged report books: **Company Overview**, **Sales Performance**, **Expenses Performance**; actions **Edit** (cover page, table of contents, preliminary pages, chosen reports, end notes, logo), **Send**, **Export as PDF**, **Export as DOCX**, **Duplicate**; create your own. | ❌ (P2 pack) |
| **KPIs** (`/app/business-intelligence/kpi-scorecard`) | KPI scorecard by period vs comparison period with variance and %: **Growth** (revenue, cost of sales, no./value of invoices, total and other expenses), **Profitability** (gross profit and margin, net profit and margin, operating expenses, opex ratio, expense % of revenue, net operating income, operating margin), **Cash flow** (operating cash flow, cash-flow margin), **Sales** (active customers, new customers, contacts, net sales, average revenue per customer). Create KPI, manage scorecard, cash/accrual, filters. | ❌ |
| **Dashboards** (`/app/business-intelligence/analytics-dashboard`) | Standard BI dashboards (**Profitability, Cash flow, Balance Sheet, Accounts receivable, Accounts payable, Revenue**) plus **Create dashboard** and favourites. | ❌ |
| **Spreadsheet sync** (`/app/spreadsheetsync`) | Excel/Google Sheets add-in: run reports into a sheet, **2-way sync** (bulk add/edit data in a sheet and post back), **multi-company consolidated reports**, budgets in sheets. | ❌ |
| **Performance centre** (`/app/insights/dashboard`) | Chart canvas (9 of 25 used): **A/R by ageing periods** (current, 1–7, 8–14, 15–21, 22–28 days, 29 days–2 months, 2–6 months, >6 months), **A/P by ageing**, expenses by time, revenue by time, gross profit by time, net profit by time, cash flow, **current ratio**, **quick ratio**; quick-add/custom charts, layout, export. | ❌ |

### 8.2 Report viewer (any report)

Report period presets and custom from/to; **Cash vs Accrual** toggle; **Quick actions** (display columns by Total,
Customer, Employee, Product/Service, Supplier, Days, Weeks, Months, Quarters, Years; **compare to** previous
period/year); **Customise** drawer: *Data* (filters by account, customer, supplier, product, class, location, tag…;
show rows/columns active, all or non-zero; number format divide by 1000, without cents, hide zero, negatives in
parentheses/red; comparison columns PP/PY/YTD with ₱ and % change; % of row/column/income/expense; ageing method,
days per period, number of periods, minimum days past due; edit section titles) and *Visual* (header/footer,
highlights, banded rows, gridlines). Toolbar: refresh, email, print, **export to Excel/PDF**, **Schedule report**,
**Add to management reports**, **Insights** (AI commentary panel), **Add note**, compact/zoom, **Save as** custom
report. **Drill-down** from any amount to the transactions, then to the form. Report-wide formatting lives in
Settings → Reports. **AA:** 🟡 (XLSX/PDF outputs; no drill-down or comparisons).

### 8.3 Standard report catalogue (every report listed)

- **Favourites:** A/R aging summary, Balance Sheet, Profit and Loss.
- **Featured:** Custom report builder, Revenue Recognition Report (beta), Inventory Status, Bill Approval Status,
  Product/Item Profitability by Customer, Invoice Approval Status.
- **Business overview:** Audit Log; Balance Sheet; Balance Sheet Comparison; Balance Sheet Detail; Balance Sheet
  Summary; Statement of Cash Flows; Business Snapshot; Custom Summary Report; Statement of Changes in Equity; Profit
  and Loss; P&L by Customer; P&L by Month; P&L by Tag Group; P&L Comparison; P&L Detail; P&L as % of Total Income; P&L
  Year-to-date Comparison; Quarterly P&L Summary.
- **Who owes you:** A/R Aging Summary; A/R Aging Detail; Collections Report; Customer Balance Summary; Customer
  Balance Detail; Invoice List; Invoices and Received Payments; Open Invoices; Statement List; Terms List; Unbilled
  Charges; Unbilled Time.
- **Inventory:** Inventory Valuation Detail; Inventory Valuation Summary; Open Purchase Order Detail; Open Purchase
  Order List; Physical Inventory Worksheet; Inventory Status.
- **Sales and customers:** Cashflow Payment Transactions; Sales by Customer Type Detail; Estimates & Progress Invoicing
  Summary by Customer; Customer Contact List; Income by Customer Summary; Customer Phone List; Sales by Customer
  Summary; Sales by Customer Detail; Deposit Detail; Estimates by Customer; Product/Service List; Sales by
  Product/Service Summary; Sales by Product/Service Detail; Payment Method List; Time Activities by Customer Detail;
  Transaction List by Customer; Transaction List by Tag Group.
- **What you owe:** A/P Aging Summary; A/P Aging Detail; Bills and Applied Payments; Bill Payment List; Unpaid Bills;
  Supplier Balance Summary; Supplier Balance Detail.
- **Expenses and suppliers:** Cheque Detail; Purchases by Product/Service Detail; Purchase List; Transaction List by
  Supplier; Purchases by Supplier Detail; Supplier Contact List; Expenses by Supplier Summary; Supplier Phone List.
- **Sales tax:** Tax Liability Report.
- **Employees:** Employee Contact List; Recent/Edited Time Activities; Time Activities by Employee Detail.
- **For my accountant:** Account List; **Invalid Journal Transactions**; General Ledger; General Ledger List; Journal;
  **Adjusting Journal Entries**; Recurring Template List; Recent Transactions; Reconciliation Reports; Trial Balance;
  **Adjusted Trial Balance**; Transaction Detail by Account; Transaction List by Date; Transaction List with Splits.
- **Payroll / Time:** Timesheet Detail by Employee; Time Summary by Pay Type.

---

## 9. Employees, time, inventory, projects, planning, workflows, taxes

| Area | What it does | AA |
|---|---|---|
| **Employees / Payroll** (`/app/employees`) | Payroll subscription: add employees, run paycheques, file and pay payroll taxes (not for PH here). | ✅ compliance side (1601-C, alphalist, 2316); ⛔ running payroll |
| **Time** (`/app/time/...`) | Overview (setup checklist, to-dos, shortcuts), **Time entries**, **Approvals**, **Schedule**, **Time team**, **Assignments** (assign workers to customers, time-tracking fields, **geofence** per site), **Time off**, **Time projects**, **Time reports** (payroll report: regular hours/breaks/overtime by pay period; itemised total time). | ⛔ |
| **Inventory** (`/app/inventory/...`) | **Overview** (low stock, out of stock, top-selling products with qty, sales, COS, gross profit, margin; open sales orders; open purchase orders; inventory reports; customisable layout), **Inventory** (products, adjustments), **Purchase orders**, **Item receipts** (receive vs PO/bill, discrepancies). | 🟡 periodic COGS only |
| **Projects** (`/app/projects`) | Project per customer job; tag transactions; project P&L, unbilled time, budget. | ⛔ |
| **Forecasts** (`/app/forecasts`) | Forecast from past trends; adjust accounts by fixed %; play with numbers without affecting the books. | ⛔ |
| **Budgets** (`/app/budgets`) | Create a budget from QBO data (by account/month, optionally by customer/class/location), **budget vs actual**, create in Spreadsheet Sync, **import budget**. | ⛔ |
| **Workflow automation** (`/app/workflow-templates`, `/app/workflows`) | Tabs **Templates / My workflows / History** plus a **Custom workflow** builder (trigger → conditions → actions, on/off, created/updated by). **38 templates**: *Approvals*: Bill, Invoice, Estimate and PO **multi-condition approval** (route to different approvers by amount, supplier, etc.). *Reminders*: pay supplier bill, send payment reminder (customer), unsent invoice, send estimate, open estimate, estimate follow-up, open PO, unsent PO, **sales tax due**, bank deposit, missing customer details, missing supplier details, unused supplier credit, take feedback after a sale. *Notifications* on create/update of PO, bill, invoice, estimate, expense, sales receipt, bank deposit and supplier credit; notify customer about payment received; notify supplier about payment. *Updates*: overdue invoice memo (adds a message to late invoices). *Report*: schedule and send a report. | ❌ (P2 slice) |
| **Taxes** (`/app/tax/home`) | Sales-tax setup wizard ("collect and track tax"), agencies, rates, returns, payments, Tax Liability report. Generic; no PH VAT, EWT, CWT, 2307 or BIR forms. | ✅ (our moat) |

---

## 10. Lists, settings & tools

### 10.1 Lists (`/app/lists`)

Chart of accounts · Recurring transactions · Products and services · **Product categories** · **Locations** (track by
branch/department) · **Custom fields** (`/app/customfields`: add fields to forms and contacts, then search, filter
and report on them) · **Payment methods** (cash, cheque… used on deposit slips) · **Terms** (due-in days, **early
payment discounts**) · **Classes** (second dimension, e.g. department) · **Tags** (tag groups) · **Attachments**
(`/app/attachments`: library with thumbnail, type, name, size, note, upload date, **links to transactions**, batch
actions, export; "My Accountant" shared documents) · **Custom form styles** (`/app/formstyles`: templates per form
type, set default). **AA:** 🟡 (chart ✅, document library ✅, locations/classes ❌ not needed for BIR).

### 10.2 Settings (`/app/settings`, `/app/accountsettings?p=`)

- **Company:** name, address, email, phone, website, industry; legal name, **TIN**, business type, legal address;
  customer-facing email and address.
- **Notifications:** work notifications by email (new assignments, due dates, details, status, project name,
  assignees, deletions).
- **Reports:** firm-wide report look (header, footer, column highlights, banded rows, empty cells, gridlines, number
  formatting) with a live preview.
- **Sales:** sales form content (preferred terms, delivery method, shipping, custom fields, **custom transaction
  numbers**, service date, discount, deposit, tags); invoice payments (online payments, payment instructions);
  products and services (product/service column, SKU, **price rules**, track qty and price, **track inventory qty on
  hand**, **inventory valuation method**, inventory receiving method, revenue recognition); **progress invoicing**;
  default email messages; **invoice reminder emails**; **Customer AI**; online delivery; statements (show aging
  table).
- **Expenses:** items table on expense forms, tags, **track expenses and items by customer**, **billable expenses**,
  default bill payment terms, purchase orders on/off, PO email message.
- **Time:** first day of the work week, show service field, billable time.
- **Advanced:** accounting method (cash/accrual); first month of the financial year and of the tax year; **Close the
  books** (closing date plus warn or password-protect changes before it); company type / tax form; **enable account
  numbers**; **track classes / locations**; automation (pre-fill forms from history, auto-invoice unbilled activity,
  **auto-apply bill payments**); project financial tracking; language; home currency, **multicurrency**; date and
  currency format; **duplicate warnings** (cheque no., bill no. per supplier, journal no.); inactivity sign-out.

### 10.3 Tools

| Tool | What it does | AA |
|---|---|---|
| **Import data** (`/app/importdata`) | CSV/XLSX/Google Sheets importers with column mapping and date-format selection: Bank data, Customers, Suppliers, Chart of accounts, Products & services (grid), Invoices, Credit notes, Sales receipts, Bills; hidden **Journal entries** and **Trial balances**. "Add new contacts/products that don't exist". No negative lines allowed. | 🟡 (employee import) |
| **Export data** (`/app/exportdata`) | Pick reports (General Ledger, P&L, Balance Sheet, Trial Balance, Journal) and lists with a date range, then **Export to Excel** as one zip. | ✅ (XLSX per period) |
| **Audit log** (`/app/auditlog`) | Filter by user, date changed, events; rows date, user, event, **history** (before/after for every field). Also **Voided/deleted transactions** view. | ❌ (P1) |
| **Reclassify transactions** (`/app/reclassify-transaction`) | Basis (cash/accrual), date range, P&L or BS account types → account list with totals → pick an account → see its transactions (filter by type) → **change account, class or location in bulk**. | ❌ (P2) |
| **Write off invoices** (`/app/writeoffinvoices`) | Find invoices by age, as-of date, balance under X → select → write off to an account in one go. | ❌ (P3) |
| **COA templates** (`/app/accounting/coa-templates`) | Create or import a reusable chart, apply it when onboarding a client. | 🟡 (one seeded chart) |
| **Close books** | Accountant tools shortcut to the closing date and password. | ✅ (month close/bind, stronger) |
| **Budgeting / Reconcile / Rules / Manage workflows** | See §3, §9. | — |

---

## 11. AI features QBO ships (where AutoAccounting competes)

1. **Autofill this bill / expense / inventory adjustment**: generative extraction from PDF or photo into a draft form,
   "review before you save".
2. **Bills → For review inbox** with **Upload multiple bills** and a *Source* column. This is the same idea as our
   upload queue, without PH validation.
3. **Bank statement upload as PDF/image** ("global experts review some statements").
4. **Bank-feed match suggestions** and **rules with auto-post**. Matching is on amount and date only (it picked wrong
   twice in our run).
5. **Prepaid-expense auto-drafts** in Advanced accounting (wrong for our phone-load receipt).
6. **Report Insights** panel and an **AI financial summary** on the reports page.
7. **Customer AI** setting (sales).
8. Marketplace AI apps for month-end close (Double, Dext): the capture layer QBO leaves to partners.

What none of these do: PH VAT classification (VATable/exempt/zero-rated per line), OR vs invoice rules, buyer-block and
TIN checks, VAT math checks, duplicate detection on capture, EWT/CWT and 2307s, BIR forms, or loose-leaf books.
