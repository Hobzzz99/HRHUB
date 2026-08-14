"use client";

import { AlertTriangle } from "lucide-react";

/**
 * Says out loud what the entered critical skills will actually require.
 *
 * Separate entries are **and**-ed: three chips means a candidate must hold all
 * three. That is right for skills and wrong for qualifications, where the same
 * credential has different names by country — and a recruiter typing
 * CPA, ACCA, ESAA plainly means "any of these". Entered as three chips it
 * rejected every candidate, including audit managers at EY and KPMG, and the
 * screen simply said nobody matched.
 *
 * Nothing here changes the filter. It shows the recruiter the logic they have
 * built, in the words they used, before they spend an hour of scrape budget
 * discovering it.
 */
export function CriticalSkillsExplainer({ terms }: { terms: string[] }) {
  const entries = terms.filter((t) => t.trim());
  if (entries.length === 0) return null;

  // One entry may itself list alternatives — the backend splits on / | or.
  const describe = (term: string) => {
    const options = term.split(/\s*[/|]\s*|\s+or\s+/i).filter(Boolean);
    return options.length > 1 ? `(${options.join(" or ")})` : term;
  };

  const requiresAll = entries.length > 1;

  return (
    <div className="mt-2 space-y-1 text-xs">
      <p className="text-muted-foreground">
        Requires:{" "}
        <span className="font-medium text-foreground">
          {entries.map(describe).join(" and ")}
        </span>
      </p>
      {requiresAll ? (
        <p className="flex gap-1.5 text-destructive">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>
            A candidate must have <strong>every one</strong> of these. If you meant
            any of them, put them in a single entry separated by <code>/</code> —
            for example <code>CPA / ACCA / ESAA</code>.
          </span>
        </p>
      ) : null}
    </div>
  );
}
