import { getAccessToken } from "./supabase";
import type {
  Candidate,
  DashboardStats,
  ProviderAccount,
  SavedCandidate,
  Search,
  SearchCreateInput,
  SearchResult,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = await getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  getDashboard: () => request<DashboardStats>("/dashboard"),
  listSearches: (limit = 20) => request<Search[]>(`/search?limit=${limit}`),
  createSearch: (input: SearchCreateInput) =>
    request<Search>("/search", { method: "POST", body: JSON.stringify(input) }),
  getSearch: (id: string) => request<Search>(`/search/${id}`),
  getResults: (id: string) => request<SearchResult[]>(`/search/${id}/results`),
  getCandidate: (id: string) => request<Candidate>(`/candidate/${id}`),
  listSaved: () => request<SavedCandidate[]>("/saved"),
  saveCandidate: (candidateId: string, notes?: string) =>
    request<SavedCandidate>("/candidate/save", {
      method: "POST",
      body: JSON.stringify({ candidate_id: candidateId, notes: notes ?? null }),
    }),
  unsaveCandidate: (candidateId: string) =>
    request<void>(`/candidate/save/${candidateId}`, { method: "DELETE" }),
  /**
   * Download the results as a file.
   *
   * Fetched rather than linked to. An `<a href>` cannot carry the bearer token,
   * so with auth on the export endpoint answered `{"detail":"Not authenticated"}`
   * — and the browser rendered that JSON in place of the app, which reads as
   * the tool being broken rather than as a download failing.
   */
  exportResults: async (id: string, fmt: "csv" | "json" = "csv") => {
    const token = await getAccessToken();
    const res = await fetch(`${API_URL}/search/${id}/export?fmt=${fmt}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new ApiError(res.status, "Could not export these results.");

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `talentfinder-${id}.${fmt}`;
    link.click();
    // Without this the blob is held for the life of the document.
    URL.revokeObjectURL(url);
  },
  getProviderAccount: (provider: string) =>
    request<ProviderAccount | null>(`/provider-account/${provider}`),
  rotateProviderAccount: (provider: string) =>
    request<ProviderAccount>(`/provider-account/${provider}/rotate`, {
      method: "POST",
    }),
};
