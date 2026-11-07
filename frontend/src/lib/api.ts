import { supabase } from "./supabase";

export const API_URL = ((import.meta.env.VITE_API_URL as string) || "http://localhost:8000").replace(/\/$/, "");
const DEV_TOKEN = "kd_dev_token";

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function token(): Promise<string | null> {
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    return data.session?.access_token ?? null;
  }
  try {
    return localStorage.getItem(DEV_TOKEN);
  } catch {
    return null;
  }
}

export function setDevToken(t: string | null) {
  try {
    if (t) localStorage.setItem(DEV_TOKEN, t);
    else localStorage.removeItem(DEV_TOKEN);
  } catch {
    /* private mode: stays signed in for this tab only */
  }
}

type Opts = { method?: string; body?: unknown; form?: FormData; query?: Record<string, string | number | undefined | null> };

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const t = await token();
  const q = opts.query
    ? Object.entries(opts.query).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => [k, String(v)])
    : [];
  const qs = q.length ? "?" + new URLSearchParams(q).toString() : "";
  const headers: Record<string, string> = {};
  if (t) headers.Authorization = `Bearer ${t}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let r: Response;
  try {
    r = await fetch(API_URL + path + qs, {
      method: opts.method || (opts.body !== undefined || opts.form ? "POST" : "GET"),
      headers,
      body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the KaushalDub server. Check your connection.");
  }
  const text = await r.text();
  let data: any = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!r.ok) {
    const d = data?.detail;
    const msg = typeof d === "string" ? d
      : d?.message || (Array.isArray(d) ? d.map((x: { msg: string }) => x.msg).join("; ") : `Request failed (${r.status})`);
    throw new ApiError(r.status, msg, d && typeof d === "object" && !Array.isArray(d) ? d.code : undefined);
  }
  return data as T;
}
