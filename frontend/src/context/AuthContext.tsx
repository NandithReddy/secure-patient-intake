/* The original version of this file authenticated in the browser against a
 * hardcoded array:
 *
 *   const users = [{ username: 'admin', password: 'admin123', role: 'admin' }, ...]
 *
 * Every password shipped inside the JavaScript bundle, and `login()` returned a
 * boolean that any user could flip in a debugger. Authentication now happens on
 * the server and this context holds only a token and the identity the server
 * hands back.
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";
import { api, token as tokenStore, type Role } from "../api";

interface User {
  id: number;
  username: string;
  role: Role;
}

interface AuthValue {
  user: User | null;
  loading: boolean;
  login: (u: string, p: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // A token in localStorage is a claim, not proof — it may be expired or signed
  // with a rotated secret. Ask the server who we are before trusting it.
  useEffect(() => {
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login(username, password);
    tokenStore.set(res.access_token);
    setUser(await api.me());
  }, []);

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, logout }),
    [user, loading, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
