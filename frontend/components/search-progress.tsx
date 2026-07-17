"use client";

import { CheckCircle2, Loader2, XCircle } from "lucide-react";

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

export function SearchProgress({ status, progress, error }: SearchProgressProps) {
  const pct =
    progress.to_process && progress.to_process > 0
      ? Math.round(((progress.processed ?? 0) / progress.to_process) * 100)
      : status === "completed"
        ? 100
        : 5;

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

        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </CardContent>
    </Card>
  );
}
