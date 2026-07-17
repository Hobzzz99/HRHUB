"use client";

import { CheckCircle2, Database } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">How candidate data is sourced.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="size-5 text-primary" /> Data source
            <span className="ml-auto inline-flex items-center gap-1 text-sm text-success">
              <CheckCircle2 className="size-4" /> Apify
            </span>
          </CardTitle>
          <CardDescription>
            LinkedIn profiles are fetched through Apify&apos;s API. Apify runs the
            collection on its own infrastructure, so no LinkedIn account is connected
            here and nothing can get banned. Pick <strong>Apify</strong> as the data
            source when creating a search.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            The Apify token is configured on the server (<code>APIFY_TOKEN</code>), not
            per user — there is nothing to connect here. Choose <strong>Demo data</strong>
            on a search to run on fixtures with no network calls.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
