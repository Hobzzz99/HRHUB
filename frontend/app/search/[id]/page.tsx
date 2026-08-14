"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Clock, Download, Frown, Users } from "lucide-react";

import { api } from "@/lib/api";
import { queryKeys, useSaved, useSearchResults } from "@/lib/queries";
import { useSearchStream } from "@/lib/use-search-stream";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CandidateCard } from "@/components/candidate-card";
import { CandidateDetail } from "@/components/candidate-detail";
import { DegradedNotice } from "@/components/degraded-notice";
import { EmptyState } from "@/components/empty-state";
import { SearchProgress } from "@/components/search-progress";

export default function SearchResultsPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [selected, setSelected] = React.useState<string | null>(null);

  const metaQuery = useQuery({
    queryKey: queryKeys.search(id),
    queryFn: () => api.getSearch(id),
  });
  const stream = useSearchStream(id, metaQuery.data?.status ?? "queued");
  const completed = stream.status === "completed";

  const resultsQuery = useSearchResults(id, completed);
  const savedQuery = useSaved();
  const savedIds = new Set((savedQuery.data ?? []).map((s) => s.candidate.id));

  const search = metaQuery.data;
  const degraded = search?.degraded_reasons ?? [];

  // "10 reviewed, 8 of them work at a different employer" tells a recruiter
  // which filter to loosen. "Try lowering the minimum score" makes them guess.
  const rejected = stream.progress.rejected;
  const reasons = stream.progress.rejection_reasons;
  const rejectionSummary =
    rejected && reasons?.length
      ? `${rejected} ${rejected === 1 ? "profile was" : "profiles were"} reviewed and filtered out — ${reasons.join(", ")}.`
      : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          {search ? (
            <>
              <h1 className="text-2xl font-bold tracking-tight">{search.job_title}</h1>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                {search.location ? <span>{search.location}</span> : null}
                {search.min_experience > 0 ? (
                  <span>· {search.min_experience}+ yrs</span>
                ) : null}
                <Badge variant="outline">provider: {search.provider}</Badge>
              </div>
            </>
          ) : (
            <Skeleton className="h-8 w-56" />
          )}
        </div>
        {completed && (resultsQuery.data?.length ?? 0) > 0 ? (
          <a href={api.exportUrl(id, "csv")}>
            <Button variant="outline">
              <Download className="size-4" /> Export CSV
            </Button>
          </a>
        ) : null}
      </div>

      <SearchProgress
        status={stream.status}
        progress={stream.progress}
        error={stream.error}
        degraded={degraded.length > 0}
      />

      {/* Above the results, not below: a shortlist that was never filtered the
          way it was asked to be looks entirely convincing on its own. */}
      <DegradedNotice reasons={degraded} />

      {completed ? (
        resultsQuery.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-64 w-full" />
            ))}
          </div>
        ) : resultsQuery.data?.length ? (
          <>
            <p className="text-sm text-muted-foreground">
              {resultsQuery.data.length} matching candidate
              {resultsQuery.data.length === 1 ? "" : "s"}, ranked by match score.
            </p>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {resultsQuery.data.map((r) => (
                <CandidateCard
                  key={r.id}
                  candidate={r.candidate}
                  score={r.match_score}
                  matchedKeywords={r.matched_keywords}
                  reasons={r.reasons}
                  rank={r.rank}
                  initiallySaved={savedIds.has(r.candidate.id)}
                  onOpenDetail={setSelected}
                />
              ))}
            </div>
          </>
        ) : stream.progress.rate_limited ? (
          // Zero results because the run was cut short, not because nothing fit.
          // Telling the recruiter to loosen their criteria here would send them
          // rewriting a search that was never the problem.
          <EmptyState
            icon={Clock}
            title="Stopped before any profile was opened"
            description="The hourly scrape limit was already spent when this search ran, so no profiles could be fetched. Re-run it once the budget frees up — your criteria are not the issue."
          />
        ) : degraded.length > 0 ? (
          // Something the search was asked to do did not happen, so an empty
          // list says nothing about the market. Telling the recruiter to
          // loosen their criteria here would send them rewriting a search that
          // was never the problem — which is exactly what used to happen.
          <EmptyState
            icon={AlertTriangle}
            title="This search could not be completed properly"
            description={degraded.map((d) => d.detail).join(" ")}
          />
        ) : (
          <EmptyState
            icon={Users}
            title="No candidates matched"
            description={
              rejectionSummary ??
              "Try lowering the minimum score or experience, removing critical skills, or using broader keywords."
            }
          />
        )
      ) : stream.status === "failed" ? (
        <EmptyState
          icon={Frown}
          title="Search failed"
          description={stream.error ?? "Something went wrong running this search."}
        />
      ) : null}

      <CandidateDetail candidateId={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
