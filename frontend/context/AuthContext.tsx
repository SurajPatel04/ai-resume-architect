"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";

import * as authApi from "@/lib/api/auth";
import type { SignInRequest, SignUpRequest, UserResponse } from "@/types/auth";

// ─── Context shape ──────────────────────────────────────────────────────────

interface AuthContextValue {
  user: UserResponse | null;
  loading: boolean;
  isAuthenticated: boolean;
  signUp: (data: SignUpRequest) => Promise<UserResponse>;
  signIn: (data: SignInRequest) => Promise<UserResponse>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// ─── Provider ───────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [loading, setLoading] = useState(true);

  // Check session on mount
  useEffect(() => {
    authApi
      .getMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const signUp = useCallback(async (data: SignUpRequest) => {
    const newUser = await authApi.signUp(data);
    // Auto sign-in after registration
    const loggedInUser = await authApi.signIn({
      email: data.email,
      password: data.password,
    });
    setUser(loggedInUser);
    return loggedInUser;
  }, []);

  const signIn = useCallback(async (data: SignInRequest) => {
    const loggedInUser = await authApi.signIn(data);
    setUser(loggedInUser);
    return loggedInUser;
  }, []);

  const logout = useCallback(async () => {
    await authApi.logout();
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      isAuthenticated: !!user,
      signUp,
      signIn,
      logout,
    }),
    [user, loading, signUp, signIn, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ─── Hook ───────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an <AuthProvider>");
  }
  return ctx;
}
