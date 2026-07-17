"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Loader2, Users } from "lucide-react";

import { AUTH_DISABLED, getSupabaseBrowserClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);

  const signIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const supabase = getSupabaseBrowserClient();
    if (!supabase) {
      setError("Supabase is not configured.");
      return;
    }
    setLoading(true);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) setError(error.message);
    else router.push("/");
  };

  return (
    <div className="mx-auto flex max-w-sm flex-col items-center gap-6 py-12">
      <div className="flex flex-col items-center gap-2 text-center">
        <span className="flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <Users className="size-6" />
        </span>
        <h1 className="text-2xl font-bold">TalentFinder</h1>
        <p className="text-sm text-muted-foreground">Sign in to search for candidates.</p>
      </div>

      {AUTH_DISABLED ? (
        <Card className="w-full">
          <CardContent className="space-y-4 p-6 text-center">
            <p className="text-sm text-muted-foreground">
              Authentication is disabled in development mode. You&apos;re signed in as the
              dev user.
            </p>
            <Button className="w-full" onClick={() => router.push("/")}>
              Continue to dashboard
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card className="w-full">
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={signIn} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
              {error ? <p className="text-sm text-destructive">{error}</p> : null}
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? <Loader2 className="animate-spin" /> : null} Sign in
              </Button>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
