"use client";

import { useState, useMemo } from "react";
import {
  Clock,
  EnvelopeSimple,
  Copy,
  CheckCircle,
  PaperPlaneTilt,
  Buildings,
  SignOut,
  ChatCircleDots,
} from "@phosphor-icons/react";
import { useAuth } from "@/lib/auth";
import { HOMEPAGE } from "@/lib/roles";
import AppFlow from "@/components/layout/AppFlow";
import LogoMark from "@/components/layout/LogoMark";

const CONTACT_EMAIL = "matthewfrasersim@gmail.com";

export default function PendingPage() {
  const { user, logout } = useAuth();
  const [copied, setCopied] = useState(false);

  const copyEmail = async () => {
    if (!user?.email) return;
    try {
      await navigator.clipboard.writeText(user.email);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch { /* ignore */ }
  };

  const gmailHref = useMemo(() => {
    const subject = "AutoAccounting — Set up our firm";
    const body = [
      "Drop your details and we’ll reach out to get you set up.",
      "",
      "Full Name*:",
      "Viber Number*:",
      "Company / Organization:",
      "Anything else we should know?:",
    ].join("\n");
    const params = new URLSearchParams({
      view: "cm",
      fs: "1",
      to: CONTACT_EMAIL,
      su: subject,
      body,
    });
    return `https://mail.google.com/mail/?${params.toString().replace(/\+/g, "%20")}`;
  }, []);

  return (
    <div className="lp min-h-screen w-full relative">
      <AppFlow />

      {/* Top bar */}
      <div className="relative flex items-center justify-between px-6 py-5 max-w-6xl mx-auto">
        <a href={HOMEPAGE} className="flex items-center gap-2 text-[var(--text-primary)] font-semibold tracking-tight hover:opacity-80 transition-opacity">
          <LogoMark width={34} height={24} />
          AutoAccounting
        </a>
        <button
          onClick={logout}
          className="flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
        >
          <SignOut size={16} /> Sign out
        </button>
      </div>

      {/* Hero card */}
      <div className="relative max-w-3xl mx-auto px-6 pt-6 pb-16">
        <div className="bg-[var(--bg-secondary)] rounded-3xl border border-[var(--border)] shadow-xl shadow-black/5 overflow-hidden">
          {/* Status header */}
          <div className="px-8 pt-10 pb-8 text-center border-b border-[var(--border)] bg-gradient-to-b from-[var(--accent-subtle)] to-transparent">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-[var(--accent)] text-white mb-4 shadow-lg shadow-[var(--accent)]/30">
              <Clock weight="bold" size={32} />
            </div>
            <h1 className="text-3xl font-bold text-[var(--text-primary)] tracking-tight">
              Account pending verification
            </h1>
            <p className="mt-3 text-[var(--text-secondary)] text-base max-w-md mx-auto">
              You&apos;re signed in, but your account isn&apos;t linked to an accounting firm yet. Pick the path that fits.
            </p>
          </div>

          {/* Path 1 — already on a team */}
          <div className="px-8 py-7 border-b border-[var(--border)]">
            <div className="flex items-start gap-4">
              <div className="shrink-0 w-10 h-10 rounded-xl bg-[var(--badge-blue-bg)] text-[var(--badge-blue-text)] flex items-center justify-center">
                <Buildings weight="bold" size={20} />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                  Already part of a firm?
                </h2>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  Ask your firm&apos;s owner or a manager to add you from their Team page. They&apos;ll need the email below.
                </p>
                <div className="mt-4 flex items-center gap-2 bg-[var(--bg-primary)] rounded-xl border border-[var(--border)] px-4 py-3">
                  <EnvelopeSimple size={18} className="text-[var(--text-secondary)] shrink-0" />
                  <span className="text-[var(--text-primary)] font-mono text-sm truncate flex-1">
                    {user?.email ?? "—"}
                  </span>
                  <button
                    onClick={copyEmail}
                    className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-colors"
                  >
                    {copied ? (
                      <>
                        <CheckCircle weight="fill" size={14} /> Copied
                      </>
                    ) : (
                      <>
                        <Copy size={14} /> Copy
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Path 2 — not on a team */}
          <div className="px-8 py-7">
            <div className="flex items-start gap-4">
              <div className="shrink-0 w-10 h-10 rounded-xl bg-[var(--accent-subtle)] text-[var(--accent)] flex items-center justify-center">
                <ChatCircleDots weight="bold" size={20} />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                  Setting up a new firm?
                </h2>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  Drop your details and we&apos;ll set your firm up.
                </p>
                <a
                  href={gmailHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-4 inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--accent)] text-white text-sm font-medium hover:bg-[var(--accent-hover)] transition-colors shadow-md shadow-[var(--accent)]/20"
                >
                  <PaperPlaneTilt size={16} weight="fill" /> Contact us
                </a>
                <p className="mt-3 text-[11px] text-[var(--text-tertiary)]">
                  Opens a Gmail compose window addressed to our support team.
                </p>
              </div>
            </div>
          </div>
        </div>

        <p className="mt-6 text-center text-xs text-[var(--text-tertiary)]">
          Already added by your admin? Sign out and back in to refresh your access.
        </p>

        <div className="mt-4 flex items-center justify-center gap-4 text-xs text-[var(--text-tertiary)]">
          <a href={`mailto:${CONTACT_EMAIL}`} className="hover:text-[var(--text-primary)] transition-colors">Support</a>
        </div>
      </div>
    </div>
  );
}
