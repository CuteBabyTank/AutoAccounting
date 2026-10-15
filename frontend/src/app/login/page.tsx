"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { GoogleLogin, GoogleOAuthProvider } from "@react-oauth/google";
import { useAuth } from "@/lib/auth";
import { roleHome } from "@/lib/roles";
import api from "@/lib/api";
import AppBackdrop from "@/components/layout/AppBackdrop";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading: authLoading, googleLogin, devLogin } = useAuth();
  // A one-click stand-in for Google while the backend has dev login enabled.
  const [devLoginEnabled, setDevLoginEnabled] = useState(false);

  useEffect(() => {
    api
      .get<{ dev_login: boolean }>("/auth/config")
      .then((res) => setDevLoginEnabled(res.data.dev_login))
      .catch(() => setDevLoginEnabled(false));
  }, []);
  const [error, setError] = useState("");
  const [deactivated, setDeactivated] = useState(false);
  const [signingIn, setSigningIn] = useState(false);

  // Already signed in (e.g. a bookmarked /login) — go straight home.
  useEffect(() => {
    if (!authLoading && user) router.replace(roleHome(user.role));
  }, [authLoading, user, router]);

  const signIn = async (attempt: () => Promise<{ role: Parameters<typeof roleHome>[0] }>) => {
    setError("");
    setDeactivated(false);
    setSigningIn(true);
    try {
      const signedIn = await attempt();
      router.push(roleHome(signedIn.role));
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } };
      const detail = axiosErr.response?.data?.detail || "";
      if (axiosErr.response?.status === 403 && /deactivat/i.test(detail)) {
        setDeactivated(true);
      } else {
        setError(detail || "Sign-in failed");
      }
    } finally {
      setSigningIn(false);
    }
  };

  const handleSuccess = (credentialResponse: { credential?: string }) => {
    const credential = credentialResponse.credential;
    if (!credential) return;
    void signIn(() => googleLogin(credential));
  };

  return (
    <div className="lp relative min-h-screen flex items-center justify-center p-4">
      <AppBackdrop />
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] p-8 shadow-2xl page-enter">
        <div className="mb-8 flex flex-col items-center text-center">
          <Image src="/logo-mark.svg" alt="" width={56} height={40} priority />
          <h1 className="mt-4 text-2xl font-bold text-[var(--text-primary)]">Sign in to AutoAccounting</h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Continue with your Google account
          </p>
        </div>

        {error && <p className="mb-4 text-center text-sm text-[var(--error)]">{error}</p>}

        {deactivated && (
          <div className="mb-5 rounded-xl border border-[var(--border)] bg-[var(--bg-tertiary)] p-4">
            <p className="mb-1 text-sm font-semibold text-[var(--text-primary)]">Account disabled</p>
            <p className="text-xs leading-relaxed text-[var(--text-secondary)]">
              Your account has been disabled. Ask your firm&apos;s owner, or the platform admin, to re-enable it.
            </p>
          </div>
        )}

        {GOOGLE_CLIENT_ID && (
          <div className="flex justify-center">
            <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
              <GoogleLogin
                onSuccess={handleSuccess}
                onError={() => setError("Sign-in failed")}
                shape="rectangular"
                theme="outline"
                size="large"
              />
            </GoogleOAuthProvider>
          </div>
        )}

        {/* Temporary stand-in for Google SSO: looks like the Google button, signs
            straight in through the backend's development-only endpoint. Shown
            only when no Google client ID is configured. */}
        {!GOOGLE_CLIENT_ID && devLoginEnabled && (
          <div className="flex justify-center">
            <button
              type="button"
              onClick={() => {
                if (!signingIn) void signIn(() => devLogin());
              }}
              disabled={signingIn}
              className="inline-flex h-10 items-center gap-3 rounded-[4px] border border-[#dadce0] bg-white pl-3 pr-4 text-sm font-medium text-[#3c4043] transition-colors hover:bg-[#f8faff] hover:border-[#d2e3fc] disabled:opacity-60"
            >
              <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
                <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
              </svg>
              Sign in with Google
            </button>
          </div>
        )}

        {!GOOGLE_CLIENT_ID && !devLoginEnabled && (
          <p className="text-center text-sm text-[var(--text-secondary)]">Sign-in isn&apos;t configured on this server.</p>
        )}

        {signingIn && <p className="mt-4 text-center text-xs text-[var(--text-secondary)]">Signing in…</p>}
      </div>
    </div>
  );
}
