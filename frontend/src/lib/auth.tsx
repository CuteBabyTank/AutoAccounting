"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import api, { TOKEN_KEY } from "@/lib/api";
import type { User } from "@/types";
import { HOMEPAGE } from "@/lib/roles";

interface AuthState {
  user: User | null;
  token: string | null;
  loading: boolean;
  /** acceptPrivacy: the person ticked the privacy policy box (needed only to create a new account). */
  googleLogin: (credential: string, acceptPrivacy?: boolean) => Promise<User>;
  /** Development-only sign-in; no email signs in as the platform admin. */
  devLogin: (email?: string) => Promise<User>;
  logout: () => void;
  updateNickname: (nickname: string | null) => Promise<User>;
  /** Set your own profile picture (JPG / PNG under 5 MB; the server shrinks it). */
  uploadAvatar: (file: File) => Promise<User>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = sessionStorage.getItem(TOKEN_KEY);
    if (stored) {
      setToken(stored);
      api
        .get("/auth/me")
        .then((res) => setUser(res.data))
        .catch(() => {
          sessionStorage.removeItem(TOKEN_KEY);
          setToken(null);
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const googleLogin = async (credential: string, acceptPrivacy = false): Promise<User> => {
    const res = await api.post("/auth/google", { credential, accept_privacy: acceptPrivacy });
    sessionStorage.setItem(TOKEN_KEY, res.data.token);
    setToken(res.data.token);
    setUser(res.data.user);
    return res.data.user;
  };

  const devLogin = async (email?: string): Promise<User> => {
    const res = await api.post("/auth/dev-login", email ? { email } : {});
    sessionStorage.setItem(TOKEN_KEY, res.data.token);
    setToken(res.data.token);
    setUser(res.data.user);
    return res.data.user;
  };

  const logout = () => {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
    window.location.href = HOMEPAGE;
  };

  const updateNickname = async (nickname: string | null): Promise<User> => {
    const res = await api.patch<User>("/auth/me", { nickname });
    setUser(res.data);
    return res.data;
  };

  const uploadAvatar = async (file: File): Promise<User> => {
    const form = new FormData();
    form.append("file", file);
    const res = await api.put<User>("/auth/me/avatar", form, { headers: { "Content-Type": "multipart/form-data" } });
    setUser(res.data);
    return res.data;
  };

  return (
    <AuthContext.Provider value={{ user, token, loading, googleLogin, devLogin, logout, updateNickname, uploadAvatar }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
