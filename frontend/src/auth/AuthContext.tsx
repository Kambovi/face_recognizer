import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  changePassword as apiChangePassword,
  getStoredToken,
  login as apiLogin,
  logoutEverywhere,
  setPasswordChangeHandler,
  setStoredToken,
  setUnauthorizedHandler,
  toApiError,
} from "../api/client";

interface AuthUser {
  email: string;
  role: string;
  must_change_password?: boolean;
}

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  isAdmin: boolean;
  isHr: boolean; // admin or HR: people, leave, payroll
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  signOutEverywhere: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const USER_STORAGE_KEY = "face_attendance_user";

function loadStoredUser(): AuthUser | null {
  try {
    const raw = window.localStorage.getItem(USER_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

function storeUser(user: AuthUser | null): void {
  try {
    if (user) {
      window.localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
    } else {
      window.localStorage.removeItem(USER_STORAGE_KEY);
    }
  } catch {
    // best-effort persistence only
  }
}

export function AuthProvider({ children }: { children: ReactNode }): JSX.Element {
  const [token, setToken] = useState<string | null>(() => getStoredToken());
  const [user, setUser] = useState<AuthUser | null>(() => loadStoredUser());
  const [loading, setLoading] = useState(false);

  const signOut = useCallback(() => {
    setStoredToken(null);
    storeUser(null);
    setToken(null);
    setUser(null);
  }, []);

  const applyLogin = useCallback((r: { access_token: string; email: string; role: string; must_change_password: boolean }) => {
    setStoredToken(r.access_token);
    const nextUser: AuthUser = { email: r.email, role: r.role, must_change_password: r.must_change_password };
    storeUser(nextUser);
    setToken(r.access_token);
    setUser(nextUser);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(signOut);
    setPasswordChangeHandler(() =>
      setUser((u) => {
        const next = u ? { ...u, must_change_password: true } : u;
        storeUser(next);
        return next;
      }),
    );
    return () => {
      setUnauthorizedHandler(null);
      setPasswordChangeHandler(null);
    };
  }, [signOut]);

  const signIn = useCallback(async (email: string, password: string) => {
    setLoading(true);
    try {
      applyLogin(await apiLogin({ email, password }));
    } catch (error) {
      throw toApiError(error);
    } finally {
      setLoading(false);
    }
  }, [applyLogin]);

  const changePassword = useCallback(async (current: string, next: string) => {
    try {
      applyLogin(await apiChangePassword(current, next));
    } catch (error) {
      throw toApiError(error);
    }
  }, [applyLogin]);

  const signOutEverywhere = useCallback(async () => {
    try {
      await logoutEverywhere();
    } finally {
      signOut();
    }
  }, [signOut]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user, token, loading, signIn, signOut, signOutEverywhere, changePassword,
      isAdmin: user?.role === "admin",
      isHr: user?.role === "admin" || user?.role === "hr",
    }),
    [user, token, loading, signIn, signOut, signOutEverywhere, changePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// The hook belongs next to its provider; this file is a context module, not
// a component module, so fast-refresh boundaries don't apply here.
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
