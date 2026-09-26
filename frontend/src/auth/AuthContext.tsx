import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { getStoredToken, login as apiLogin, setStoredToken, setUnauthorizedHandler, toApiError } from "../api/client";

interface AuthUser {
  email: string;
  role: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
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

  useEffect(() => {
    setUnauthorizedHandler(signOut);
    return () => setUnauthorizedHandler(null);
  }, [signOut]);

  const signIn = useCallback(async (email: string, password: string) => {
    setLoading(true);
    try {
      const response = await apiLogin({ email, password });
      setStoredToken(response.access_token);
      const nextUser: AuthUser = { email: response.email, role: response.role };
      storeUser(nextUser);
      setToken(response.access_token);
      setUser(nextUser);
    } catch (error) {
      throw toApiError(error);
    } finally {
      setLoading(false);
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, token, loading, signIn, signOut }),
    [user, token, loading, signIn, signOut],
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
