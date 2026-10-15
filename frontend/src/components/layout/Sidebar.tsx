"use client";

import { useState, useMemo, useEffect } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import {
  Files,
  Buildings,
  UsersThree,
  Crown,
  SignOut,
  Moon,
  Sun,
  PencilSimple,
  Check,
  X,
  List,
} from "@phosphor-icons/react";
import { useAuth } from "@/lib/auth";
import { useTheme } from "next-themes";
import type { UserRole } from "@/types";
import { roleLabel } from "@/lib/roles";

interface NavItem {
  id: string;
  label: string;
  icon: typeof Files;
  href: string;
  roles: UserRole[];
  /** Active only on this exact path (for a parent route like /accounting). */
  exact?: boolean;
}

const FIRM: UserRole[] = ["admin", "enterprise", "manager", "employee"];

const ALL_NAV_ITEMS: NavItem[] = [
  { id: "documents", label: "Documents", icon: Files, href: "/accounting", roles: FIRM, exact: true },
  { id: "companies", label: "Companies", icon: Buildings, href: "/accounting/companies", roles: FIRM },
  { id: "team", label: "Team", icon: UsersThree, href: "/team", roles: ["admin", "enterprise", "manager"] },
  { id: "admin", label: "Platform admin", icon: Crown, href: "/admin", roles: ["admin"] },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { user, logout, updateNickname } = useAuth();
  const [editingNickname, setEditingNickname] = useState(false);
  const [nicknameDraft, setNicknameDraft] = useState("");
  const [savingNickname, setSavingNickname] = useState(false);
  const { theme, setTheme } = useTheme();
  const [showSignOut, setShowSignOut] = useState(false);
  // Mobile off-canvas drawer. Desktop (md+) ignores this and renders the sidebar statically.
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Close the drawer whenever the route changes (tapping a nav item navigates).
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  // Lock body scroll while the mobile drawer is open so the page behind stays put.
  useEffect(() => {
    if (!drawerOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [drawerOpen]);

  const navItems = useMemo(() => {
    const role = user?.role || "unverified";
    return ALL_NAV_ITEMS.filter((item) => item.roles.includes(role));
  }, [user?.role]);

  return (
    <>
    {/* Mobile top bar — hamburger + wordmark. Only below md; the static sidebar takes over at md+. */}
    <header className="lp-skin md:hidden fixed top-0 inset-x-0 z-40 h-14 flex items-center gap-2 px-3 bg-[var(--bg-sidebar)] border-b border-[var(--border-sidebar)]">
      <button
        onClick={() => setDrawerOpen(true)}
        aria-label="Open menu"
        aria-expanded={drawerOpen}
        className="nav-press flex items-center justify-center w-11 h-11 rounded-lg text-[var(--text-sidebar)] hover:bg-[var(--bg-sidebar-hover)] transition-colors"
      >
        <List size={24} />
      </button>
      <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
        <Image src="/logo-mark.svg" alt="" width={34} height={24} />
        <span className="lp-logo-text text-[18px] tracking-tight text-[var(--text-sidebar)]">AutoAccounting</span>
      </Link>
    </header>

    {/* Mobile drawer scrim */}
    {drawerOpen && (
      <div
        className="md:hidden fixed inset-0 z-40 bg-black/40 overlay-enter"
        onClick={() => setDrawerOpen(false)}
        aria-hidden="true"
      />
    )}

    <aside
      className={`lp-skin flex flex-col w-[264px] md:w-[210px] shrink-0 h-screen fixed md:sticky top-0 left-0 z-50 md:z-auto overflow-y-auto bg-[var(--bg-sidebar)] text-[var(--text-sidebar)] border-r border-[var(--border-sidebar)] transition-transform duration-300 ease-out md:transition-none ${
        drawerOpen ? "translate-x-0" : "-translate-x-full"
      } md:translate-x-0`}
    >
      {/* Logo */}
      <div className="p-5 pb-2 flex items-center justify-between gap-2">
        <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <Image src="/logo-mark.svg" alt="" width={34} height={24} />
          <h1 className="lp-logo-text text-[17px] tracking-tight">AutoAccounting</h1>
        </Link>
        {/* Close drawer (mobile only) */}
        <button
          onClick={() => setDrawerOpen(false)}
          aria-label="Close menu"
          className="md:hidden nav-press flex items-center justify-center w-10 h-10 -mr-1 rounded-lg text-[var(--text-sidebar-muted)] hover:bg-[var(--bg-sidebar-hover)] hover:text-[var(--text-sidebar)] transition-colors"
        >
          <X size={22} />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-2">
        {navItems.map((item) => {
          const active = item.exact ? pathname === item.href : pathname.startsWith(item.href);
          return (
            <Link
              key={item.id}
              href={item.href}
              className={`nav-press flex items-center gap-3 px-3 py-2.5 rounded-lg mb-1 text-sm transition-colors ${
                active
                  ? "bg-[var(--bg-sidebar-active)] text-[var(--accent)] font-semibold"
                  : "text-[var(--text-sidebar-muted)] hover:bg-[var(--bg-sidebar-hover)] hover:text-[var(--text-sidebar)]"
              }`}
            >
              <item.icon size={20} weight={active ? "fill" : "regular"} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-3 pb-4 space-y-2">
        {/* Theme toggle */}
        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="nav-press flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-[var(--text-sidebar-muted)] hover:bg-[var(--bg-sidebar-hover)] hover:text-[var(--text-sidebar)] transition-colors"
        >
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          {theme === "dark" ? "Light Mode" : "Dark Mode"}
        </button>

        {/* User info */}
        {user && (
          <div className="px-3 py-2 text-xs text-[var(--text-sidebar-muted)]">
            {editingNickname ? (
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (savingNickname) return;
                  setSavingNickname(true);
                  try {
                    const next = nicknameDraft.trim();
                    await updateNickname(next.length ? next : null);
                    setEditingNickname(false);
                  } catch {
                    /* leave open so the user can retry */
                  } finally {
                    setSavingNickname(false);
                  }
                }}
                className="flex items-center gap-1"
              >
                <input
                  type="text"
                  autoFocus
                  value={nicknameDraft}
                  onChange={(e) => setNicknameDraft(e.target.value)}
                  maxLength={100}
                  placeholder="Display name"
                  disabled={savingNickname}
                  className="flex-1 min-w-0 px-2 py-1 rounded border border-[var(--border)] bg-[var(--bg-secondary)] text-xs text-[var(--text-primary)]"
                />
                <button
                  type="submit"
                  disabled={savingNickname}
                  aria-label="Save"
                  className="p-1 rounded hover:bg-[var(--bg-sidebar-hover)] text-[var(--accent)]"
                >
                  <Check size={14} weight="bold" />
                </button>
                <button
                  type="button"
                  onClick={() => setEditingNickname(false)}
                  disabled={savingNickname}
                  aria-label="Cancel"
                  className="p-1 rounded hover:bg-[var(--bg-sidebar-hover)]"
                >
                  <X size={14} />
                </button>
              </form>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setNicknameDraft(user.nickname ?? "");
                  setEditingNickname(true);
                }}
                className="group flex items-center gap-1 w-full text-left"
                title="Edit display name"
              >
                <span className="truncate text-[var(--text-sidebar)] font-medium">
                  {user.nickname || user.email}
                </span>
                <PencilSimple
                  size={12}
                  className="shrink-0 opacity-0 group-hover:opacity-100 text-[var(--text-sidebar-muted)]"
                />
              </button>
            )}
            {user.nickname && (
              <p className="truncate text-[10px] opacity-70">{user.email}</p>
            )}
            <p className="mt-0.5 font-medium">{roleLabel(user.role)}</p>
            {user.organization_name && <p className="truncate text-[10px] opacity-70">{user.organization_name}</p>}
          </div>
        )}

        {/* Logout */}
        <button
          onClick={() => setShowSignOut(true)}
          className="nav-press flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-[var(--text-sidebar-muted)] hover:bg-[var(--bg-sidebar-hover)] hover:text-[var(--text-sidebar)] transition-colors"
        >
          <SignOut size={18} />
          Sign Out
        </button>

        <p className="px-3 text-[10px] text-[var(--text-sidebar-muted)] opacity-60">v1.0.0</p>
      </div>
    </aside>
    {/* Sign Out Confirmation Modal — rendered via portal to escape sidebar stacking context */}
    {showSignOut && createPortal(
      <div className="lp-skin overlay-enter fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
        <div className="modal-enter bg-[var(--bg-secondary)] rounded-xl border border-[var(--border)] p-6 w-80 shadow-xl">
          <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">Sign Out</h3>
          <p className="text-sm text-[var(--text-secondary)] mb-6">Are you sure you want to sign out?</p>
          <div className="flex items-center gap-3 justify-end">
            <button
              onClick={() => setShowSignOut(false)}
              className="px-4 py-2 rounded-lg border border-[var(--border)] text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-primary)] transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => { logout(); setShowSignOut(false); }}
              className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition-colors"
            >
              Sign Out
            </button>
          </div>
        </div>
      </div>,
      document.body
    )}
    </>
  );
}
