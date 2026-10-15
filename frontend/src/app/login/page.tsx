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
  // Email sign-in stands in for Google while the backend runs in development.
  const [devLoginEnabled, setDevLoginEnabled] = useState(false);
  const [email, setEmail] = useState("");

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
            {GOOGLE_CLIENT_ID ? "Continue with your Google account" : "Continue with your email"}
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

        {devLoginEnabled && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!signingIn && email.trim()) void signIn(() => devLogin(email.trim()));
            }}
            className={GOOGLE_CLIENT_ID ? "mt-6 border-t border-[var(--border)] pt-6" : ""}
          >
            <label htmlFor="dev-email" className="mb-1.5 block text-sm font-medium text-[var(--text-primary)]">
              Email
            </label>
            <input
              id="dev-email"
              type="email"
              required
              autoComplete="email"
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@yourfirm.com"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
            />
            <button
              type="submit"
              disabled={signingIn}
              className="mt-3 w-full rounded-lg bg-[var(--accent)] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-60"
            >
              Sign in
            </button>
            <p className="mt-3 text-center text-xs text-[var(--text-tertiary)]">
              Local development sign-in. The first account becomes the platform admin.
            </p>
          </form>
        )}

        {!GOOGLE_CLIENT_ID && !devLoginEnabled && (
          <p className="text-center text-sm text-[var(--text-secondary)]">Sign-in isn&apos;t configured on this server.</p>
        )}

        {signingIn && <p className="mt-4 text-center text-xs text-[var(--text-secondary)]">Signing in…</p>}
      </div>
    </div>
  );
}
