"use client";

import { AlertTriangle } from "lucide-react";

import type { Degradation } from "@/lib/types";

/**
 * Says what a search could not do, above the results it still returned.
 *
 * This exists because the most damaging failure in this app is not a crash —
 * it is a search that quietly answers a different question. When LinkedIn's
 * company filter cannot be driven, the run continues *unfiltered*: real
 * candidates come back, ranked and plausible, and none of them are restricted
 * to the firms the recruiter asked for.
 *
 * A recruiter who is told that keeps trusting the tool. One who is not will
 * either act on the wrong shortlist or conclude the filter does not work.
 */
export function DegradedNotice({ reasons }: { reasons: Degradation[] }) {
  if (reasons.length === 0) return null;

  // `destructive`, matching the account-restricted banner. The theme has no
  // warning colour, and this is not a lesser problem than a restriction — it is
  // the one that looks like everything worked.
  return (
    <div
      role="status"
      className="flex gap-3 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
      <div>
        <p className="font-medium text-foreground">
          These results are not what you asked for
        </p>
        {reasons.map((reason, i) => (
          <p key={i} className="text-muted-foreground">
            {reason.detail}
          </p>
        ))}
      </div>
    </div>
  );
}
