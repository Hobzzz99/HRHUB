"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Gauge,
  Loader2,
  MousePointer2,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

import { useProviderAccount, useRotateProviderAccount } from "@/lib/queries";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

function AccountStatus({ provider, label, note }: {
  provider: string;
  label: string;
  note: string;
}) {
  const { data: account, isLoading } = useProviderAccount(provider);
  const rotate = useRotateProviderAccount(provider);
  const [confirming, setConfirming] = useState(false);

  if (isLoading) return <Skeleton className="h-24 w-full" />;

  const restricted = account?.status === "restricted";
  const burned = account?.retired_count ?? 0;

  return (
    <Card className={restricted ? "border-destructive" : undefined}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-5 text-primary" /> {label} account
          <span
            className={`ml-auto rounded-full px-2.5 py-0.5 text-xs font-medium ${
              restricted
                ? "bg-destructive/10 text-destructive"
                : account?.has_session
                  ? "bg-success/10 text-success"
                  : "bg-muted text-muted-foreground"
            }`}
          >
            {restricted
              ? "Restricted"
              : account?.has_session
                ? "Signed in"
                : "Not signed in yet"}
          </span>
        </CardTitle>
        <CardDescription>
          {restricted ? (
            <>
              {label} has locked this account and searches will refuse to run on
              it. Clearing a restriction is done with {label} directly — no setting
              here can undo it.
            </>
          ) : account?.has_session ? (
            <>
              A signed-in session is stored and encrypted. Searches reuse it, so you
              should not be asked to log in again.
            </>
          ) : (
            <>
              No session stored yet. {note} The first {label} search opens a
              browser window and waits for you to sign in.
            </>
          )}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4 text-sm">
        {account?.status_reason ? (
          <p className="rounded-md bg-destructive/5 p-3 text-destructive">
            {account.status_reason}
          </p>
        ) : null}

        {burned > 0 ? (
          <p className="text-muted-foreground">
            <strong className="text-foreground">
              {burned} account{burned === 1 ? "" : "s"} already retired
            </strong>{" "}
            on this provider. Each replacement is more likely to be linked to the last
            — every request still comes from this machine&apos;s IP address, which no
            amount of rotation changes.
          </p>
        ) : null}

        {confirming ? (
          <div className="space-y-3 rounded-md border border-destructive/40 bg-destructive/5 p-3">
            <p className="text-foreground">
              Retire this account and connect a different one? The stored session is
              deleted and the next {label} search will open a sign-in window.
            </p>
            <p className="text-muted-foreground">
              This does <strong>not</strong> unlock the restricted account, and it does
              not make the next one safe. Use an account you are prepared to lose.
            </p>
            <div className="flex gap-2">
              <Button
                variant="destructive"
                size="sm"
                disabled={rotate.isPending}
                onClick={() =>
                  rotate.mutate(undefined, { onSuccess: () => setConfirming(false) })
                }
              >
                {rotate.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <RotateCcw className="size-4" />
                )}
                Retire and switch
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setConfirming(false)}
                disabled={rotate.isPending}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <Button
            variant={restricted ? "default" : "outline"}
            size="sm"
            onClick={() => setConfirming(true)}
          >
            <RotateCcw className="size-4" />
            Connect a different account
          </Button>
        )}

        {rotate.isError ? (
          <p className="text-destructive">
            Could not switch accounts. Is the API running?
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">How candidate data is sourced.</p>
      </div>

      <AccountStatus
        provider="linkedin"
        label="LinkedIn"
        note="Any signed-in member account can search profiles."
      />
      <AccountStatus
        provider="indeed"
        label="Indeed"
        note="Needs an employer account with an active Resume subscription — a job-seeker login cannot search resumes."
      />

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
