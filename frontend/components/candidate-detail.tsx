"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, X } from "lucide-react";

import { useCandidate } from "@/lib/queries";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

interface CandidateDetailProps {
  candidateId: string | null;
  onClose: () => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </div>
  );
}

export function CandidateDetail({ candidateId, onClose }: CandidateDetailProps) {
  const { data: candidate, isLoading } = useCandidate(candidateId);
  const open = !!candidateId;

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-50 bg-black/50"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className="fixed inset-y-0 right-0 z-50 w-full max-w-lg overflow-y-auto border-l border-border bg-background shadow-xl"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
          >
            <div className="sticky top-0 flex items-center justify-between border-b border-border bg-background/90 px-6 py-4 backdrop-blur">
              <h2 className="font-semibold">Candidate profile</h2>
              <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
                <X />
              </Button>
            </div>

            <div className="space-y-6 p-6">
              {isLoading || !candidate ? (
                <div className="space-y-4">
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-24 w-full" />
                  <Skeleton className="h-24 w-full" />
                </div>
              ) : (
                <>
                  <div className="flex items-start gap-4">
                    <Avatar
                      src={candidate.profile_picture_url}
                      name={candidate.name}
                      className="size-16"
                    />
                    <div className="min-w-0 flex-1">
                      <h1 className="text-lg font-semibold">{candidate.name}</h1>
                      <p className="text-sm text-muted-foreground">
                        {candidate.headline ?? candidate.current_title}
                      </p>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {candidate.current_company}
                        {candidate.location ? ` · ${candidate.location}` : ""}
                      </p>
                      <p className="mt-1 text-sm font-medium">
                        {candidate.total_experience_years} years of experience
                      </p>
                    </div>
                  </div>

                  <a
                    href={candidate.source_profile_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Button variant="outline" size="sm" className="w-full">
                      <ExternalLink className="size-4" /> View original profile
                    </Button>
                  </a>

                  {candidate.about && (
                    <Section title="About">
                      <p className="text-sm leading-relaxed text-foreground/90">
                        {candidate.about}
                      </p>
                    </Section>
                  )}

                  {candidate.skills.length > 0 && (
                    <Section title="Skills">
                      <div className="flex flex-wrap gap-1.5">
                        {candidate.skills.map((s) => (
                          <Badge key={s} variant="secondary">
                            {s}
                          </Badge>
                        ))}
                      </div>
                    </Section>
                  )}

                  {candidate.experience.length > 0 && (
                    <Section title="Experience">
                      <div className="space-y-3">
                        {candidate.experience.map((exp, i) => (
                          <div key={i} className="border-l-2 border-border pl-3">
                            <p className="text-sm font-medium">{exp.title}</p>
                            <p className="text-sm text-muted-foreground">
                              {exp.company}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {exp.start ?? "?"} – {exp.end ?? "Present"}
                            </p>
                          </div>
                        ))}
                      </div>
                    </Section>
                  )}

                  {candidate.education.length > 0 && (
                    <Section title="Education">
                      <div className="space-y-2">
                        {candidate.education.map((ed, i) => (
                          <div key={i}>
                            <p className="text-sm font-medium">{ed.school}</p>
                            <p className="text-sm text-muted-foreground">
                              {[ed.degree, ed.field].filter(Boolean).join(", ")}
                            </p>
                          </div>
                        ))}
                      </div>
                    </Section>
                  )}

                  {candidate.certifications.length > 0 && (
                    <Section title="Certifications">
                      <ul className="list-inside list-disc text-sm text-foreground/90">
                        {candidate.certifications.map((c, i) => (
                          <li key={i}>{(c as { name?: string }).name ?? "Certification"}</li>
                        ))}
                      </ul>
                    </Section>
                  )}

                  {candidate.languages.length > 0 && (
                    <Section title="Languages">
                      <div className="flex flex-wrap gap-1.5">
                        {candidate.languages.map((l) => (
                          <Badge key={l} variant="outline">
                            {l}
                          </Badge>
                        ))}
                      </div>
                    </Section>
                  )}
                </>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
