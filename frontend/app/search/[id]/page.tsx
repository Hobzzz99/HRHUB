"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Clock, Download, Frown, Users } from "lucide-react";

import { api } from "@/lib/api";
import { queryKeys, useSaved, useSearchResults } from "@/lib/queries";
import { useSearchStream } from "@/lib/use-search-stream";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CandidateCard } from "@/components/candidate-card";
import { CandidateDetail } from "@/components/candidate-detail";
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
      />

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
        ) : (
          <EmptyState
            icon={Users}
            title="No candidates matched"
            description="Try lowering the minimum score or experience, removing critical skills, or using broader keywords."
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
