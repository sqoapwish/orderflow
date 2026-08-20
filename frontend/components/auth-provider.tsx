"use client";

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { apiRequest, clearTokens, loadTokens, saveTokens } from "@/lib/api";
import type { AuthResponse, User } from "@/lib/types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login(email: string, password: string): Promise<void>;
  register(email: string, password: string): Promise<void>;
  logout(): Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function restore() {
      if (!loadTokens()) {
        if (active) setLoading(false);
        return;
      }
      try {
        const current = await apiRequest<User>("/auth/me");
        if (active) setUser(current);
      } catch {
        clearTokens();
      } finally {
        if (active) setLoading(false);
      }
    }
    void restore();
    return () => {
      active = false;
    };
  }, []);

  const authenticate = useCallback(async (mode: "login" | "register", email: string, password: string) => {
    const response = await apiRequest<AuthResponse>(
      `/auth/${mode}`,
      { method: "POST", body: JSON.stringify({ email, password }) },
      { auth: false },
    );
    saveTokens(response.tokens);
    setUser(response.user);
  }, []);

  const login = useCallback(
    (email: string, password: string) => authenticate("login", email, password),
    [authenticate],
  );
  const register = useCallback(
    (email: string, password: string) => authenticate("register", email, password),
    [authenticate],
  );
  const logout = useCallback(async () => {
    const tokens = loadTokens();
    try {
      if (tokens) {
        await apiRequest<void>(
          "/auth/logout",
          { method: "POST", body: JSON.stringify({ refresh_token: tokens.refresh_token }) },
          { auth: false },
        );
      }
    } finally {
      clearTokens();
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
