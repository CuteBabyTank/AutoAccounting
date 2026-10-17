"use client";

import { Card, Pill, Row, d } from "@/components/guide/art";
import type { Slide } from "@/components/guide/GuideTour";

function BoardArt() {
  const rows: [string, string, string, "green" | "blue" | "yellow" | "red" | "gray", string][] = [
    ["26 Oct", "Dela Cruz Builders", "2550-Q Q3", "blue", "Generated"],
    ["10 Nov", "Dela Cruz Builders", "0619-E Oct", "yellow", "Needs review"],
    ["10 Nov", "Rivera Bakeshop", "1601-C Oct", "gray", "No documents"],
    ["15 Oct", "Santos Dental", "1702-Q Q3", "red", "2 days late"],
  ];
  return (
    <div className="gd-art">
      <Card title="Work · Filings" className="gd-in" style={d(0)}>
        {rows.map(([due, who, form, tone, status], i) => (
          <div key={form + who} className="gd-row gd-in" style={d(1 + i)}>
            <span className="whitespace-nowrap">{due} · {who}</span>
            <span className="flex items-center gap-1.5 whitespace-nowrap">{form} <Pill tone={tone}>{status}</Pill></span>
          </div>
        ))}
      </Card>
    </div>
  );
}

function HealthArt() {
  return (
    <div className="gd-art">
      <Card title="Dela Cruz Builders · health check" className="gd-in" style={d(0)}>
        <Row k="Documents to review" v={<Pill tone="yellow">3</Pill>} />
        <Row k="Cash in bank" v="Reconciled through 30 Sep" />
        <Row k="2307s to receive" v={<Pill tone="yellow">1 · ₱2,415.70</Pill>} />
        <Row k="Cash on hand" v={<Pill tone="red">₱12,500 below zero</Pill>} warn />
        <Row k="Months not closed" v="Oct 2026" />
      </Card>
    </div>
  );
}

function TasksArt() {
  return (
    <div className="gd-art">
      <Card title="Tasks" className="gd-in" style={d(0)}>
        <Row k="Ask client for Oct–Nov bank statement" v={<Pill tone="red">High</Pill>} on />
        <Row k="Chase Kalayaan for the Q4 2307" v="Ana" />
        <Row k="Sign the 1702-Q before filing" v={<Pill tone="green">Done</Pill>} />
      </Card>
    </div>
  );
}

export const WORK_TOUR: Slide[] = [
  {
    id: "filings",
    title: "Every client's returns by due date",
    body: "The Filings tab lists each return a client owes, worked out from its company profile, with the BIR due date.",
    points: [
      "Status follows the work: no documents, documents in, some need review, a version generated, filed.",
      "Assign each return to someone on your team; they get a reminder in the bell before it's due.",
      "Overdue returns are red. Mark filed here only for a return filed outside AutoAccounting.",
    ],
    Art: BoardArt,
  },
  {
    id: "health",
    title: "A health check per client",
    body: "Clients shows what's waiting for each company. Open the full check before filing or closing a month.",
    points: [
      "Documents to review, bank lines to match, months not reconciled and the date the bank is reconciled through.",
      "2307s still to receive, invoices and bills over 90 days, and balances on the wrong side, like negative cash.",
      "The same check is on each company's Overview in Documents.",
    ],
    Art: HealthArt,
  },
  {
    id: "tasks",
    title: "Tasks and notifications",
    body: "Add a task for anything you need to chase, and link it to a client and period.",
    points: [
      "The bell shows deadlines, documents to review, unreconciled statements, missing 2307s and your tasks.",
      "The firm owner can require a manager to mark returns filed (Team page).",
    ],
    Art: TasksArt,
  },
];
