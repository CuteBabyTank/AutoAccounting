"use client";

import { ThemeProvider } from "next-themes";
import { AuthProvider, useAuth } from "@/lib/auth";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, ReactNode } from "react";
import Sidebar from "@/components/layout/Sidebar";
import AppFlow from "@/components/layout/AppFlow";
import { PUBLIC_ROUTES, canAccess, roleHome } from "@/lib/roles";
import { FeatureOff, FeaturesProvider, useFeatures, type FeatureKey } from "@/lib/features";

/** Pages a maintenance switch can take down (most specific first). */
const PAGE_FEATURES: { path: string; exact?: boolean; key: FeatureKey; label: string }[] = [
  { path: "/accounting/work", key: "work", label: "The work board" },
  { path: "/accounting/companies", key: "companies", label: "Companies" },
  { path: "/accounting", exact: true, key: "documents", label: "Documents" },
  { path: "/team", key: "team", label: "Team" },
];

function AuthGate({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [mounted, setMounted] = useState(false);
  const features = useFeatures();

  const isPublicRoute = PUBLIC_ROUTES.includes(pathname);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted || loading) return;
    if (!user && !isPublicRoute) {
      router.push("/login");
      return;
    }
    if (user && !canAccess(user.role, pathname)) {
      router.push(roleHome(user.role));
    }
  }, [mounted, user, loading, pathname, router, isPublicRoute]);

  // Public routes render immediately. Protected routes hold off mounting children
  // until auth resolves — otherwise their effects fire API calls before the
  // redirect lands.
  if (!mounted || loading) {
    if (isPublicRoute) return <>{children}</>;
    return (
      <div className="flex h-screen overflow-hidden">
        <div className="hidden md:block w-[72px] shrink-0" />
        <main className="lp flex-1 overflow-y-auto pt-14 md:pt-0" />
      </div>
    );
  }

  if (!user && !isPublicRoute) return null;
  if (isPublicRoute) return <>{children}</>;
  // Unverified users live on /pending — full-bleed, no sidebar.
  if (user?.role === "unverified") return <>{children}</>;
  // Wrong-role route: the effect above is redirecting; don't mount the page.
  if (user && !canAccess(user.role, pathname)) return null;

  const page = PAGE_FEATURES.find((p) => (p.exact ? pathname === p.path : pathname.startsWith(p.path)));
  // Hold a switchable page until the switches load, so a page that's off never flashes.
  const content = !page ? children : !features.ready ? null : features.on(page.key) ? children : <FeatureOff label={page.label} />;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      {/* pt-14 clears the fixed mobile top bar in Sidebar; at md+ the sidebar is
          static and the bar is hidden, so the offset goes away. */}
      {/* Every signed-in page shares one background (AppFlow); page roots
          that also carry `.lp` stay transparent so it shows through. */}
      <main className="lp flex-1 min-w-0 overflow-y-auto pt-14 md:pt-0">
        <div className="relative min-h-full">
          <AppFlow />
          {content}
        </div>
      </main>
    </div>
  );
}

export function Providers({ children, nonce }: { children: ReactNode; nonce?: string }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false} storageKey="autoaccounting-theme" nonce={nonce}>
      <AuthProvider>
        <FeaturesProvider>
          <AuthGate>{children}</AuthGate>
        </FeaturesProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
