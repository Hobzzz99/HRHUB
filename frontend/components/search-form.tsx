"use client";

import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { Loader2, Search } from "lucide-react";
import { z } from "zod";

import { useCreateSearch } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { TagInput } from "@/components/ui/tag-input";

/** Kept in step with BIG_FOUR in the backend's domain/companies.py. */
const BIG_FOUR = ["Deloitte", "PwC", "EY", "KPMG"] as const;

/**
 * Pull LinkedIn's company ids out of a search URL, e.g.
 * `?currentCompany=%5B"9499295"%2C"1073"%5D` -> ["9499295", "1073"].
 * Used when the filter panel cannot be driven — LinkedIn has already resolved
 * these, so they cannot pick the wrong company entity.
 */
function companyIdsFromUrl(url: string): string[] {
  const match = /currentCompany=([^&]+)/.exec(url);
  if (!match) return [];
  return decodeURIComponent(match[1]).match(/\d+/g) ?? [];
}

const schema = z.object({
  job_title: z.string().min(1, "Job title is required"),
  keywords: z.array(z.string()),
  critical_skills: z.array(z.string()),
  location: z.string(),
  min_experience: z.coerce.number().min(0).max(50),
  require_title_match: z.boolean(),
  graduation_year_from: z.string(),
  graduation_year_to: z.string(),
  companies: z.array(z.string()),
  company_ids: z.array(z.string()),
  industry: z.string(),
  max_results: z.coerce.number().min(1).max(200),
  min_match_score: z.coerce.number().min(0).max(100),
  enforce_location: z.boolean(),
  provider: z.enum(["mock", "linkedin", "indeed"]),
});

type FormValues = z.infer<typeof schema>;

const defaults: FormValues = {
  job_title: "",
  keywords: [],
  critical_skills: [],
  location: "",
  min_experience: 0,
  require_title_match: true,
  graduation_year_from: "",
  graduation_year_to: "",
  companies: [],
  company_ids: [],
  industry: "",
  max_results: 25,
  min_match_score: 40,
  enforce_location: false,
  provider: "mock",
};

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function SearchForm() {
  const router = useRouter();
  const createSearch = useCreateSearch();
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: defaults });

  const onSubmit = handleSubmit(async (values) => {
    const search = await createSearch.mutateAsync({
      ...values,
      location: values.location || null,
      graduation_year_from: values.graduation_year_from
        ? Number(values.graduation_year_from)
        : null,
      graduation_year_to: values.graduation_year_to
        ? Number(values.graduation_year_to)
        : null,
      industry: values.industry || null,
    });
    router.push(`/search/${search.id}`);
  });

  return (
    <div className="glass rounded-3xl p-6 sm:p-8">
      <form onSubmit={onSubmit} className="space-y-5">
          <Field
            label="Data source"
            hint="LinkedIn and Indeed each open a real browser window on the server — you sign in yourself, and each platform has its own 20-per-hour cap and its own stored session. Indeed needs an employer account with a Resume subscription. Demo data runs on fixtures, no network."
          >
            <Controller
              control={control}
              name="provider"
              render={({ field }) => (
                <div className="grid grid-cols-3 gap-2">
                  {(
                    [
                      { value: "mock", label: "Demo data", sub: "safe, instant" },
                      { value: "linkedin", label: "LinkedIn", sub: "manual sign-in, 20/hr" },
                      { value: "indeed", label: "Indeed", sub: "employer account, 20/hr" },
                    ] as const
                  ).map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => field.onChange(opt.value)}
                      className={cn(
                        "rounded-md border p-3 text-left text-sm transition-colors",
                        field.value === opt.value
                          ? "border-primary bg-primary/5 ring-1 ring-primary"
                          : "border-border hover:bg-accent",
                      )}
                    >
                      <div className="font-medium">{opt.label}</div>
                      <div className="text-xs text-muted-foreground">{opt.sub}</div>
                    </button>
                  ))}
                </div>
              )}
            />
          </Field>

          <Field label="Job title" htmlFor="job_title">
            <Input
              id="job_title"
              placeholder="e.g. Senior Backend Engineer"
              {...register("job_title")}
            />
            {errors.job_title ? (
              <p className="text-xs text-destructive">{errors.job_title.message}</p>
            ) : null}
          </Field>

          <Field
            label="Keywords (optional)"
            hint="30% of the match score. Matched against titles, headline, skills and certifications — use role words like 'external audit'. Leave blank to rank on job title and experience alone."
          >
            <Controller
              control={control}
              name="keywords"
              render={({ field }) => (
                <TagInput
                  value={field.value}
                  onChange={field.onChange}
                  placeholder="vendor management, procurement…"
                />
              )}
            />
          </Field>

          <Field
            label="Critical skills (optional)"
            hint="Pass/fail, not scored. Anyone without these is discarded — checked against titles, skills and certifications. Leave blank to filter on nothing."
          >
            <Controller
              control={control}
              name="critical_skills"
              render={({ field }) => (
                <TagInput
                  value={field.value}
                  onChange={field.onChange}
                  placeholder="Must-have skills…"
                />
              )}
            />
          </Field>

          <div className="grid gap-5 sm:grid-cols-2">
            <Field
              label="Location (optional)"
              htmlFor="location"
              hint="Leave blank to search everywhere — the 10% is redistributed, not given away."
            >
              <Input id="location" placeholder="Riyadh / Remote" {...register("location")} />
            </Field>
            <Field
              label="Minimum years of experience"
              htmlFor="min_experience"
              hint="0 means experience is not scored at all."
            >
              <Input
                id="min_experience"
                type="number"
                min={0}
                step={1}
                {...register("min_experience")}
              />
            </Field>
          </div>

          <Field
            label="Current company (optional)"
            hint="Applied as LinkedIn's own company filter, so people at other firms are never opened and cost you no hourly budget."
          >
            <Controller
              control={control}
              name="companies"
              render={({ field }) => (
                <div className="space-y-2">
                  <TagInput
                    value={field.value}
                    onChange={field.onChange}
                    placeholder="Deloitte, PwC…"
                  />
                  <button
                    type="button"
                    onClick={() =>
                      field.onChange(
                        Array.from(new Set([...field.value, ...BIG_FOUR])),
                      )
                    }
                    className="text-xs text-primary underline-offset-2 hover:underline"
                  >
                    + Add the Big Four
                  </button>
                  <Controller
                    control={control}
                    name="company_ids"
                    render={({ field: idsField }) => (
                      <div className="space-y-1">
                        <Input
                          placeholder="…or paste a LinkedIn search URL with the filter already applied"
                          onChange={(e) =>
                            idsField.onChange(companyIdsFromUrl(e.target.value))
                          }
                        />
                        {idsField.value.length > 0 ? (
                          <p className="text-xs text-success">
                            Using {idsField.value.length} company filter
                            {idsField.value.length === 1 ? "" : "s"} straight from
                            LinkedIn ({idsField.value.join(", ")}).
                          </p>
                        ) : null}
                      </div>
                    )}
                  />
                </div>
              )}
            />
          </Field>

          <Field
            label="Graduation year (optional)"
            hint="Career stage, read from the candidate's earliest graduation — so a recent part-time qualification does not make a long career look new. Profiles with no education dates are kept."
          >
            <div className="grid grid-cols-2 gap-3">
              <Input
                type="number"
                min={1950}
                max={2100}
                placeholder="From e.g. 2019"
                aria-label="Graduated from year"
                {...register("graduation_year_from")}
              />
              <Input
                type="number"
                min={1950}
                max={2100}
                placeholder="To (blank = now)"
                aria-label="Graduated to year"
                {...register("graduation_year_to")}
              />
            </div>
          </Field>

          <Field label="Industry (optional)" htmlFor="industry">
            <Input id="industry" {...register("industry")} />
          </Field>

          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Maximum results" htmlFor="max_results">
              <Input
                id="max_results"
                type="number"
                min={1}
                max={200}
                {...register("max_results")}
              />
            </Field>
            <Field label="Minimum match score" htmlFor="min_match_score">
              <Input
                id="min_match_score"
                type="number"
                min={0}
                max={100}
                {...register("min_match_score")}
              />
            </Field>
          </div>

          <div className="flex items-center justify-between rounded-md border border-border p-3">
            <div>
              <Label htmlFor="require_title_match">Must work in this field</Label>
              <p className="text-xs text-muted-foreground">
                Discard anyone whose career shows no sign of the job title&apos;s
                subject. A search for &ldquo;external audit manager&rdquo; then
                cannot return a finance manager.
              </p>
            </div>
            <Controller
              control={control}
              name="require_title_match"
              render={({ field }) => (
                <Switch
                  id="require_title_match"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>

          <div className="flex items-center justify-between rounded-md border border-border p-3">
            <div>
              <Label htmlFor="enforce_location">Strict location filter</Label>
              <p className="text-xs text-muted-foreground">
                Discard candidates outside the requested location. Ignored when no
                location is set.
              </p>
            </div>
            <Controller
              control={control}
              name="enforce_location"
              render={({ field }) => (
                <Switch
                  id="enforce_location"
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>

          {createSearch.isError ? (
            <p className="text-sm text-destructive">
              Could not start the search. Is the API running?
            </p>
          ) : null}

          <Button type="submit" size="lg" className="w-full" disabled={createSearch.isPending}>
            {createSearch.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <Search className="size-4" />
            )}
            Start search
          </Button>
        </form>
    </div>
  );
}
