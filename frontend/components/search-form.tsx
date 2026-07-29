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

const schema = z.object({
  job_title: z.string().min(1, "Job title is required"),
  skills: z.array(z.string()),
  critical_skills: z.array(z.string()),
  location: z.string(),
  min_experience: z.coerce.number().min(0).max(50),
  keywords: z.array(z.string()),
  company: z.string(),
  industry: z.string(),
  max_results: z.coerce.number().min(1).max(200),
  min_match_score: z.coerce.number().min(0).max(100),
  enforce_location: z.boolean(),
  provider: z.enum(["mock", "linkedin"]),
});

type FormValues = z.infer<typeof schema>;

const defaults: FormValues = {
  job_title: "",
  skills: [],
  critical_skills: [],
  location: "",
  min_experience: 0,
  keywords: [],
  company: "",
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
      company: values.company || null,
      industry: values.industry || null,
    });
    router.push(`/search/${search.id}`);
  });

  return (
    <div className="glass rounded-3xl p-6 sm:p-8">
      <form onSubmit={onSubmit} className="space-y-5">
          <Field
            label="Data source"
            hint="LinkedIn opens a real browser window on the server — sign in and clear any CAPTCHA yourself. Capped at 20 profiles per hour. Demo data runs on fixtures, no network."
          >
            <Controller
              control={control}
              name="provider"
              render={({ field }) => (
                <div className="grid grid-cols-2 gap-2">
                  {(
                    [
                      { value: "mock", label: "Demo data", sub: "safe, instant" },
                      { value: "linkedin", label: "LinkedIn", sub: "manual sign-in, 20/hr" },
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

          <Field label="Required skills" hint="Press Enter or comma to add">
            <Controller
              control={control}
              name="skills"
              render={({ field }) => (
                <TagInput
                  value={field.value}
                  onChange={field.onChange}
                  placeholder="Python, FastAPI, Docker…"
                />
              )}
            />
          </Field>

          <Field
            label="Critical skills"
            hint="Candidates missing any of these are discarded"
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
            <Field label="Location" htmlFor="location">
              <Input id="location" placeholder="Berlin / Remote" {...register("location")} />
            </Field>
            <Field label="Minimum years of experience" htmlFor="min_experience">
              <Input
                id="min_experience"
                type="number"
                min={0}
                step={1}
                {...register("min_experience")}
              />
            </Field>
          </div>

          <Field label="Keywords" hint="Extra terms to guide the search">
            <Controller
              control={control}
              name="keywords"
              render={({ field }) => (
                <TagInput
                  value={field.value}
                  onChange={field.onChange}
                  placeholder="microservices, fintech…"
                />
              )}
            />
          </Field>

          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Current company (optional)" htmlFor="company">
              <Input id="company" {...register("company")} />
            </Field>
            <Field label="Industry (optional)" htmlFor="industry">
              <Input id="industry" {...register("industry")} />
            </Field>
          </div>

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
              <Label htmlFor="enforce_location">Strict location filter</Label>
              <p className="text-xs text-muted-foreground">
                Discard candidates outside the requested location
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
