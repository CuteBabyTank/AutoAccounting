"use client";

import { useCallback, useEffect, useState } from "react";

/** Dismissed guides are remembered per browser; "Show guides again" in the sidebar clears them. */
const PREFIX = "aa:guide:";
const RESET_EVENT = "aa:guides-reset";

export interface GuideStep {
  title: string;
  body: string;
}

function isDismissed(id: string): boolean {
  try {
    return localStorage.getItem(PREFIX + id) === "1";
  } catch {
    return false;
  }
}

/**
 * Whether a guide is showing. It opens on its own until the user dismisses it once,
 * unless autoOpen is false (then only its button opens it).
 */
export function useGuide(id: string, { autoOpen = true }: { autoOpen?: boolean } = {}) {
  // Closed for the first render so server and client markup match; the effect opens it.
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(autoOpen && !isDismissed(id));
    const reset = () => setOpen(autoOpen);
    window.addEventListener(RESET_EVENT, reset);
    return () => window.removeEventListener(RESET_EVENT, reset);
  }, [id, autoOpen]);

  const dismiss = useCallback(() => {
    setOpen(false);
    try {
      localStorage.setItem(PREFIX + id, "1");
    } catch {
      // not persisted; it comes back next visit
    }
  }, [id]);

  const toggle = useCallback(() => {
    if (open) dismiss();
    else setOpen(true);
  }, [open, dismiss]);

  return { open, dismiss, toggle };
}

/** Bring back every dismissed guide on every page. */
export function resetGuides() {
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(PREFIX)) localStorage.removeItem(key);
    }
  } catch {
    // storage unavailable; open guides still reopen below
  }
  window.dispatchEvent(new Event(RESET_EVENT));
}

export const GUIDES = {
  documents: [
    {
      title: "Drop the files",
      body: "Drag a client's receipts, invoices, 2307s or payroll into the box below (PDF, PNG or JPG). One PDF can hold many documents; we split it up.",
    },
    {
      title: "Confirm the company",
      body: "We read each document's TIN and name and suggest a company. Check the match, or add the company if it's new, before anything is filed.",
    },
    {
      title: "Check what was read",
      body: "Documents land in Company → Year → Quarter on the left. A yellow number means some need a second look. Open them, fix any field, then mark them reviewed.",
    },
    {
      title: "Generate the returns",
      body: "Open a quarter and click Generate. You get the filled BIR forms as PDFs plus an Excel workbook. Each run is a new version; mark it filed once you've filed with the BIR.",
    },
  ],
  companies: [
    {
      title: "One row per client",
      body: "Every client you file for lives here. The TIN, taxpayer type and VAT status decide which BIR returns we prepare for them.",
    },
    {
      title: "Aliases help matching",
      body: "Add trade names a client's receipts might use. Dropped documents are matched by TIN first, then by registered name and aliases.",
    },
    {
      title: "Turn on books",
      body: "Set a Books start date when editing a company to get journals, the general ledger and trial balance in each quarter's workbook.",
    },
  ],
  team: [
    {
      title: "Have them sign in first",
      body: "Your colleague signs in once with Google. They'll see a waiting screen until you add them.",
    },
    {
      title: "Add them by email",
      body: "Type the same Google email below. They get access to every client in your firm right away.",
    },
    {
      title: "Pick their role",
      body: "Employees upload and review documents. Managers can also add and edit companies and manage employees. Only the firm owner can promote managers.",
    },
  ],
  admin: [
    {
      title: "New sign-ups wait here",
      body: "Anyone who signs in with Google shows up as Unverified. They can't see any client data until you give them a role.",
    },
    {
      title: "Create a firm",
      body: "Click Make firm on an unverified account to make them a firm owner. From then on they add their own staff on the Team page.",
    },
    {
      title: "Billing is optional",
      body: "Leave the price per page empty and uploads are free. Set a price and each extracted page comes out of the firm's budget; top it up from the account row.",
    },
  ],
  quarter: [
    {
      title: "Fill in what documents can't show",
      body: "Open Quarter inputs for figures like inventory, carry-overs or tax already paid. Everything else comes from the documents.",
    },
    {
      title: "Generate a version",
      body: "Generate builds the BIR returns for this quarter. Download the PDFs to file, or the workbook to check the numbers.",
    },
    {
      title: "Keep it current",
      body: "Stale means documents or inputs changed since the last version, so generate again. Mark as filed once it's submitted; later changes become amended returns.",
    },
  ],
} satisfies Record<string, GuideStep[]>;
