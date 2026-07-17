import { SearchForm } from "@/components/search-form";

export default function NewSearchPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">New search</h1>
        <p className="text-muted-foreground">
          Describe the role. We&apos;ll search, score, and rank candidates for you.
        </p>
      </div>
      <SearchForm />
    </div>
  );
}
