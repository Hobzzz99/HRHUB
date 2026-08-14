"use client";

import { CheckCircle2, Clock, Loader2, ShieldAlert, XCircle } from "lucide-react";

import type { SearchProgress as Progress, SearchStatus } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";

interface SearchProgressProps {
  status: SearchStatus;
  progress: Progress;
  error?: string | null;
}

const STAGES: { key: keyof Progress; label: string }[] = [
  { key: "found", label: "Profiles found" },
  { key: "to_process", label: "To review" },
  { key: "processed", label: "Reviewed" },
  { key: "kept", label: "Matches kept" },
];

/** "25 minutes" / "45 seconds" — the wait is what the reader actually needs. */
function humanizeSeconds(seconds: number): string {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} seconds`;
  const minutes = Math.round(seconds / 60);
  return `${minutes} minute${minutes === 1 ? "" : "s"}`;
}

export function SearchProgress({ status, progress, error }: SearchProgressProps) {
  const pct =
    progress.to_process && progress.to_process > 0
      ? Math.round(((progress.processed ?? 0) / progress.to_process) * 100)
      : status === "completed"
        ? 100
        : 5;

  const { budget_limit: limit, budget_remaining: remaining } = progress;
  // Only meaningful for scraping providers, which are the only ones with a budget.
  const showBudget = typeof limit === "number" && typeof remaining === "number";

  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <div className="flex items-center gap-2">
          {status === "completed" ? (
            <CheckCircle2 className="size-5 text-success" />
          ) : status === "failed" ? (
            <XCircle className="size-5 text-destructive" />
          ) : (
            <Loader2 className="size-5 animate-spin text-primary" />
          )}
          <span className="font-medium capitalize">{status}</span>
          {showBudget ? (
            <span className="ml-auto text-xs text-muted-foreground">
              Hourly budget: {remaining} of {limit} left
            </span>
          ) : null}
        </div>

        <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {STAGES.map(({ key, label }) => (
            <div key={key} className="rounded-md bg-secondary/50 p-3 text-center">
              <div className="text-2xl font-semibold">{progress[key] ?? 0}</div>
              <div className="text-xs text-muted-foreground">{label}</div>
            </div>
          ))}
        </div>

        {/* Without these the run reads as "found nothing", when in fact it was
            stopped by a safety control and the criteria were never the problem. */}
        {progress.rate_limited ? (
          <div className="flex gap-3 rounded-md border border-primary/40 bg-primary/5 p-3 text-sm">
            <Clock className="mt-0.5 size-4 shrink-0 text-primary" />
            <div>
              <p className="font-medium text-foreground">
                Stopped early — hourly scrape limit reached
              </p>
              <p className="text-muted-foreground">
                The cap is {limit ?? 20} profiles per rolling hour, and it was already
                spent when this search ran.{" "}
                {progress.retry_after_s
                  ? `The next profile slot frees up in about ${humanizeSeconds(progress.retry_after_s)}.`
                  : ""}{" "}
                Anything collected before the limit was reached is kept — re-run this
                search later and it will carry on from where it stopped.
              </p>
              <p className="mt-1 text-muted-foreground">
                Changing the score threshold or skills will not help here.
              </p>
            </div>
          </div>
        ) : null}

        {progress.account_restricted ? (
          <div className="flex gap-3 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
            <ShieldAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
            <div>
              <p className="font-medium text-foreground">
                Stopped — the LinkedIn account was restricted
              </p>
              <p className="text-muted-foreground">
                The run halted and the account was locked out so nothing can reach it
                again. Connect a different account in Settings to continue.
              </p>
            </div>
          </div>
        ) : null}

        {/* Recruiters plan around this: a scrape-backed run is minutes, not
            seconds, and the per-profile figure is what makes a bigger search
            predictable. */}
        {typeof progress.elapsed_seconds === "number" ? (
          <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-border pt-3 text-xs text-muted-foreground">
            <span>
              Total time{" "}
              <strong className="text-foreground">
                {humanizeSeconds(progress.elapsed_seconds)}
              </strong>
            </span>
            {typeof progress.search_seconds === "number" ? (
              <span>
                Finding profiles {humanizeSeconds(progress.search_seconds)}
              </span>
            ) : null}
            {typeof progress.seconds_per_profile === "number" ? (
              <span>
                {humanizeSeconds(progress.seconds_per_profile)} per profile
              </span>
            ) : null}
          </div>
        ) : null}

        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </CardContent>
    </Card>
  );
}
