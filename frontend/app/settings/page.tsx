"use client";

import { AlertTriangle, Gauge, MousePointer2, ShieldCheck } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">How candidate data is sourced.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="size-5 text-primary" /> Data source
            <span className="ml-auto inline-flex items-center gap-1 text-sm text-success">
              LinkedIn
            </span>
          </CardTitle>
          <CardDescription>
            Searches run in a real Chromium window driven from the server. There is
            nothing to connect here — <strong>you sign in yourself</strong> the first
            time, and the session is encrypted and reused after that. Pick{" "}
            <strong>LinkedIn</strong> as the data source when creating a search, or{" "}
            <strong>Demo data</strong> to run on fixtures with no network calls.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <div className="flex gap-3">
            <MousePointer2 className="mt-0.5 size-4 shrink-0 text-primary" />
            <p>
              <strong className="text-foreground">You drive sign-in.</strong> The app
              never types credentials. When a search needs a login or hits a CAPTCHA,
              the browser window waits for you to handle it, then carries on.
            </p>
          </div>
          <div className="flex gap-3">
            <Gauge className="mt-0.5 size-4 shrink-0 text-primary" />
            <p>
              <strong className="text-foreground">20 profiles per hour.</strong> The
              limit is a rolling window kept on disk, so it holds across searches and
              across restarts. A search that runs out stops early and keeps whatever it
              already collected.
            </p>
          </div>
          <div className="flex gap-3">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
            <p>
              <strong className="text-foreground">This breaches LinkedIn&apos;s User
              Agreement</strong> and the account you sign in with can be restricted.
              Read <code>COMPLIANCE.md</code> before running it on an account you care
              about.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
