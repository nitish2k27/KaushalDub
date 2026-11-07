import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setDevToken } from "./api";
import { devAuth, supabase } from "./supabase";
import type { Role, User } from "./types";

const PENDING_ROLE = "kd_pending_role";

interface AuthState {
  user: User | null;
  loading: boolean;
  error: string | null;
  signInWithGoogle: (role: Role) => Promise<void>;
  devSignIn: (role: Role, email: string, name: string) => Promise<void>;
  setRole: (role: Role) => Promise<User>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

function pending(): Role | null {
  try {
    return (localStorage.getItem(PENDING_ROLE) as Role) || null;
  } catch {
    return null;
  }
}
function setPending(r: Role | null) {
  try {
    if (r) localStorage.setItem(PENDING_ROLE, r);
    else localStorage.removeItem(PENDING_ROLE);
  } catch {
    /* ignore */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      let me = await api<User>("/me");
      const want = pending();
      if (want && want !== me.role) me = { ...me, ...(await api<User>("/me/role", { method: "PUT", body: { role: want } })) };
      setPending(null);
      setUser(me);
      setError(null);
    } catch (e) {
      setUser(null);
      if (e instanceof Error && !("status" in e && (e as { status: number }).status === 401)) setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (supabase) {
      const { data } = supabase.auth.onAuthStateChange((event, session) => {
        if (session && (event === "SIGNED_IN" || event === "INITIAL_SESSION" || event === "TOKEN_REFRESHED")) {
          if (event !== "TOKEN_REFRESHED") void load();
        } else if (!session) {
          setUser(null);
          setLoading(false);
        }
      });
      return () => data.subscription.unsubscribe();
    }
    void load();
  }, [load]);

  const signInWithGoogle = async (role: Role) => {
    if (!supabase) throw new Error("Supabase is not configured (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY).");
    setPending(role);
    const { error: e } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: window.location.origin + "/", queryParams: { prompt: "select_account" } },
    });
    if (e) throw e;
  };

  const devSignIn = async (role: Role, email: string, name: string) => {
    if (!devAuth) throw new Error("Dev sign-in is disabled");
    const r = await api<{ access_token: string }>("/dev/login", { body: { email, name, role } });
    setDevToken(r.access_token);
    await load();
  };

  const setRole = async (role: Role) => {
    const u = await api<User>("/me/role", { method: "PUT", body: { role } });
    const next = { ...(user as User), ...u };
    setUser(next);
    return next;
  };

  const signOut = async () => {
    if (supabase) await supabase.auth.signOut();
    setDevToken(null);
    setPending(null);
    setUser(null);
  };

  return (
    <Ctx.Provider value={{ user, loading, error, signInWithGoogle, devSignIn, setRole, signOut, refresh: load }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}
