"use client";

import * as React from "react";
import { motion } from "framer-motion";
import {
  Bookmark,
  BookmarkCheck,
  Briefcase,
  Check,
  ExternalLink,
  MapPin,
} from "lucide-react";

import type { CandidateSummary } from "@/lib/types";
import { useSaveCandidate, useUnsaveCandidate } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScoreRing } from "@/components/score-ring";

interface CandidateCardProps {
  candidate: CandidateSummary;
  score?: number;
  matchedSkills?: string[];
  reasons?: string[];
  rank?: number;
  initiallySaved?: boolean;
  onOpenDetail: (candidateId: string) => void;
}

export function CandidateCard({
  candidate,
  score,
  matchedSkills = [],
  reasons = [],
  rank,
  initiallySaved = false,
  onOpenDetail,
}: CandidateCardProps) {
  const [saved, setSaved] = React.useState(initiallySaved);
  const save = useSaveCandidate();
  const unsave = useUnsaveCandidate();
  const matched = new Set(matchedSkills.map((s) => s.toLowerCase()));

  const toggleSave = () => {
    if (saved) {
      unsave.mutate(candidate.id);
      setSaved(false);
    } else {
      save.mutate({ candidateId: candidate.id });
      setSaved(true);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="glass group flex h-full flex-col gap-4 rounded-2xl p-5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-glow"
    >
      <div className="flex items-start gap-3">
        {rank ? (
          <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-gradient-brand text-xs font-bold text-white shadow-sm">
            {rank}
          </div>
        ) : null}
        <button
          onClick={() => onOpenDetail(candidate.id)}
          className="flex min-w-0 flex-1 cursor-pointer items-start gap-3 text-left"
        >
          <Avatar
            src={candidate.profile_picture_url}
            name={candidate.name}
            className="ring-2 ring-primary/10"
          />
          <div className="min-w-0 flex-1">
            <div className="truncate font-heading font-semibold group-hover:text-primary">
              {candidate.name}
            </div>
            <p className="truncate text-sm text-muted-foreground">
              {candidate.headline ?? candidate.current_title}
            </p>
          </div>
        </button>
        {typeof score === "number" ? <ScoreRing score={score} /> : null}
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {candidate.current_company ? (
          <span className="inline-flex items-center gap-1">
            <Briefcase className="size-3.5" />
            {candidate.current_company}
          </span>
        ) : null}
        {candidate.location ? (
          <span className="inline-flex items-center gap-1">
            <MapPin className="size-3.5" />
            {candidate.location}
          </span>
        ) : null}
        <span className="inline-flex items-center gap-1 font-medium text-foreground/70">
          {candidate.total_experience_years} yrs
        </span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {candidate.top_skills.map((skill) => (
          <Badge
            key={skill}
            variant={matched.has(skill.toLowerCase()) ? "success" : "secondary"}
            className={cn(matched.has(skill.toLowerCase()) && "gap-1")}
          >
            {matched.has(skill.toLowerCase()) ? <Check className="size-3" /> : null}
            {skill}
          </Badge>
        ))}
      </div>

      {reasons.length ? (
        <ul className="space-y-1 text-xs text-muted-foreground">
          {reasons.slice(0, 3).map((r) => (
            <li key={r} className="flex gap-1.5">
              <Check className="mt-0.5 size-3 shrink-0 text-success" />
              {r}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="mt-auto flex items-center gap-2 pt-1">
        <Button
          variant="outline"
          size="sm"
          className="flex-1"
          onClick={() => onOpenDetail(candidate.id)}
        >
          View details
        </Button>
        <a href={candidate.source_profile_url} target="_blank" rel="noreferrer">
          <Button variant="ghost" size="icon" aria-label="Open profile">
            <ExternalLink />
          </Button>
        </a>
        <Button
          variant={saved ? "secondary" : "ghost"}
          size="icon"
          aria-label={saved ? "Unsave" : "Save"}
          onClick={toggleSave}
        >
          {saved ? <BookmarkCheck className="text-primary" /> : <Bookmark />}
        </Button>
      </div>
    </motion.div>
  );
}
