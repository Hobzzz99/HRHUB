"use client";

import * as React from "react";
import { AlertTriangle, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * Catches a render error anywhere in the app.
 *
 * Without this Next.js shows a blank page in production, which a recruiter
 * reads as the tool being gone. Nothing here explains the fault — the message
 * is an internal one and would only alarm — but it says the app is at fault
 * rather than their search, and offers the one action that usually works.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    // The digest is the only handle on the server-side trace, so it goes to the
    // console rather than on screen.
    console.error("Unhandled UI error", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <span className="flex size-12 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
        <AlertTriangle className="size-6" />
      </span>
      <div className="space-y-1">
        <h1 className="text-lg font-semibold">Something went wrong in the app</h1>
        <p className="max-w-md text-sm text-muted-foreground">
          This is a fault on our side, not a problem with your search. Any search
          already running carries on — its results will be waiting when you come
          back.
        </p>
      </div>
      <Button onClick={reset} variant="outline">
        <RotateCw className="size-4" /> Try again
      </Button>
      {error.digest ? (
        <p className="text-xs text-muted-foreground">Reference: {error.digest}</p>
      ) : null}
    </div>
  );
}
