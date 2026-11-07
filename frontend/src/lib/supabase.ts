import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const supabase: SupabaseClient | null = url && anon ? createClient(url, anon) : null;
/** Offline development only: sign in through the backend's /dev/login (backend DEV_AUTH=true). */
export const devAuth = !supabase && import.meta.env.VITE_DEV_AUTH === "1";
