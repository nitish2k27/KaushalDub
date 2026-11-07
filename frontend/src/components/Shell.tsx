import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AnnRequest, Role, Ticket } from "@/lib/types";
import { Icon } from "./Icon";
import { Badge, Pill } from "./ui/primitives";
import { Button } from "./ui/button";

export const ROLE: Record<Role, { n: string; i: string; home: string }> = {
  trainer: { n: "Trainer", i: "upload", home: "/t" },
  learner: { n: "Learner", i: "learn", home: "/l" },
  annotator: { n: "Annotator", i: "tag", home: "/a" },
};

export function useTrainerCounts(enabled: boolean) {
  const tickets = useQuery({ queryKey: ["tickets", "open"], queryFn: () => api<Ticket[]>("/tickets", { query: { status: "open" } }),
    enabled, refetchInterval: 30000 });
  const reqs = useQuery({ queryKey: ["annreq", "pending"], queryFn: () => api<AnnRequest[]>("/annotation-requests", { query: { status: "pending" } }),
    enabled, refetchInterval: 30000 });
  return { open: tickets.data?.length ?? 0, pending: reqs.data?.length ?? 0 };
}

function ThemeToggle() {
  const sysDark = () => window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  const [dark, setDark] = useState(() => {
    const t = document.documentElement.dataset.theme;
    return t ? t === "dark" : !!sysDark();
  });
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);
  return (
    <Button size="sm" className="theme-toggle" aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => { const d = !dark; setDark(d); try { localStorage.setItem("kd_theme", d ? "dark" : "light"); } catch { /* ignore */ } }}>
      <Icon name={dark ? "sun" : "moon"} />
    </Button>
  );
}

export function Logo({ to }: { to?: string }) {
  const nav = useNavigate();
  return (
    <button className="logo" onClick={() => to && nav(to)} aria-label="KaushalDub home">
      <b>क</b>KaushalDub
    </button>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth();
  const nav = useNavigate();
  const role = user!.role;
  const { open, pending } = useTrainerCounts(role === "trainer");
  const tabs: Record<Role, [string, ReactNode][]> = {
    trainer: [["/t", "My videos"], ["/t/reports", <>Learner reports<Badge n={open} /></>],
      ["/t/annotations", <>Annotation requests<Badge n={pending} /></>], ["/t/settings", "API keys & plan"]],
    learner: [["/l", "Library"], ["/l/progress", "My progress"]],
    annotator: [["/a", "Queue"], ["/a/history", "My labels"]],
  };
  const budget = user!.budget;
  return (
    <div className="wrap">
      <header className="top">
        <Logo to={ROLE[role].home} />
        <Pill><Icon name={ROLE[role].i} />{ROLE[role].n}</Pill>
        <span className="grow" />
        <ThemeToggle />
        <Button size="sm" onClick={() => nav("/?switch=1")}><Icon name="swap" />Switch role</Button>
        <span className="row" style={{ gap: 8 }}>
          {user!.avatar_url ? <img src={user!.avatar_url} alt="" className="avatar" referrerPolicy="no-referrer" />
            : <span className="avatar" aria-hidden="true">{(user!.name || "?")[0].toUpperCase()}</span>}
          <span className="small"><b>{user!.name}</b><br /><span className="muted tiny">{user!.email}</span></span>
        </span>
        <Button size="sm" aria-label="Sign out" onClick={async () => { await signOut(); nav("/"); }}><Icon name="out" /></Button>
      </header>
      <nav className="nav" aria-label="Sections">
        {tabs[role].map(([to, label]) => (
          <NavLink key={to} to={to} end={to.length <= 2}
            className={({ isActive }) => (isActive ? "on" : "")}>
            {label}
          </NavLink>
        ))}
      </nav>
      {budget?.low && (
        <div className="banner" style={{ marginBottom: 16 }} role="alert">
          <Icon name="flag" />
          <span className="grow small"><b>Admin: platform budget {budget.exhausted ? "used up" : "running low"}.</b> ₹{budget.spent_inr} of ₹{budget.budget_inr} spent this month on free-trial jobs.</span>
        </div>
      )}
      <main>{children}</main>
      <p className="tiny muted" style={{ padding: "32px 0 24px" }}>
        KaushalDub · RV University CS3235 coursework. Narration and captions are machine-made and reviewed by the trainer; check safety-critical steps with a qualified instructor.
      </p>
    </div>
  );
}
