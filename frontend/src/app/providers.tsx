"use client";

import { ThemeProvider } from "next-themes";
import { AuthProvider, useAuth } from "@/lib/auth";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, ReactNode } from "react";
import Sidebar from "@/components/layout/Sidebar";
import { PUBLIC_ROUTES, canAccess, roleHome } from "@/lib/roles";

function AuthGate({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [mounted, setMounted] = useState(false);

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
        <div className="hidden md:block w-[210px] shrink-0" />
        <main className="flex-1 overflow-y-auto pt-14 md:pt-0" />
      </div>
    );
  }

  if (!user && !isPublicRoute) return null;
  if (isPublicRoute) return <>{children}</>;
  // Unverified users live on /pending — full-bleed, no sidebar.
  if (user?.role === "unverified") return <>{children}</>;
  // Wrong-role route: the effect above is redirecting; don't mount the page.
  if (user && !canAccess(user.role, pathname)) return null;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      {/* pt-14 clears the fixed mobile top bar in Sidebar; at md+ the sidebar is
          static and the bar is hidden, so the offset goes away. */}
      <main className="flex-1 min-w-0 overflow-y-auto pt-14 md:pt-0">{children}</main>
    </div>
  );
}

export function Providers({ children, nonce }: { children: ReactNode; nonce?: string }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false} storageKey="autoaccounting-theme" nonce={nonce}>
      <AuthProvider>
        <AuthGate>{children}</AuthGate>
      </AuthProvider>
    </ThemeProvider>
  );
}
