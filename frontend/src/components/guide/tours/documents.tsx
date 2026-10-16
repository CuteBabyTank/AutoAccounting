"use client";

import { useRef } from "react";
import {
  BookOpen,
  Buildings,
  CaretDown,
  FileImage,
  FilePdf,
  FileXls,
  Tag,
  UploadSimple,
  UsersThree,
  Warning,
} from "@phosphor-icons/react";
import { Card, Line, Pill, Row, Wire, d } from "@/components/guide/art";
import type { Slide } from "@/components/guide/GuideTour";

/* ───────────── Illustrations ───────────── */

function DropArt() {
  const files = [
    { icon: FilePdf, name: "santos-hardware-si.pdf", meta: "1 page" },
    { icon: FilePdf, name: "bir-2307-july-sept.pdf", meta: "4 pages" },
    { icon: FileImage, name: "meralco-sept.jpg", meta: "photo" },
  ];
  return (
    <div className="gd-art">
      <div className="gd-in mb-3 flex justify-end" style={d(0)}>
        <span className="gd-pill border border-[var(--lp-accent)] bg-[var(--lp-accent-soft)] !py-1 !text-[11px] text-[var(--lp-text)]">
          <span className="font-normal text-[var(--lp-muted)]">Drop files for:</span> Auto-detect
        </span>
      </div>
      <div className="gd-card gd-in border-2 border-dashed border-[var(--lp-accent)] !shadow-none px-6 py-7 text-center" style={d(1)}>
        <UploadSimple size={26} className="mx-auto text-[var(--lp-accent)]" />
        <p className="mt-2 text-[13px] font-semibold">Drop receipts, invoices or scans here</p>
        <p className="mt-0.5 text-[11px] text-[var(--lp-muted)]">We&apos;ll detect the company from each document&apos;s TIN and name.</p>
        <div className="mt-5 space-y-2 text-left">
          {files.map((f, i) => (
            <div key={f.name} className="gd-in flex items-center gap-2.5 rounded-lg border border-[var(--lp-border)] bg-[var(--lp-bg-card)] px-3 py-2" style={d(2 + i)}>
              <f.icon size={18} className="shrink-0 text-[var(--lp-accent)]" />
              <span className="min-w-0 flex-1 truncate font-[family-name:var(--font-mono)] text-[11px]">{f.name}</span>
              <span className="text-[10.5px] text-[var(--lp-muted)]">{f.meta}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function DetectArt() {
  const box = useRef<HTMLDivElement>(null);
  const tin = useRef<HTMLSpanElement>(null);
  const match = useRef<HTMLDivElement>(null);
  return (
    <div ref={box} className="gd-art grid grid-cols-[170px_1fr] items-center gap-10">
      <figure className="gd-receipt gd-in" style={d(0)}>
        <div className="gd-rule pb-2 text-center">
          <b className="block text-[12px] uppercase tracking-wide">Santos Hardware</b>
          <span className="block">TIN 214-385-901-000</span>
        </div>
        <div className="gd-rule py-2">
          <span className="block">SOLD TO:</span>
          <span ref={tin} className="gd-lit block px-0.5">
            <b>DELA CRUZ BUILDERS</b>
            <br />
            TIN 008-112-334-000
          </span>
        </div>
        <div className="pt-2">
          <Line l="SI No." r="0004127" />
          <Line l="Total" r="7,500.00" bold />
        </div>
      </figure>
      <Card title="Confirm the company" className="gd-in" style={d(1)}>
        <div ref={match} className="gd-row gd-row--on">
          <span className="whitespace-nowrap font-semibold !text-[var(--lp-text)]">3 files</span>
          <span className="flex flex-col items-end gap-1 whitespace-nowrap">
            <span className="flex items-center gap-1"><Buildings size={13} /> Dela Cruz Builders</span>
            <Pill tone="green">Matched by TIN</Pill>
          </span>
        </div>
        <div className="gd-row">
          <span className="whitespace-nowrap font-semibold !text-[var(--lp-text)]">1 file</span>
          <span className="flex flex-col items-end gap-1 whitespace-nowrap">
            <span>Bayani Bakeshop</span>
            <Pill tone="yellow">Not in your list</Pill>
          </span>
        </div>
        <div className="flex justify-end gap-2 px-3.5 py-2.5">
          <span className="gd-btn gd-btn--ghost">Decide later</span>
          <span className="gd-btn">Confirm</span>
        </div>
      </Card>
      <Wire box={box} from={tin} to={match} />
    </div>
  );
}

function ExtractArt() {
  const box = useRef<HTMLDivElement>(null);
  const total = useRef<HTMLElement>(null);
  const amount = useRef<HTMLDivElement>(null);
  return (
    <div ref={box} className="gd-art grid grid-cols-[208px_1fr] items-center gap-8">
      <figure className="gd-receipt gd-in" style={d(0)}>
        <div className="gd-rule pb-2 text-center">
          <b className="block text-[12px] uppercase tracking-wide">Santos Hardware</b>
          <span className="block">&amp; Construction Supply</span>
          <span className="block">VAT Reg. TIN 214-385-901-000</span>
        </div>
        <div className="gd-rule flex justify-between py-1.5">
          <span>09/02/2026</span>
          <span>SI No. 0004127</span>
        </div>
        <div className="gd-rule py-1.5">
          <Line l="Cement 40kg ×10" r="2,450.00" />
          <Line l="Plywood 1/4 ×6" r="2,670.00" />
          <Line l="Tie wire #16" r="1,180.00" />
          <Line l="Latex paint 4L ×2" r="1,200.00" />
        </div>
        <div className="pt-1.5">
          <Line l="VATable sales" r="6,696.43" />
          <Line l="VAT 12%" r="803.57" />
          <div className="mt-1 flex justify-between">
            <b className="text-[12px]">Total</b>
            <b ref={total} className="gd-lit px-1 text-[12px]">7,500.00</b>
          </div>
        </div>
      </figure>
      <Card title="Purchase journal" code="PJ-0902-14" className="gd-in" style={d(1)}>
        <Row k="Supplier" v="Santos Hardware" />
        <Row k="TIN" v="214-385-901-000" />
        <Row k="Date" v="Sep 2, 2026" />
        <Row k="Amount" v="₱7,500.00" on rowRef={amount} />
        <Row k="Input VAT" v="₱803.57" />
        <Row k="Account" v="Repairs & maintenance" />
      </Card>
      <Wire box={box} from={total} to={amount} />
    </div>
  );
}

function TreeArt() {
  const leaf = "flex items-center gap-2 rounded-md px-2 py-1.5 text-[12px]";
  return (
    <div className="gd-art flex justify-center">
      <Card className="gd-in w-[300px] p-3" style={d(0)}>
        <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--lp-muted)]">Companies</p>
        <div className={`${leaf} font-semibold`}>
          <CaretDown size={11} /> <Buildings size={14} className="text-[var(--lp-muted)]" /> Dela Cruz Builders
        </div>
        <div className="ml-4 border-l border-[var(--lp-border)] pl-2">
          <p className="px-2 pt-1 text-[11px] font-semibold text-[var(--lp-muted)]">2026</p>
          <div className={`${leaf} gd-in`} style={d(1)}>Books</div>
          <div className={`${leaf} gd-in`} style={d(1)}>Annual return</div>
          <div className={`${leaf} gd-in`} style={d(2)}>
            Q1 (Jan–Mar) <span className="ml-auto text-[11px] text-[var(--lp-muted)]">42</span> <Pill tone="green">Filed</Pill>
          </div>
          <div className={`${leaf} gd-in`} style={d(3)}>
            Q2 (Apr–Jun) <span className="ml-auto text-[11px] text-[var(--lp-muted)]">38</span> <Pill tone="yellow">Stale</Pill>
          </div>
          <div className={`${leaf} gd-in bg-[var(--lp-accent-soft)] font-semibold`} style={d(4)}>
            Q3 (Jul–Sep) <span className="ml-auto text-[11px] font-normal text-[var(--lp-muted)]">27</span> <Pill tone="yellow">3</Pill> <Pill tone="blue">v1</Pill>
          </div>
          <div className={`${leaf} gd-in`} style={d(5)}>ATC databank</div>
          <div className={`${leaf} gd-in`} style={d(5)}>
            Undated <span className="ml-auto text-[11px] text-[var(--lp-muted)]">1</span> <Pill tone="yellow">1</Pill>
          </div>
        </div>
      </Card>
    </div>
  );
}

function ReviewArt() {
  return (
    <div className="gd-art grid grid-cols-[150px_1fr] items-start gap-5">
      <figure className="gd-receipt gd-in mt-4" style={d(0)}>
        <div className="gd-rule pb-2 text-center">
          <b className="block text-[11px] uppercase">Kusina ni Lola</b>
          <span className="block text-[9.5px]">Non-VAT Reg.</span>
        </div>
        <div className="py-2 text-[9.5px]">
          <Line l="Lunch ×4" r="1,560.00" />
          <Line l="Total" r="1,560.00" bold />
          <span className="mt-1 block">OFFICIAL RECEIPT</span>
        </div>
      </figure>
      <Card title="OR 88213 · Kusina ni Lola" className="gd-in" style={d(1)}>
        <div className="flex gap-2 border-b border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] px-3.5 py-2.5 text-[11px] leading-snug text-[var(--alert-warning-text)]">
          <Warning size={15} className="mt-px shrink-0" />
          Seller isn&apos;t shown as VAT-registered, so no input VAT.
        </div>
        <Row k="Date" v="Aug 14, 2026" />
        <Row k="Total" v="₱1,560.00" />
        <Row k="Input VAT" v="₱0.00" warn />
        <Row k="Account" v={<span className="inline-flex items-center gap-1">Representation <CaretDown size={11} /></span>} />
        <div className="flex justify-end px-3.5 py-2.5">
          <span className="gd-btn gd-in" style={d(3)}>Mark reviewed</span>
        </div>
      </Card>
    </div>
  );
}

export function InputsArt() {
  const field = (label: string, value: string, note: string, i: number, on = false) => (
    <div className={`gd-in rounded-lg px-3 py-2 ${on ? "bg-[var(--lp-accent-soft)]" : ""}`} style={d(i)}>
      <span className="mb-1 block text-[11px] font-medium text-[var(--lp-muted)]">{label}</span>
      <span className={`flex items-center justify-between rounded-md border bg-[var(--lp-bg-card)] px-2.5 py-1.5 text-[12px] tabular-nums ${on ? "border-[var(--lp-accent)]" : "border-[var(--lp-border)]"}`}>
        {value}
        <span className="text-[10px] text-[var(--lp-faint)]">{note}</span>
      </span>
    </div>
  );
  return (
    <div className="gd-art">
      <Card className="gd-in p-2" style={d(0)}>
        <p className="flex items-center gap-1.5 px-3 pb-2 pt-2 text-[12.5px] font-semibold">
          <CaretDown size={12} /> Quarter inputs <span className="ml-auto font-normal text-[11px] text-[var(--lp-muted)]">Q3 · Jul–Sep 2026</span>
        </p>
        <div className="grid grid-cols-2">
          {field("Ending inventory", "184,500.00", "optional", 1)}
          {field("VAT withheld (2307, WV…)", "3,200.00", "2550-Q 16", 2, true)}
          {field("Non-operating income", "1,050.00", "interest", 3)}
          {field("Prior year's excess credits", "0.00", "", 4)}
        </div>
        <p className="mx-3 mb-2 mt-1 border-t border-[var(--lp-border)] pt-2 text-[11px] text-[var(--lp-muted)]">
          Payroll · July: minimum wage, 13th month, contributions…
        </p>
      </Card>
    </div>
  );
}

export function GenerateArt() {
  const box = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLSpanElement>(null);
  const out = useRef<HTMLDivElement>(null);
  const files = [
    { icon: FilePdf, name: "2550-Q", what: "Quarterly VAT return" },
    { icon: FilePdf, name: "1702-Q", what: "Quarterly income tax" },
    { icon: FilePdf, name: "1601-EQ", what: "Expanded withholding" },
    { icon: FileXls, name: "Workbook", what: "Every figure, traced" },
  ];
  return (
    <div ref={box} className="gd-art grid grid-cols-[130px_1fr] items-center gap-12">
      <div className="gd-in flex flex-col items-start gap-2.5" style={d(0)}>
        <Pill tone="blue">Generated v2</Pill>
        <span ref={btn} className="gd-btn !px-3 !py-2 !text-[12px]">
          <FileXls size={14} /> Generate v3
        </span>
        <span className="text-[10.5px] leading-snug text-[var(--lp-muted)]">2550-Q due Oct 25</span>
      </div>
      <Card title="Q3 2026 · v3" code="4 changes since v2" className="gd-in" style={d(1)}>
        <div ref={out}>
          {files.map((f, i) => (
            <div key={f.name} className="gd-row gd-in" style={d(2 + i)}>
              <span className="flex items-center gap-2 !text-[var(--lp-text)]">
                <f.icon size={16} className="text-[var(--lp-accent)]" />
                <b className="font-semibold">{f.name}</b>
              </span>
              <span className="!font-normal text-[var(--lp-muted)]">{f.what}</span>
            </div>
          ))}
        </div>
      </Card>
      <Wire box={box} from={btn} to={out} delay={3} />
    </div>
  );
}

export function FileArt() {
  const steps: { tone: "gray" | "blue" | "green" | "yellow"; text: string; note: string }[] = [
    { tone: "gray", text: "Collecting", note: "Documents coming in" },
    { tone: "blue", text: "Generated v1", note: "Ready to download" },
    { tone: "green", text: "Filed", note: "You marked it submitted" },
    { tone: "yellow", text: "Filed — changed since v1", note: "A late receipt arrived" },
    { tone: "blue", text: "v2 · Amended", note: "Only the forms that changed" },
  ];
  return (
    <div className="gd-art flex justify-center">
      <ol className="relative w-[380px] space-y-3 pl-7">
        <span className="absolute bottom-3 left-[9px] top-3 border-l-[1.5px] border-dashed border-[var(--lp-accent)]" />
        {steps.map((s, i) => (
          <li key={s.text} className="gd-in relative" style={d(i)}>
            <span className="absolute -left-[23px] top-3 h-2.5 w-2.5 rounded-full bg-[var(--lp-accent)] ring-4 ring-[var(--lp-bg-gray)]" />
            <div className="gd-card flex items-center justify-between gap-3 px-3.5 py-2.5">
              <Pill tone={s.tone}>{s.text}</Pill>
              <span className="whitespace-nowrap text-[11px] text-[var(--lp-muted)]">{s.note}</span>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function MoreArt() {
  const tiles = [
    { icon: FileXls, title: "Annual return", note: "1702-RT · 1701 · 1701-A", body: <Pill tone="blue">After Q4</Pill> },
    {
      icon: BookOpen,
      title: "Books",
      note: "Journals, ledger, TB",
      body: (
        <span className="flex gap-0.5">
          {Array.from({ length: 12 }, (_, i) => (
            <span key={i} className={`h-3 w-2 rounded-[2px] ${i < 8 ? "bg-[var(--lp-text)]" : "border border-[var(--lp-accent)]"}`} />
          ))}
        </span>
      ),
    },
    { icon: UsersThree, title: "Employees", note: "1604-C · 2316s", body: <Pill tone="yellow">Due Jan 31</Pill> },
    { icon: Tag, title: "ATC databank", note: "Withholding codes", body: <span className="font-[family-name:var(--font-mono)] text-[10.5px] text-[var(--lp-muted)]">WC158 · WC160</span> },
  ];
  return (
    <div className="gd-art grid grid-cols-2 gap-3">
      {tiles.map((t, i) => (
        <div key={t.title} className="gd-card gd-in p-4" style={d(i)}>
          <t.icon size={20} className="text-[var(--lp-accent)]" />
          <p className="mt-2 text-[13px] font-semibold">{t.title}</p>
          <p className="mb-3 text-[11px] text-[var(--lp-muted)]">{t.note}</p>
          {t.body}
        </div>
      ))}
    </div>
  );
}

/* ───────────── Slides ───────────── */

export const INPUTS_SLIDE: Slide = {
  id: "inputs",
  title: "Add what the documents can't show",
  body: "Open a quarter and expand Quarter inputs. These are the figures no receipt carries.",
  points: [
    "Inventory, tax your client's customers withheld (2307s received), advance payments and other income.",
    "Most fields can stay blank. Carry-overs flow in from earlier quarters prepared on AutoAccounting.",
    "Clients with employees get monthly payroll totals here for the 1601-C.",
    "Each field names the line on the BIR form it feeds, so you know where it lands.",
  ],
  Art: InputsArt,
};

export const GENERATE_SLIDE: Slide = {
  id: "generate",
  title: "Generate the returns",
  body: "Click Generate and you get filled BIR forms plus an Excel workbook. Which forms depends on the client.",
  points: [
    "VAT clients get the 2550-Q. Non-VAT clients get the 2551-Q, except individuals on the 8% rate.",
    "Income tax: 1701-Q for individuals, 1702-Q for corporations and partnerships, in Q1–Q3. Q4 is covered by the annual return.",
    "Employers add the monthly 1601-C. Withholding agents add the 0619-E and 1601-EQ, with their outgoing 2307s as a zip.",
    "The workbook highlights what changed since the last version. Use Clean copy or Clean PDF for an unmarked file.",
  ],
  Art: GenerateArt,
};

export const FILE_SLIDE: Slide = {
  id: "file",
  title: "File it, then keep it current",
  body: "The status next to each quarter tells you where it stands.",
  points: [
    "After you file with the BIR, click Mark as filed so the whole team knows it's done.",
    "Stale means a document or input changed after the last version. Generate again to catch up.",
    "Once a quarter is filed, a new version is an amended return, but only for the forms whose figures changed.",
    "Every version is kept, so you can always download exactly what was filed.",
  ],
  Art: FileArt,
};

export const DOCUMENTS_TOUR: Slide[] = [
  {
    id: "drop",
    title: "Drop in your client's documents",
    body: "Drag files onto the Documents page or click Upload files. A whole month's pile can go in at once.",
    points: [
      "PDF, PNG and JPG. A PDF holding many receipts is split into separate documents.",
      "Sales invoices, official receipts, supplier bills, BIR 2307s and payslips all go in the same place.",
      "Keep Drop files for on Auto-detect, or pick a client when the whole batch is theirs.",
      "A file you've already dropped is caught and skipped, and never charged twice.",
    ],
    Art: DropArt,
  },
  {
    id: "detect",
    title: "We work out which client it's for",
    body: "Each document is matched to a company in your databank, and you confirm before anything is filed.",
    points: [
      "The TIN is matched first, then the registered name and any trade names you've saved as aliases.",
      "Change a wrong match from the dropdown, or skip files that don't belong.",
      "A client you don't have yet? Add them from the prompt with the name and TIN already filled in.",
      "Decide later keeps the batch waiting. A banner on Documents brings it back.",
    ],
    Art: DetectArt,
  },
  {
    id: "extract",
    title: "Every figure, read off the page",
    body: "AutoAccounting reads each document the way you would and turns it into a journal entry you can trace back.",
    points: [
      "Supplier or customer, TIN, date, invoice number, VATable sales, VAT and total.",
      "Each document is sorted as sales, purchases, expenses, payroll, 2307 or support, and given an account.",
      "The VAT math is checked: 12% of VATable sales, and every line has to add up to the total.",
      "Fix a supplier's account once and later documents from them follow it.",
    ],
    Art: ExtractArt,
  },
  {
    id: "tree",
    title: "Filed under the right quarter",
    body: "The list on the left is Company → Year → Quarter. Open a quarter to see its documents and returns.",
    points: [
      "Each document goes to the quarter its date falls in, following the client's fiscal year.",
      "No readable date? It waits in Undated until you set one.",
      "Yellow number: documents to review. v1, v2: returns generated. Stale: changed since then. Filed: submitted.",
      "Pin busy clients on the Companies page to keep them at the top.",
    ],
    Art: TreeArt,
  },
  {
    id: "review",
    title: "Check the ones we flagged",
    body: "When something looks off, the document is flagged with the reason. You decide.",
    points: [
      "Common flags: an unreadable date, VAT that isn't 12%, a possible duplicate, or a receipt that can't support input VAT.",
      "Open the document to see the page beside the fields, and correct anything.",
      "Click Mark reviewed when it's right. Returns generated with open flags are marked DRAFT.",
    ],
    Art: ReviewArt,
  },
  INPUTS_SLIDE,
  GENERATE_SLIDE,
  FILE_SLIDE,
  {
    id: "more",
    title: "Beyond the quarter",
    body: "Each company's folder also holds the year-end work.",
    points: [
      "Annual return: after Q4, built from all four quarters less the tax already paid.",
      "Books: set a Books start on the company to keep BIR loose-leaf journals, ledger and trial balance.",
      "Employees: import the payroll register for the 1604-C alphalist and each 2316, due January 31.",
      "ATC databank: set each supplier's withholding tax code once and every document from them uses it.",
    ],
    Art: MoreArt,
  },
];

