import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { devAuth, supabase } from "@/lib/supabase";
import type { Role } from "@/lib/types";
import { ROLE, Logo } from "@/components/Shell";
import { Button } from "@/components/ui/button";
import { ErrorBox, Input, Label } from "@/components/ui/primitives";

export default function Login() {
  const [params] = useSearchParams();
  const role = ((params.get("role") as Role) || "learner") as Role;
  const next = params.get("next");
  const { user, loading, signInWithGoogle, devSignIn, setRole, error } = useAuth();
  const nav = useNavigate();
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState(`${role}@example.com`);
  const [name, setName] = useState(role === "learner" ? "Asha" : role === "trainer" ? "Nitish" : "Ravi");

  useEffect(() => {
    if (loading || !user) return;
    (async () => {
      if (user.role !== role) await setRole(role).catch(() => {});
      nav(next && next.startsWith(ROLE[role].home) ? next : ROLE[role].home, { replace: true });
    })();
  }, [loading, user, role, next, nav, setRole]);

  const google = async () => {
    setBusy(true);
    setErr(null);
    try {
      await signInWithGoogle(role);
    } catch (e) {
      setErr(e);
      setBusy(false);
    }
  };

  return (
    <div className="wrap">
      <div className="login card">
        <div className="logo" style={{ justifyContent: "center" }}><Logo /></div>
        <h2 style={{ marginTop: 18 }}>Sign in as {ROLE[role].n.toLowerCase()}</h2>
        <p className="muted small" style={{ marginTop: 6 }}>Use your Google account. We only read your name, email and picture.</p>
        <ErrorBox error={err || error} />
        {supabase && (
          <button className="gbtn" onClick={google} disabled={busy}>
            <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true">
              <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.4-.4-3.5z" />
              <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
              <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
              <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.2-.1-2.4-.4-3.5z" />
            </svg>
            {busy ? "Opening Google…" : "Continue with Google"}
          </button>
        )}
        {devAuth && (
          <form className="stack" style={{ marginTop: 18, textAlign: "left", gap: 10 }}
            onSubmit={async (e) => { e.preventDefault(); setBusy(true); try { await devSignIn(role, email, name); } catch (x) { setErr(x); } setBusy(false); }}>
            <p className="tiny" style={{ color: "var(--accent)" }}>Local development sign-in (DEV_AUTH). Not available in production.</p>
            <div><Label htmlFor="dn">Name</Label><Input id="dn" value={name} onChange={(e) => setName(e.target.value)} required /></div>
            <div><Label htmlFor="de">Email</Label><Input id="de" type="text" value={email} onChange={(e) => setEmail(e.target.value)} required /></div>
            <Button type="submit" variant="primary" disabled={busy}>Sign in</Button>
          </form>
        )}
        {!supabase && !devAuth && <ErrorBox error="Sign-in is not configured: set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY." />}
        <Button size="sm" style={{ marginTop: 18 }} onClick={() => nav("/")}>Back</Button>
      </div>
    </div>
  );
}
