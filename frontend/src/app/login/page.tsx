"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { GoogleLogin, GoogleOAuthProvider } from "@react-oauth/google";
import { ArrowLeft, EnvelopeSimple, X } from "@phosphor-icons/react";
import { useAuth } from "@/lib/auth";
import { HOMEPAGE, roleHome } from "@/lib/roles";
import api from "@/lib/api";
import AppFlow from "@/components/layout/AppFlow";
import LogoMark from "@/components/layout/LogoMark";
import LegalText, { PRIVACY_POLICY, TERMS_OF_SERVICE, type LegalDoc } from "@/components/LegalText";
import { Divider, EmailField, LINK, NewPasswordHint, PasswordField, PRIMARY, MIN_PASSWORD } from "@/components/auth/PasswordForms";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

/** signin / signup: the two tabs. forgot: ask for a reset link. sent: "check your email". reset / verify: an emailed
 * link was opened. unverified: right password, email not confirmed yet. */
type View = "signin" | "signup" | "forgot" | "sent" | "reset" | "verify" | "unverified";

interface Config {
  dev_login: boolean;
  password_login: boolean;
  password_signup: boolean;
}

// "privacy_consent_updated:privacy,terms" names the documents updated since the person last accepted.
function updatedDocs(detail: string): LegalDoc[] {
  const names = detail.split(":")[1]?.split(",") ?? [];
  const docs = [names.includes("terms") && TERMS_OF_SERVICE, names.includes("privacy") && PRIVACY_POLICY];
  const found = docs.filter((doc): doc is LegalDoc => !!doc);
  return found.length ? found : [TERMS_OF_SERVICE, PRIVACY_POLICY];
}

function joinTitles(docs: LegalDoc[]): string {
  return docs.map((doc) => doc.title).join(" and ");
}

type ApiError = { response?: { status?: number; data?: { detail?: unknown } } };
const detailOf = (err: unknown) => {
  const d = (err as ApiError).response?.data?.detail;
  return typeof d === "string" ? d : Array.isArray(d) ? "Check the email and password and try again." : "";
};

/**
 * Sign in or create an account: Google, or email + password. Also opens the links we email (?verify=, ?reset=).
 * With ?embed=1 it's the homepage's sign-in pop-up: no page background, a close button, and it tells the homepage
 * its height; signing in moves the whole tab into the app.
 */
export default function LoginPage() {
  const router = useRouter();
  const { user, loading: authLoading, googleLogin, devLogin, signInWith } = useAuth();
  const [config, setConfig] = useState<Config>({ dev_login: false, password_login: true, password_signup: false });
  const [embed, setEmbed] = useState(false);
  const [view, setView] = useState<View>("signin");
  const [linkToken, setLinkToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [accept, setAccept] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [deactivated, setDeactivated] = useState(false);
  const [busy, setBusy] = useState(false);
  // A Google token waits here until the person agrees: a new account (nothing is stored yet) ticks the box for both
  // documents; an existing one is shown only what was updated since they last accepted and presses OK.
  const [consentCredential, setConsentCredential] = useState<string | null>(null);
  const [consentIsNew, setConsentIsNew] = useState(true);
  const [consentDocs, setConsentDocs] = useState<LegalDoc[]>([TERMS_OF_SERVICE, PRIVACY_POLICY]);
  const [agreed, setAgreed] = useState(false);
  const [legalDoc, setLegalDoc] = useState(TERMS_OF_SERVICE);
  const card = useRef<HTMLDivElement>(null);

  // Read ?embed / ?verify / ?reset once, then take the token out of the address bar and history.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setEmbed(params.get("embed") === "1");
    const verify = params.get("verify");
    const reset = params.get("reset");
    if (verify || reset) {
      setLinkToken(verify || reset || "");
      setView(verify ? "verify" : "reset");
      params.delete("verify");
      params.delete("reset");
      const rest = params.toString();
      window.history.replaceState(null, "", `/login${rest ? `?${rest}` : ""}`);
    } else if (params.get("mode") === "signup") {
      setView("signup");
    }
    api.get<Config>("/auth/config").then((res) => setConfig(res.data)).catch(() => undefined);
  }, []);

  /** Into the app: the whole tab, even from inside the homepage pop-up. */
  const go = (role: Parameters<typeof roleHome>[0]) => {
    const target = roleHome(role);
    if (embed && window.top && window.top !== window) window.top.location.assign(target);
    else router.push(target);
  };

  // Already signed in (a bookmarked /login, or the pop-up after signing in elsewhere): go straight in. Not while an
  // emailed link is being used, which signs in by itself.
  useEffect(() => {
    if (!authLoading && user && view !== "verify" && view !== "reset") go(user.role);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- go only depends on embed, read before this matters
  }, [authLoading, user]);

  // In the pop-up the frame is exactly the card: no page background, no scrollbars.
  useEffect(() => {
    if (!embed) return;
    for (const el of [document.documentElement, document.body]) {
      el.style.background = "transparent";
      el.style.overflow = "hidden";
    }
  }, [embed]);

  // The pop-up grows and shrinks with the card.
  useEffect(() => {
    if (!embed || !card.current || window.parent === window) return;
    const post = () =>
      window.parent.postMessage({ type: "aa-login-height", height: card.current?.offsetHeight ?? 0 }, window.location.origin);
    const ro = new ResizeObserver(post);
    ro.observe(card.current);
    post();
    return () => ro.disconnect();
  }, [embed]);

  const close = () => window.parent.postMessage({ type: "aa-login-close" }, window.location.origin);

  const switchTo = (next: View) => {
    setView(next);
    setError("");
    setNotice("");
    setPassword("");
  };

  const run = async (attempt: () => Promise<void>) => {
    setError("");
    setDeactivated(false);
    setBusy(true);
    try {
      await attempt();
    } catch (err) {
      const status = (err as ApiError).response?.status;
      const detail = detailOf(err);
      if (status === 403 && /deactivat/i.test(detail)) setDeactivated(true);
      else if (status === 403 && /confirm your email/i.test(detail)) setView("unverified");
      else setError(detail || "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  // ---- Google --------------------------------------------------------------------------------------------------
  const googleSignIn = async (credential: string, acceptPrivacy = false) => {
    setError("");
    setDeactivated(false);
    setBusy(true);
    try {
      const signedIn = await googleLogin(credential, acceptPrivacy);
      setConsentCredential(null);
      go(signedIn.role);
    } catch (err) {
      const status = (err as ApiError).response?.status;
      const detail = detailOf(err);
      if (status === 428 && detail.startsWith("privacy_consent_")) {
        setConsentCredential(credential);
        const isNew = detail === "privacy_consent_required";
        const docs = isNew ? [TERMS_OF_SERVICE, PRIVACY_POLICY] : updatedDocs(detail);
        setConsentIsNew(isNew);
        setConsentDocs(docs);
        setLegalDoc(docs[0]);
        setAgreed(!isNew); // an update is accepted by pressing OK
      } else if (status === 403 && /deactivat/i.test(detail)) {
        setDeactivated(true);
      } else {
        setError(detail || "Sign-in failed");
      }
    } finally {
      setBusy(false);
    }
  };

  // ---- Email + password ----------------------------------------------------------------------------------------
  const passwordSignIn = (e: React.FormEvent) => {
    e.preventDefault();
    void run(async () => go((await signInWith("/auth/password/login", { email, password })).role));
  };
  const register = (e: React.FormEvent) => {
    e.preventDefault();
    if (!accept) return setError("Please accept the terms of service and privacy policy to continue.");
    void run(async () => {
      const res = await api.post<{ detail: string }>("/auth/password/register", { email, password, accept_privacy: true });
      setNotice(res.data.detail);
      setPassword("");
      setView("sent");
    });
  };
  const forgot = (e: React.FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const res = await api.post<{ detail: string }>("/auth/password/forgot", { email });
      setNotice(res.data.detail);
      setView("sent");
    });
  };
  const resend = () =>
    void run(async () => {
      const res = await api.post<{ detail: string }>("/auth/password/resend", { email });
      setNotice(res.data.detail);
      setView("sent");
    });
  const resetPassword = (e: React.FormEvent) => {
    e.preventDefault();
    void run(async () => go((await signInWith("/auth/password/reset", { token: linkToken, password })).role));
  };
  const confirmEmail = () =>
    void run(async () => go((await signInWith("/auth/password/verify", { token: linkToken })).role));

  // An emailed verify link signs in as soon as the page opens.
  const verifying = useRef(false);
  useEffect(() => {
    if (view === "verify" && linkToken && !verifying.current) {
      verifying.current = true;
      confirmEmail();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once per link
  }, [view, linkToken]);

  const signup = config.password_signup;
  const title =
    view === "signup" ? "Create your account"
      : view === "forgot" ? "Reset your password"
        : view === "reset" ? "Choose a new password"
          : view === "verify" ? "Confirming your email"
            : view === "sent" ? "Check your email"
              : view === "unverified" ? "Confirm your email first"
                : "Sign in to AutoAccounting";

  const googleButton = (label: "signin_with" | "signup_with") =>
    GOOGLE_CLIENT_ID ? (
      <div className="flex justify-center">
        <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
          <GoogleLogin
            onSuccess={(r) => r.credential && void googleSignIn(r.credential)}
            onError={() => setError("Google sign-in didn't finish. Please try again.")}
            text={label}
            shape="rectangular"
            theme="outline"
            size="large"
            width="320"
          />
        </GoogleOAuthProvider>
      </div>
    ) : config.dev_login ? (
      // Development stand-in for Google (no client ID configured): signs straight in through the dev endpoint.
      <div className="flex justify-center">
        <button
          type="button"
          onClick={() => !busy && void run(async () => go((await devLogin()).role))}
          disabled={busy}
          className="inline-flex h-10 w-full max-w-[320px] items-center justify-center gap-3 rounded-[4px] border border-[#dadce0] bg-white px-4 text-sm font-medium text-[#3c4043] transition-colors hover:border-[#d2e3fc] hover:bg-[#f8faff] disabled:opacity-60"
        >
          <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
            <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
            <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
            <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
            <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
          </svg>
          {label === "signup_with" ? "Sign up with Google" : "Sign in with Google"}
        </button>
      </div>
    ) : null;

  const tabs = (view === "signin" || view === "signup") && signup && (
    <div role="tablist" aria-label="Sign in or create an account" className="mb-6 grid grid-cols-2 rounded-lg bg-[var(--bg-tertiary)] p-1 text-sm">
      {(["signin", "signup"] as const).map((v) => (
        <button
          key={v}
          type="button"
          role="tab"
          aria-selected={view === v}
          onClick={() => switchTo(v)}
          className={`rounded-md py-1.5 font-medium transition-colors ${
            view === v ? "bg-[var(--bg-secondary)] text-[var(--text-primary)] shadow-sm" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          }`}
        >
          {v === "signin" ? "Sign in" : "Create account"}
        </button>
      ))}
    </div>
  );

  const back = (to: View, label = "Back to sign in") => (
    <button type="button" onClick={() => switchTo(to)} className="mt-5 flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
      <ArrowLeft size={14} /> {label}
    </button>
  );

  const body = (
    <div
      ref={card}
      className={`relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] p-8 ${embed ? "" : "shadow-2xl page-enter"}`}
    >
      {embed && (
        <button type="button" onClick={close} aria-label="Close" className="aa-icon-btn absolute right-3 top-3">
          <X size={18} />
        </button>
      )}
      <div className="mb-6 flex flex-col items-center text-center">
        {embed ? (
          <LogoMark width={48} height={34} />
        ) : (
          <a href={HOMEPAGE} aria-label="AutoAccounting homepage" className="transition-opacity hover:opacity-80">
            <LogoMark width={56} height={40} />
          </a>
        )}
        <h1 id="login-title" className="mt-4 text-2xl font-bold text-[var(--text-primary)]">{title}</h1>
      </div>

      {error && <p role="alert" className="mb-4 rounded-lg bg-[var(--alert-error-bg)] px-3 py-2 text-center text-sm text-[var(--alert-error-text)]">{error}</p>}
      {deactivated && (
        <div className="mb-5 rounded-xl border border-[var(--border)] bg-[var(--bg-tertiary)] p-4">
          <p className="mb-1 text-sm font-semibold text-[var(--text-primary)]">Account disabled</p>
          <p className="text-xs leading-relaxed text-[var(--text-secondary)]">
            Your account has been disabled. Ask your firm&apos;s owner, or the platform admin, to re-enable it.
          </p>
        </div>
      )}

      {consentCredential ? (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-tertiary)] p-4">
          <p className="mb-1 text-sm font-semibold text-[var(--text-primary)]">
            {consentIsNew ? "Create your account" : `We've updated our ${joinTitles(consentDocs)}`}
          </p>
          <p className="mb-4 text-xs leading-relaxed text-[var(--text-secondary)]">
            {consentIsNew
              ? "This Google account isn't registered yet. To create an account, please read and accept our terms and how we handle your data. If you don't accept, no account is created and nothing is saved."
              : `Please read the updated ${joinTitles(consentDocs)}. By pressing OK you agree to ${consentDocs.length > 1 ? "them" : "it"}. You can't continue into AutoAccounting until you do.`}
          </p>
          {consentDocs.length > 1 && (
            <div role="tablist" aria-label="Legal documents" className="mb-2 flex gap-1">
              {consentDocs.map((doc) => (
                <button
                  key={doc.src}
                  type="button"
                  role="tab"
                  aria-selected={legalDoc.src === doc.src}
                  onClick={() => setLegalDoc(doc)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                    legalDoc.src === doc.src
                      ? "bg-[var(--bg-card)] text-[var(--text-primary)] ring-1 ring-[var(--border)]"
                      : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
                  }`}
                >
                  {doc.title}
                </button>
              ))}
            </div>
          )}
          <LegalText doc={legalDoc} className="mb-4 max-h-64" />
          {consentIsNew && (
            <label className="mb-4 flex cursor-pointer items-start gap-2.5 text-sm text-[var(--text-primary)]">
              <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--accent)]" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} disabled={busy} />
              <LegalAgree />
            </label>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => { setConsentCredential(null); setAgreed(false); }} disabled={busy}
              className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-60">
              Cancel
            </button>
            <button type="button" onClick={() => consentCredential && agreed && void googleSignIn(consentCredential, true)} disabled={!agreed || busy}
              className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60">
              {consentIsNew ? "Create account" : "OK"}
            </button>
          </div>
        </div>
      ) : view === "signin" ? (
        <>
          {tabs}
          {googleButton("signin_with")}
          {(GOOGLE_CLIENT_ID || config.dev_login) && config.password_login && <Divider label="or with your email" />}
          {config.password_login && (
            <form onSubmit={passwordSignIn} className="space-y-4" noValidate={false}>
              <EmailField value={email} onChange={setEmail} />
              <PasswordField id="password" label="Password" value={password} onChange={setPassword} autoComplete="current-password" />
              {signup && (
                <div className="-mt-1 text-right text-sm">
                  <button type="button" className={LINK} onClick={() => switchTo("forgot")}>Forgot password?</button>
                </div>
              )}
              <button type="submit" disabled={busy || !email || !password} className={PRIMARY}>
                {busy ? "Signing in…" : "Sign in"}
              </button>
            </form>
          )}
          {!GOOGLE_CLIENT_ID && !config.dev_login && !config.password_login && (
            <p className="text-center text-sm text-[var(--text-secondary)]">Sign-in isn&apos;t configured on this server.</p>
          )}
        </>
      ) : view === "signup" ? (
        <>
          {tabs}
          {googleButton("signup_with")}
          {(GOOGLE_CLIENT_ID || config.dev_login) && <Divider label="or with your email" />}
          <form onSubmit={register} className="space-y-4">
            <EmailField value={email} onChange={setEmail} />
            <PasswordField id="new-password" label="Password" value={password} onChange={setPassword} autoComplete="new-password"
              hint={<NewPasswordHint value={password} />} />
            <label className="flex cursor-pointer items-start gap-2.5 text-sm text-[var(--text-primary)]">
              <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--accent)]" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
              <LegalAgree />
            </label>
            <button type="submit" disabled={busy || !email || [...password].length < MIN_PASSWORD || !accept} className={PRIMARY}>
              {busy ? "Creating your account…" : "Create account"}
            </button>
            <p className="text-center text-xs leading-relaxed text-[var(--text-secondary)]">
              We&apos;ll email you a link to confirm it&apos;s you. Then your firm owner adds you to their team.
            </p>
          </form>
        </>
      ) : view === "forgot" ? (
        <form onSubmit={forgot} className="space-y-4">
          <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
            Enter the email you sign in with and we&apos;ll send you a link to choose a new password. It works for Google accounts too.
          </p>
          <EmailField value={email} onChange={setEmail} autoFocus />
          <button type="submit" disabled={busy || !email} className={PRIMARY}>{busy ? "Sending…" : "Send reset link"}</button>
          {back("signin")}
        </form>
      ) : view === "sent" ? (
        <div className="text-center">
          <EnvelopeSimple size={40} className="mx-auto text-[var(--accent)]" />
          <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">{notice}</p>
          {email && <p className="mt-1 text-sm font-medium text-[var(--text-primary)]">{email}</p>}
          <p className="mt-4 text-xs text-[var(--text-tertiary)]">The link works once. You can close this window.</p>
          <div className="flex justify-center">{back("signin")}</div>
        </div>
      ) : view === "unverified" ? (
        <div className="text-center">
          <EnvelopeSimple size={40} className="mx-auto text-[var(--accent)]" />
          <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">
            Your password is right, but this email isn&apos;t confirmed yet. Open the link we sent when you signed up, or get a new one.
          </p>
          {signup && (
            <button type="button" onClick={resend} disabled={busy} className={`${PRIMARY} mt-5`}>
              {busy ? "Sending…" : "Send a new link"}
            </button>
          )}
          <div className="flex justify-center">{back("signin")}</div>
        </div>
      ) : view === "reset" ? (
        <form onSubmit={resetPassword} className="space-y-4">
          <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
            Choose a new password. You&apos;ll be signed out everywhere else and signed in here.
          </p>
          <PasswordField id="new-password" label="New password" value={password} onChange={setPassword} autoComplete="new-password"
            hint={<NewPasswordHint value={password} />} />
          <button type="submit" disabled={busy || [...password].length < MIN_PASSWORD} className={PRIMARY}>
            {busy ? "Saving…" : "Save and sign in"}
          </button>
          {back("forgot", "Ask for a new link")}
        </form>
      ) : (
        <div className="text-center text-sm text-[var(--text-secondary)]">
          {busy ? "One moment…" : error ? back("signin") : "Done. Taking you in…"}
        </div>
      )}
    </div>
  );

  if (embed) return <div className="flex justify-center bg-transparent">{body}</div>;
  return (
    <div className="lp relative flex min-h-screen items-center justify-center p-4">
      <AppFlow />
      {body}
    </div>
  );
}

function LegalAgree() {
  return (
    <span>
      I have read and agree to the{" "}
      <a href={TERMS_OF_SERVICE.src} target="_blank" rel="noopener" className="font-medium text-[var(--accent)] underline underline-offset-2">
        {TERMS_OF_SERVICE.title}
      </a>{" "}
      and the{" "}
      <a href={PRIVACY_POLICY.src} target="_blank" rel="noopener" className="font-medium text-[var(--accent)] underline underline-offset-2">
        {PRIVACY_POLICY.title}
      </a>
      .
    </span>
  );
}
