"use client";

import { useRef } from "react";
import { Check, Clock, Crown, EnvelopeSimple, Minus, UserPlus } from "@phosphor-icons/react";
import { Card, Pill, Row, Wire, d } from "@/components/guide/art";
import type { Slide } from "@/components/guide/GuideTour";

const EMAIL = "ana.reyes@gmail.com";

function Avatar({ letter }: { letter: string }) {
  return (
    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-[var(--lp-accent-soft)] text-[11px] font-semibold text-[var(--lp-accent)]">
      {letter}
    </span>
  );
}

/* ───────────── Team ───────────── */

function SignInArt() {
  return (
    <div className="gd-art flex justify-center">
      <div className="gd-card gd-in w-[300px] overflow-hidden text-center" style={d(0)}>
        <div className="bg-gradient-to-b from-[var(--lp-accent-soft)] to-transparent px-6 pb-5 pt-7">
          <span className="gd-in mx-auto grid h-11 w-11 place-items-center rounded-xl bg-[var(--lp-accent)] text-white" style={d(1)}>
            <Clock size={22} weight="bold" />
          </span>
          <p className="mt-3 text-[15px] font-bold">Account pending verification</p>
          <p className="mt-1 text-[11px] text-[var(--lp-muted)]">You&apos;re signed in, but not linked to a firm yet.</p>
        </div>
        <div className="gd-in mx-5 mb-6 flex items-center gap-2 rounded-lg border border-[var(--lp-border)] px-3 py-2 text-left" style={d(2)}>
          <EnvelopeSimple size={14} className="text-[var(--lp-muted)]" />
          <span className="flex-1 truncate font-[family-name:var(--font-mono)] text-[11px]">{EMAIL}</span>
          <span className="gd-btn !px-2 !py-1 !text-[10px]">Copy</span>
        </div>
      </div>
    </div>
  );
}

function AddArt() {
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLDivElement>(null);
  const row = useRef<HTMLDivElement>(null);
  return (
    <div ref={box} className="gd-art space-y-12">
      <div ref={input} className="gd-in flex items-center gap-2" style={d(0)}>
        <span className="gd-card flex-1 px-3 py-2.5 font-[family-name:var(--font-mono)] text-[12px]">{EMAIL}</span>
        <span className="gd-btn !py-2.5"><UserPlus size={14} /> Add member</span>
      </div>
      <Card className="gd-in" style={d(2)}>
        <div className="gd-row !text-[10.5px]">
          <span>Member</span>
          <span className="!font-normal text-[var(--lp-muted)]">Role · Status</span>
        </div>
        <div ref={row} className="gd-row gd-row--on">
          <span className="flex items-center gap-2 !text-[var(--lp-text)]"><Avatar letter="A" /> <b>Ana Reyes</b></span>
          <span className="flex items-center gap-1.5"><Pill tone="gray">Employee</Pill><Pill tone="green">Active</Pill></span>
        </div>
        <div className="gd-row">
          <span className="flex items-center gap-2 !text-[var(--lp-text)]"><Avatar letter="J" /> Jose Lim</span>
          <span className="flex items-center gap-1.5"><Pill tone="blue">Manager</Pill><Pill tone="green">Active</Pill></span>
        </div>
      </Card>
      <Wire box={box} from={input} to={row} delay={3} />
    </div>
  );
}

function RolesArt() {
  const rows: [string, boolean, boolean, boolean][] = [
    ["Upload, review and generate returns", true, true, true],
    ["Set up clients: companies, books, payroll", false, true, true],
    ["Add and deactivate staff", false, true, true],
    ["Make someone a manager", false, false, true],
  ];
  const mark = (on: boolean) =>
    on ? <Check size={14} weight="bold" className="mx-auto text-[var(--lp-accent)]" /> : <Minus size={14} className="mx-auto text-[var(--lp-faint)]" />;
  return (
    <div className="gd-art">
      <Card className="gd-in" style={d(0)}>
        <div className="grid grid-cols-[1fr_62px_62px_62px] border-b border-[var(--lp-border)] px-3.5 py-2.5 text-[10.5px] font-semibold text-[var(--lp-muted)]">
          <span />
          <span className="text-center">Employee</span>
          <span className="text-center">Manager</span>
          <span className="text-center">Owner</span>
        </div>
        {rows.map(([what, e, m, o], i) => (
          <div key={what} className="gd-in grid grid-cols-[1fr_62px_62px_62px] items-center border-b border-[var(--lp-border)] px-3.5 py-2.5 text-[12px] last:border-0" style={d(1 + i)}>
            <span>{what}</span>
            {mark(e)}
            {mark(m)}
            {mark(o)}
          </div>
        ))}
      </Card>
    </div>
  );
}

export const TEAM_TOUR: Slide[] = [
  {
    id: "signin",
    title: "Your colleague signs in first",
    body: "AutoAccounting uses Google sign-in only, so there are no invites or passwords to manage.",
    points: [
      "Ask them to open AutoAccounting and sign in with their Google account.",
      "They'll land on a waiting screen showing their email. They can't see any clients yet.",
      "They can copy that email and send it to you.",
    ],
    Art: SignInArt,
  },
  {
    id: "add",
    title: "Add them by email",
    body: "Type the exact Google email they signed in with and click Add member.",
    points: [
      "They join as an Employee and can see every client in the firm straight away.",
      "Deactivate pauses someone's access without removing them.",
      "Remove takes them off the firm. Their account stays, and you can add them back later.",
    ],
    Art: AddArt,
  },
  {
    id: "roles",
    title: "Who can do what",
    body: "Staff are Employees or Managers. You, the firm owner, can do everything.",
    points: [
      "Employees upload, review, generate and mark quarters filed for every client.",
      "Managers can also set up clients (companies, books and payroll) and add or deactivate staff.",
      "Only the firm owner can promote someone to manager or demote them back.",
      "The usage cards show pages read this month and, if billing is on, your prepaid balance.",
    ],
    Art: RolesArt,
  },
];

/* ───────────── Platform admin ───────────── */

function ApproveArt() {
  const box = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLSpanElement>(null);
  const firm = useRef<HTMLDivElement>(null);
  return (
    <div ref={box} className="gd-art space-y-12">
      <Card className="gd-in" style={d(0)}>
        <div className="gd-row">
          <span className="flex items-center gap-2 !text-[var(--lp-text)]"><Avatar letter="M" /> {EMAIL.replace("ana.reyes", "maria.santos")}</span>
          <span className="flex items-center gap-2">
            <Pill tone="gray">Unverified</Pill>
            <span ref={btn} className="gd-btn">Make firm</span>
          </span>
        </div>
      </Card>
      <Card className="gd-in" style={d(2)}>
        <div ref={firm} className="gd-row gd-row--on">
          <span className="flex items-center gap-2 !text-[var(--lp-text)]"><Crown size={16} className="text-[var(--lp-accent)]" /> <b>Santos &amp; Co. CPAs</b></span>
          <Pill tone="green">Firm owner</Pill>
        </div>
        <Row k="Team page" v="Adds their own staff" />
        <Row k="Clients" v="Visible to this firm only" />
      </Card>
      <Wire box={box} from={btn} to={firm} delay={3} dir="v" />
    </div>
  );
}

function BillingArt() {
  const box = useRef<HTMLDivElement>(null);
  const rate = useRef<HTMLDivElement>(null);
  const budget = useRef<HTMLDivElement>(null);
  return (
    <div ref={box} className="gd-art space-y-12">
      <div ref={rate} className="gd-card gd-in flex items-center gap-3 px-4 py-3" style={d(0)}>
        <span className="flex-1">
          <span className="block text-[12.5px] font-semibold">Price per page</span>
          <span className="text-[11px] text-[var(--lp-muted)]">Each extracted page debits the firm&apos;s budget</span>
        </span>
        <span className="rounded-lg border border-[var(--lp-border)] px-3 py-1.5 text-[12px] tabular-nums">₱ 2.00</span>
      </div>
      <Card title="Santos & Co. CPAs" code="October" className="gd-in" style={d(2)}>
        <Row k="Pages this month" v="1,380" />
        <div ref={budget} className="gd-row gd-row--on">
          <span>Prepaid budget</span>
          <span className="tabular-nums">₱1,240.00</span>
        </div>
        <div className="flex justify-end gap-1.5 px-3.5 py-2.5">
          <span className="gd-btn">Top up</span>
          <span className="gd-btn gd-btn--ghost">Deduct</span>
          <span className="gd-btn gd-btn--ghost">Set</span>
        </div>
      </Card>
      <Wire box={box} from={rate} to={budget} delay={3} />
    </div>
  );
}

export const ADMIN_TOUR: Slide[] = [
  {
    id: "approve",
    title: "Approve new sign-ups",
    body: "Anyone who signs in with Google appears here as Unverified and sees nothing until you act.",
    points: [
      "Click Make firm and name the firm to turn someone into a firm owner.",
      "Or use the Role menu to attach them to an existing firm as a manager or employee.",
      "Deactivate blocks an account from signing in. Reactivate undoes it.",
    ],
    Art: ApproveArt,
  },
  {
    id: "billing",
    title: "Charge per page, or not at all",
    body: "Billing is off until you set a price per page.",
    points: [
      "Empty price: uploads are free and never blocked.",
      "With a price set, every page AutoAccounting reads comes out of the firm's prepaid budget.",
      "At ₱0, the firm's uploads stop until you Top up. Deduct and Set adjust the balance directly.",
      "Pages this month shows each firm's usage, so you can bill or top up.",
    ],
    Art: BillingArt,
  },
];
