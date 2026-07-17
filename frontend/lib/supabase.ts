import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

/**
 * When AUTH is disabled (local dev), the backend injects a dev user and no token
 * is required. In that mode we never initialise Supabase.
 */
export const AUTH_DISABLED = process.env.NEXT_PUBLIC_AUTH_DISABLED === "true";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

let client: SupabaseClient | null = null;

export function getSupabaseBrowserClient(): SupabaseClient | null {
  if (AUTH_DISABLED || !url || !anonKey) return null;
  if (!client) client = createBrowserClient(url, anonKey);
  return client;
}

export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
