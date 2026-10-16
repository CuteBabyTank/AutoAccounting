"use client";

import { useRef } from "react";
import { Buildings, FilePdf } from "@phosphor-icons/react";
import { Card, Line, Pill, Row, Wire, d } from "@/components/guide/art";
import type { Slide } from "@/components/guide/GuideTour";

function ProfileArt() {
  const box = useRef<HTMLDivElement>(null);
  const reg = useRef<HTMLDivElement>(null);
  const forms = useRef<HTMLDivElement>(null);
  const list = [
    ["2550-Q", "Quarterly · VAT-registered"],
    ["1702-Q", "Quarterly · corporation"],
    ["0619-E · 1601-EQ", "Monthly + quarterly EWT"],
    ["1601-C", "Monthly · has employees"],
  ];
  return (
    <div ref={box} className="gd-art grid grid-cols-[1fr_170px] items-center gap-10">
      <Card title={<span className="flex items-center gap-1.5"><Buildings size={15} /> Dela Cruz Builders Inc.</span>} className="gd-in" style={d(0)}>
        <Row k="TIN" v="008-112-334-000" />
        <Row k="RDO" v="044 · Taguig" />
        <Row k="Taxpayer type" v="Corporation" />
        <div ref={reg} className="gd-row gd-row--on">
          <span className="whitespace-nowrap">Tax setup</span>
          <span className="flex flex-wrap justify-end gap-1">
            <Pill tone="green">VAT</Pill>
            <Pill tone="blue">Withholding agent</Pill>
            <Pill tone="gray">Employees</Pill>
          </span>
        </div>
      </Card>
      <div ref={forms} className="gd-in space-y-2" style={d(2)}>
        <p className="text-[11px] font-semibold text-[var(--lp-muted)]">Returns we prepare</p>
        {list.map(([f, why], i) => (
          <div key={f} className="gd-card gd-in px-3 py-2" style={d(3 + i)}>
            <span className="flex items-center gap-1.5 text-[12px] font-semibold"><FilePdf size={14} className="text-[var(--lp-accent)]" /> {f}</span>
            <span className="text-[10.5px] text-[var(--lp-muted)]">{why}</span>
          </div>
        ))}
      </div>
      <Wire box={box} from={reg} to={forms} delay={2} />
    </div>
  );
}

function MatchArt() {
  const box = useRef<HTMLDivElement>(null);
  const name = useRef<HTMLSpanElement>(null);
  const alias = useRef<HTMLDivElement>(null);
  return (
    <div ref={box} className="gd-art grid grid-cols-[170px_1fr] items-center gap-10">
      <figure className="gd-receipt gd-in" style={d(0)}>
        <div className="gd-rule pb-2 text-center">
          <b className="block text-[11.5px] uppercase">Metro Cement Corp.</b>
          <span className="block">OFFICIAL RECEIPT</span>
        </div>
        <div className="gd-rule py-2">
          <span className="block">RECEIVED FROM:</span>
          <span ref={name} className="gd-lit block px-0.5"><b>DCB CONSTRUCTION</b></span>
          <span className="block text-[#94A3B8]">TIN ___-___-___</span>
        </div>
        <div className="pt-2">
          <Line l="Amount" r="38,200.00" bold />
        </div>
      </figure>
      <Card title="Dela Cruz Builders Inc." code="008-112-334-000" className="gd-in" style={d(1)}>
        <Row k="Match by TIN" v={<Pill tone="gray">No TIN on page</Pill>} />
        <Row k="Name" v="Dela Cruz Builders Inc." />
        <Row k="Aliases" v="DCB Construction, DCB" on rowRef={alias} />
        <Row k="Result" v={<Pill tone="green">Matched by alias</Pill>} />
      </Card>
      <Wire box={box} from={name} to={alias} />
    </div>
  );
}

function FiscalArt() {
  const months = ["Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun"];
  return (
    <div className="gd-art">
      <Card className="gd-in p-4" style={d(0)}>
        <div className="mb-4 flex items-center justify-between">
          <span className="text-[12.5px] font-semibold">Fiscal year ends</span>
          <span className="rounded-md border border-[var(--lp-accent)] bg-[var(--lp-accent-soft)] px-2.5 py-1 text-[12px] font-semibold">June</span>
        </div>
        <p className="mb-2 text-[11px] font-semibold text-[var(--lp-muted)]">FY 2027 · July 2026 to June 2027</p>
        <div className="grid grid-cols-4 gap-2">
          {[0, 1, 2, 3].map((q) => (
            <div key={q} className={`gd-in rounded-lg border p-2 ${q === 0 ? "border-[var(--lp-accent)] bg-[var(--lp-accent-soft)]" : "border-[var(--lp-border)]"}`} style={d(1 + q)}>
              <p className="mb-1.5 text-[11.5px] font-semibold">Q{q + 1}</p>
              <div className="flex gap-1">
                {months.slice(q * 3, q * 3 + 3).map((m) => (
                  <span key={m} className="flex-1 rounded bg-[var(--lp-bg-card)] py-1 text-center text-[10px] text-[var(--lp-muted)] shadow-sm">{m}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11px] text-[var(--lp-muted)]">In Q4 the VAT return is filed as usual; income tax goes on the annual return.</p>
      </Card>
    </div>
  );
}

function BooksArt() {
  const months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
  return (
    <div className="gd-art space-y-3">
      <Card className="gd-in" style={d(0)}>
        <Row k="Books start" v="Jan 1, 2026" on />
        <Row k="Registered books" v="Sales · Purchases · Cash receipts · Cash disb." />
      </Card>
      <Card className="gd-in p-4" style={d(1)}>
        <p className="mb-2.5 text-[12px] font-semibold">Books · FY 2026</p>
        <div className="grid grid-cols-12 gap-1">
          {months.map((m, i) => (
            <span
              key={i}
              className={`gd-in rounded-md py-1.5 text-center text-[10px] font-semibold ${
                i < 8 ? "bg-[var(--lp-text)] text-[var(--lp-bg)]" : i === 8 ? "border-[1.5px] border-[var(--lp-accent)] text-[var(--lp-accent)]" : "border border-[var(--lp-border)] text-[var(--lp-muted)]"
              }`}
              style={d(2 + i * 0.3)}
            >
              {m}
            </span>
          ))}
        </div>
        <p className="mt-2.5 flex items-center gap-3 text-[10.5px] text-[var(--lp-muted)]">
          <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-[3px] bg-[var(--lp-text)]" /> Closed</span>
          <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-[3px] border-[1.5px] border-[var(--lp-accent)]" /> Next to close</span>
        </p>
      </Card>
      <div className="gd-in flex gap-2" style={d(5)}>
        {["Sales journal", "Purchase journal", "General journal", "General ledger"].map((b) => (
          <span key={b} className="gd-card flex-1 px-2 py-2 text-center text-[10.5px] font-semibold">{b}</span>
        ))}
      </div>
    </div>
  );
}

export const COMPANIES_TOUR: Slide[] = [
  {
    id: "profile",
    title: "One profile per client",
    body: "Each client's profile decides which BIR returns AutoAccounting prepares for them, and what goes on each form's header.",
    points: [
      "Registered name, TIN, branch code, RDO and address print on every form.",
      "Taxpayer type, VAT registration and the income tax option decide the VAT or percentage tax return and the income tax return.",
      "Tick \"Withholds tax on supplier payments\" to add the 0619-E and 1601-EQ. Tick \"Has employees\" to add the 1601-C.",
      "Only managers and the firm owner can add or edit companies.",
    ],
    Art: ProfileArt,
  },
  {
    id: "match",
    title: "How documents find their client",
    body: "When you drop a file, its TIN and names are compared with this list.",
    points: [
      "A matching TIN wins. A document showing your client's TIN files under them.",
      "Without a TIN, we compare the registered name and every alias.",
      "Save the trade names and short forms suppliers write on receipts as aliases.",
      "Pin your busiest clients so they stay at the top of every list.",
    ],
    Art: MatchArt,
  },
  {
    id: "fiscal",
    title: "The fiscal year sets the quarters",
    body: "Choose the month the client's fiscal year ends. Quarters, due dates and the annual return all follow it.",
    points: [
      "December (calendar year) is the default.",
      "With a June year-end, July–September is Q1 of the fiscal year that ends the next June.",
      "Documents are filed by their date into the matching fiscal quarter automatically.",
    ],
    Art: FiscalArt,
  },
  {
    id: "books",
    title: "Turn on the books of accounts",
    body: "Set a Books start date when editing a company to keep its BIR loose-leaf books here too.",
    points: [
      "Choose which books the client registered with the BIR.",
      "A Books folder appears under each year: opening balances, manual journal entries and month close.",
      "Journals, the general ledger and trial balance are added to each quarter's workbook.",
      "Leave Books start empty to prepare returns only.",
    ],
    Art: BooksArt,
  },
];
