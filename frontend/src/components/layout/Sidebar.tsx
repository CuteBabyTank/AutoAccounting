"use client";

import { useState, useMemo, useEffect, useRef } from "react";
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

const NAV_SECTIONS: { label: string; items: NavItem[] }[] = [
  {
    label: "Workspace",
    items: [
      { id: "documents", label: "Documents", icon: Files, href: "/accounting", roles: FIRM, exact: true },
      { id: "companies", label: "Companies", icon: Buildings, href: "/accounting/companies", roles: FIRM },
    ],
  },
  {
    label: "Manage",
    items: [
      { id: "team", label: "Team", icon: UsersThree, href: "/team", roles: ["admin", "enterprise", "manager"] },
      { id: "admin", label: "Platform admin", icon: Crown, href: "/admin", roles: ["admin"] },
    ],
  },
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
  // Desktop rail: expands on hover (with a short intent delay so passing the cursor
  // across it doesn't flash it open) or when keyboard focus moves inside it.
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queueOpen = (next: boolean) => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => setHovered(next), next ? 80 : 180);
  };
  useEffect(() => () => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
  }, []);
  const expanded = hovered || focused || editingNickname;

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

  const sections = useMemo(() => {
    const role = user?.role || "unverified";
    return NAV_SECTIONS.map((section) => ({
      ...section,
      items: section.items.filter((item) => item.roles.includes(role)),
    })).filter((section) => section.items.length > 0);
  }, [user?.role]);

  const initials = useMemo(() => {
    const name = (user?.nickname || user?.email || "").replace(/@.*/, "");
    const parts = name.split(/[\s._-]+/).filter(Boolean);
    return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
  }, [user?.nickname, user?.email]);

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

    {/* Desktop: a 72px icon rail that holds its place in the layout; the panel inside
        widens over the page on hover (or keyboard focus) so content keeps the space.
        Mobile: the same panel is an off-canvas drawer at full width. */}
    <div
      className="aa-rail lp-skin w-0 md:w-[72px] shrink-0 md:relative h-screen"
      data-open={expanded}
      onMouseEnter={() => queueOpen(true)}
      onMouseLeave={() => queueOpen(false)}
      onFocus={(e) => {
        if (e.target.matches(":focus-visible")) setFocused(true);
      }}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false);
      }}
    >
    <aside
      className={`aa-rail-panel flex flex-col h-screen fixed md:absolute top-0 left-0 z-50 overflow-x-hidden overflow-y-auto text-[var(--text-sidebar)] border-r border-[var(--border-sidebar)] ${
        drawerOpen ? "translate-x-0" : "-translate-x-full"
      } md:translate-x-0`}
    >
      {/* Logo */}
      <div className="px-[19px] pt-5 pb-4 flex items-center justify-between gap-2">
        <Link href="/" className="flex items-center gap-2.5 min-w-0 hover:opacity-80 transition-opacity">
          <Image src="/logo-mark.svg" alt="" width={34} height={24} className="shrink-0" />
          <span className="aa-fade lp-logo-text text-[17px] tracking-tight whitespace-nowrap">AutoAccounting</span>
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
      <nav className="flex-1 px-[14px] pt-1">
        {sections.map((section) => (
          <div key={section.label} className="mb-5">
            <p className="aa-fade px-1 h-5 text-[11px] font-medium text-[var(--text-sidebar-muted)] whitespace-nowrap">
              {section.label}
            </p>
            <div className="h-px mt-1.5 mb-3 bg-[var(--border-sidebar)]" />
            {section.items.map((item) => {
              const active = item.exact ? pathname === item.href : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.id}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  aria-label={item.label}
                  className={`aa-item nav-press flex items-center gap-3 h-11 px-3 rounded-xl mb-1 text-[15px] whitespace-nowrap overflow-hidden ${
                    active
                      ? "aa-item--active text-[var(--text-sidebar)] font-medium"
                      : "text-[var(--text-sidebar-muted)] hover:text-[var(--text-sidebar)]"
                  }`}
                >
                  <item.icon size={20} weight={active ? "regular" : "light"} className="shrink-0" />
                  <span className="aa-fade">{item.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Account card */}
      {user && (
        <div className="px-[14px] pb-3">
          <div className="aa-card flex items-center gap-2.5 p-1 rounded-2xl">
            <span
              aria-hidden="true"
              className="shrink-0 grid place-items-center w-9 h-9 rounded-xl bg-[var(--lp-accent-soft)] text-[var(--accent)] text-[13px] font-semibold"
            >
              {initials}
            </span>
            <div className="aa-fade flex-1 min-w-0 pr-1 text-xs">
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
                    className="flex-1 min-w-0 px-2 py-1 rounded-md border border-[var(--border)] bg-[var(--bg-secondary)] text-xs text-[var(--text-primary)]"
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
                  className="group flex items-center gap-2 w-full text-left"
                  title="Edit display name"
                >
                  <span className="flex-1 min-w-0">
                    <span className="block truncate text-[13px] font-medium text-[var(--text-sidebar)]">
                      {user.nickname || user.email}
                    </span>
                    <span className="block truncate text-[11px] text-[var(--text-sidebar-muted)]">
                      {roleLabel(user.role)}
                      {user.organization_name && ` · ${user.organization_name}`}
                    </span>
                  </span>
                  <PencilSimple
                    size={14}
                    className="shrink-0 text-[var(--text-sidebar-muted)] opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity"
                  />
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="px-[14px] pb-4">
        <div className="h-px mb-2 bg-[var(--border-sidebar)]" />
        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          aria-label={theme === "dark" ? "Light mode" : "Dark mode"}
          className="aa-item nav-press flex items-center gap-3 w-full h-10 px-3 rounded-xl text-sm whitespace-nowrap overflow-hidden text-[var(--text-sidebar-muted)] hover:text-[var(--text-sidebar)]"
        >
          {theme === "dark" ? <Sun size={20} weight="light" className="shrink-0" /> : <Moon size={20} weight="light" className="shrink-0" />}
          <span className="aa-fade">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
        </button>
        <button
          onClick={() => setShowSignOut(true)}
          aria-label="Sign out"
          className="aa-item nav-press flex items-center gap-3 w-full h-10 px-3 rounded-xl text-sm whitespace-nowrap overflow-hidden text-[var(--text-sidebar-muted)] hover:text-[var(--text-sidebar)]"
        >
          <SignOut size={20} weight="light" className="shrink-0" />
          <span className="aa-fade">Sign out</span>
        </button>
      </div>
    </aside>
    </div>
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
