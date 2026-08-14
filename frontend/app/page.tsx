"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  ArrowUpRight,
  Bookmark,
  CheckCircle2,
  Gauge,
  Loader2,
  Search as SearchIcon,
  Sparkles,
  TrendingUp,
  Users,
} from "lucide-react";

import { useDashboard } from "@/lib/queries";
import { cn, formatDate } from "@/lib/utils";
import type { Search } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";

const STAT_META = [
  { key: "total_searches", label: "Searches run", icon: SearchIcon, tint: "from-indigo-500 to-violet-500" },
  { key: "completed_searches", label: "Completed", icon: CheckCircle2, tint: "from-emerald-500 to-teal-500" },
  { key: "total_candidates_found", label: "Candidates found", icon: Users, tint: "from-sky-500 to-indigo-500" },
  { key: "saved_candidates", label: "Saved", icon: Bookmark, tint: "from-fuchsia-500 to-violet-500" },
] as const;

function statusVariant(status: Search["status"]) {
  switch (status) {
    case "completed":
      return "success" as const;
    case "failed":
      return "destructive" as const;
    default:
      return "default" as const;
  }
}

export default function DashboardPage() {
  const { data, isLoading } = useDashboard();

  return (
    <div className="space-y-10">
      {/* Hero */}
      <motion.section
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="glass relative overflow-hidden rounded-3xl p-8 sm:p-10"
      >
        <div className="relative z-10 max-w-2xl">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
            <Sparkles className="size-3.5" /> AI-assisted candidate matching
          </div>
          <h1 className="font-heading text-3xl font-bold leading-tight sm:text-4xl">
            Find your next hire,{" "}
            <span className="text-gradient">faster.</span>
          </h1>
          <p className="mt-3 max-w-xl text-muted-foreground">
            Describe the role once. We search, score, and rank candidates — so you
            review only the best matches, not hundreds of profiles.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/search/new">
              <Button size="lg">
                <SearchIcon className="size-4" /> New search
              </Button>
            </Link>
            <Link href="/saved">
              <Button size="lg" variant="outline">
                <Bookmark className="size-4" /> Saved candidates
              </Button>
            </Link>
          </div>
        </div>
        <div className="pointer-events-none absolute -right-10 -top-10 hidden size-64 rounded-full bg-gradient-brand opacity-20 blur-3xl md:block" />
      </motion.section>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {STAT_META.map(({ key, label, icon: Icon, tint }, i) => (
          <motion.div
            key={key}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.05 * i }}
            className="glass flex items-center gap-4 rounded-2xl p-5"
          >
            <div
              className={cn(
                "flex size-12 items-center justify-center rounded-xl bg-gradient-to-br text-white shadow-sm",
                tint,
              )}
            >
              <Icon className="size-5" />
            </div>
            <div>
              <div className="font-heading text-2xl font-bold">
                {isLoading ? <Skeleton className="h-7 w-10" /> : (data?.[key] ?? 0)}
              </div>
              <div className="text-xs text-muted-foreground">{label}</div>
            </div>
          </motion.div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Average score */}
        <div className="glass rounded-2xl p-6">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Gauge className="size-4 text-primary" /> Average match score
          </div>
          {isLoading ? (
            <Skeleton className="h-12 w-24" />
          ) : (
            <div className="font-heading text-5xl font-bold text-gradient">
              {data?.average_match_score ?? 0}
              <span className="text-2xl text-muted-foreground">%</span>
            </div>
          )}
          <p className="mt-2 text-xs text-muted-foreground">
            Across all matched candidates
          </p>
        </div>

        {/* Top skills */}
        <div className="glass rounded-2xl p-6 lg:col-span-2">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <TrendingUp className="size-4 text-primary" /> Top skills found
          </div>
          {isLoading ? (
            <div className="flex flex-wrap gap-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-7 w-16" />
              ))}
            </div>
          ) : data?.top_skills.length ? (
            <div className="flex flex-wrap gap-2">
              {data.top_skills.map((s) => (
                <Badge key={s.skill} variant="secondary" className="px-3 py-1">
                  {s.skill}
                  <span className="ml-1.5 rounded-full bg-primary/15 px-1.5 text-[10px] font-semibold text-primary">
                    {s.count}
                  </span>
                </Badge>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Run a search to see aggregated skills.
            </p>
          )}
        </div>
      </div>

      {/* Recent searches */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-heading text-lg font-semibold">Recent searches</h2>
          <Link
            href="/search/new"
            className="text-sm font-medium text-primary hover:underline"
          >
            New search
          </Link>
        </div>
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-[68px] w-full rounded-2xl" />
            ))}
          </div>
        ) : data?.recent_searches.length ? (
          <div className="space-y-2">
            {data.recent_searches.map((s) => (
              <Link key={s.id} href={`/search/${s.id}`} className="group block">
                <div className="glass flex items-center justify-between gap-4 rounded-2xl p-4 transition-all duration-200 hover:shadow-glow">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium">{s.job_title}</span>
                      <Badge variant={statusVariant(s.status)} className="capitalize">
                        {s.status === "running" || s.status === "queued" ? (
                          <Loader2 className="mr-1 size-3 animate-spin" />
                        ) : null}
                        {s.status}
                      </Badge>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {[s.location, ...(s.keywords ?? [])].filter(Boolean).join(" · ") ||
                        "No filters"}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-4">
                    <div className="text-right">
                      <div className="font-heading font-semibold">{s.result_count}</div>
                      <div className="text-xs text-muted-foreground">
                        {formatDate(s.created_at)}
                      </div>
                    </div>
                    <ArrowUpRight className="size-4 text-muted-foreground transition-transform duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-primary" />
                  </div>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={SearchIcon}
            title="No searches yet"
            description="Create your first search to start finding matching candidates."
            action={
              <Link href="/search/new">
                <Button>
                  <SearchIcon className="size-4" /> New search
                </Button>
              </Link>
            }
          />
        )}
      </div>
    </div>
  );
}
