"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";

import { AUTH_DISABLED, getSupabaseBrowserClient } from "@/lib/supabase";

/**
 * Signs the current recruiter out.
 *
 * Needed because these are shared company laptops: without it the only way to
 * leave a session is to clear browser storage, so whoever sits down next is
 * still signed in as the previous person — and searches they start would run
 * against that person's LinkedIn account.
 *
 * Renders nothing when auth is disabled, where there is no session to end.
 */
export function SignOutButton() {
  const router = useRouter();
  const [busy, setBusy] = React.useState(false);

  if (AUTH_DISABLED) return null;

  const signOut = async () => {
    const supabase = getSupabaseBrowserClient();
    if (!supabase) return;
    setBusy(true);
    await supabase.auth.signOut();
    // replace, not push: the back button must not return to a signed-in view.
    router.replace("/login");
  };

  return (
    <button
      type="button"
      onClick={signOut}
      disabled={busy}
      title="Sign out"
      aria-label="Sign out"
      className="flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium text-muted-foreground transition-colors duration-200 hover:bg-accent hover:text-foreground disabled:opacity-50"
    >
      <LogOut className="size-4" />
      <span className="hidden md:inline">Sign out</span>
    </button>
  );
}
