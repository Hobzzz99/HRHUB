"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { AUTH_DISABLED, getSupabaseBrowserClient } from "@/lib/supabase";

const LOGIN_PATH = "/login";

/**
 * Sends signed-out visitors to the login page, and signed-in ones away from it.
 *
 * Without this the app had a login page that nothing ever routed to: an
 * unauthenticated recruiter landed on the dashboard, every request came back
 * 401, and they saw a broken page with no way to sign in short of typing
 * /login by hand.
 *
 * The check runs in the browser because the session lives in the Supabase
 * client, not on our server. That means a brief unresolved state on first
 * paint, which is what `checking` covers — rendering children during it would
 * flash the dashboard at someone who is not allowed to see it.
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [allowed, setAllowed] = React.useState(AUTH_DISABLED);
  const [checking, setChecking] = React.useState(!AUTH_DISABLED);

  React.useEffect(() => {
    if (AUTH_DISABLED) return;

    const supabase = getSupabaseBrowserClient();
    if (!supabase) {
      // Auth is on but Supabase is not configured. Failing closed is the only
      // safe reading: the alternative shows candidate data to anyone.
      setChecking(false);
      setAllowed(false);
      return;
    }

    let active = true;

    const settle = (signedIn: boolean) => {
      if (!active) return;
      const onLogin = pathname === LOGIN_PATH;
      if (!signedIn && !onLogin) router.replace(LOGIN_PATH);
      if (signedIn && onLogin) router.replace("/");
      setAllowed(signedIn || onLogin);
      setChecking(false);
    };

    supabase.auth.getSession().then(({ data }) => settle(!!data.session));

    // Keeps other tabs and token expiry in step with this one.
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) =>
      settle(!!session),
    );

    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, [pathname, router]);

  if (checking) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!allowed) return null;

  return <>{children}</>;
}
