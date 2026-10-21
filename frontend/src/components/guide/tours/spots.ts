import type { Spot } from "@/components/guide/SpotlightTour";

/* On-screen tour stops. Each ``target`` is a ``data-tour`` attribute on the page; stops whose element isn't on screen
   for this person (role, phone layout, no data yet) are skipped. */

const APP_SPOTS: Spot[] = [
  {
    target: "nav-work",
    title: "Work: what's due",
    body: "Every client's BIR returns by due date, who's on each one, and what's late. Start your day here.",
  },
  {
    target: "nav-companies",
    title: "Companies: your client list",
    body: "Each client's TIN, address and tax registration. We use it to match dropped files and decide which returns they owe.",
  },
  {
    target: "nav-team",
    title: "Team",
    body: "Add colleagues by their Google email and choose who can manage clients or mark returns filed.",
  },
  {
    target: "search",
    title: "Search anything",
    body: "Find a client, document, supplier or amount from any page. Press / or Ctrl K.",
  },
  {
    target: "bell",
    title: "Notifications",
    body: "Deadlines, documents to review, missing 2307s and your tasks. Click one to jump straight to it.",
  },
];

const REPLAY: Spot = {
  target: "show-guides",
  title: "Need this again?",
  body: "Show guides brings back every page's tour. Each page also has a How this works button at the top.",
};

export const DOCUMENTS_SPOTS: Spot[] = [
  {
    title: "Welcome to AutoAccounting",
    body: "A one-minute tour of the screen. We'll point at each part and say what it does. Use the arrow keys or the buttons; Esc closes it.",
  },
  {
    target: "upload",
    title: "Drop your client's files here",
    body: "Receipts, sales invoices, 2307s, bank statements or payroll, as PDFs or phone photos. You can also drag them anywhere on this page.",
  },
  {
    target: "company-picker",
    title: "Whose files are these?",
    body: "Leave it on Auto-detect and we read each document's TIN and name to find the company. Pick a client when the whole drop is theirs.",
  },
  {
    target: "folders",
    title: "Everything gets filed here",
    body: "Company, then year, then quarter. A yellow number means some documents need a look from you. Click a quarter to see its returns.",
  },
  {
    target: "workspace",
    title: "Your working area",
    body: "Whatever you open on the left shows here: documents to check, the quarter's BIR returns, books, bank and reports.",
  },
  {
    target: "books-off",
    title: "Returns only, or full books?",
    body: "This client gets BIR returns only. Turn on books to also keep their journals, ledger and financial statements, and to get Reports.",
  },
  {
    target: "getting-started",
    title: "Your first steps",
    body: "This checklist ticks itself off as you go, and hides once you're set up.",
  },
  ...APP_SPOTS,
  REPLAY,
];

export const WORK_SPOTS: Spot[] = [
  {
    target: "work-history",
    title: "See who completed what",
    body: "History tracks completed tasks and filed returns, with per-person totals, on-time and late completions, and open work. Pick a period, person or client to review it.",
  },
  {
    target: "work-tabs",
    title: "Four views of the firm's work",
    body: "Filings lists every return owed by due date. Clients shows each company's health. Tasks holds anything you need to chase. History shows who completed it and when.",
  },
  {
    target: "work-filters",
    title: "Narrow it down",
    body: "Filter by client, due window, status or who it's assigned to. Assigned people get a reminder before the due date.",
  },
  {
    target: "work-board",
    title: "One row per return",
    body: "Status follows the documents: none yet, in, needs review, generated, filed. Red means it's late.",
  },
  {
    target: "privacy",
    title: "Sharing your screen?",
    body: "Hide amounts blurs every peso figure until you turn it back on.",
  },
  REPLAY,
];

export const COMPANIES_SPOTS: Spot[] = [
  {
    target: "add-company",
    title: "Add a client",
    body: "Enter their TIN and tax registration (VAT or non-VAT, employer or not). That decides which returns we prepare.",
  },
  {
    target: "company-search",
    title: "Find a client fast",
    body: "Search by registered name, trade name or TIN.",
  },
  {
    target: "company-list",
    title: "Your client databank",
    body: "Dropped documents are matched against this list. Open a client to edit it, pin it, or set aliases for names that show up on receipts.",
  },
  REPLAY,
];

export const TEAM_SPOTS: Spot[] = [
  {
    target: "add-member",
    title: "Invite a colleague",
    body: "They sign in with Google once, then you add them here by that email.",
  },
  {
    target: "members",
    title: "Roles",
    body: "Employees upload and review. Managers can also set up clients and add staff. Only the firm owner promotes managers.",
  },
  {
    target: "work-settings",
    title: "Who can mark returns filed",
    body: "Turn on manager approval and only managers and the owner can mark a return filed or close a month.",
  },
  {
    target: "usage",
    title: "Pages and budget",
    body: "Every page our AI reads counts once for the firm. Duplicates you drop again are free.",
  },
  REPLAY,
];
