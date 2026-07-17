"use client";

import * as React from "react";
import Link from "next/link";
import { Bookmark, Search as SearchIcon } from "lucide-react";

import { useSaved } from "@/lib/queries";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CandidateCard } from "@/components/candidate-card";
import { CandidateDetail } from "@/components/candidate-detail";
import { EmptyState } from "@/components/empty-state";

export default function SavedPage() {
  const { data, isLoading } = useSaved();
  const [selected, setSelected] = React.useState<string | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Saved candidates</h1>
        <p className="text-muted-foreground">Candidates you&apos;ve bookmarked.</p>
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-56 w-full" />
          ))}
        </div>
      ) : data?.length ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((s) => (
            <CandidateCard
              key={s.id}
              candidate={s.candidate}
              initiallySaved
              onOpenDetail={setSelected}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Bookmark}
          title="No saved candidates"
          description="Save candidates from a search to keep track of them here."
          action={
            <Link href="/search/new">
              <Button>
                <SearchIcon className="size-4" /> Start a search
              </Button>
            </Link>
          }
        />
      )}

      <CandidateDetail candidateId={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
