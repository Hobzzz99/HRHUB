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
  exportUrl: (id: string, fmt: "csv" | "json" = "csv") =>
    `${API_URL}/search/${id}/export?fmt=${fmt}`,
  getProviderAccount: (provider: string) =>
    request<ProviderAccount | null>(`/provider-account/${provider}`),
  connectProvider: (provider: string, username: string, password: string) =>
    request<ProviderAccount>("/provider-account", {
      method: "POST",
      body: JSON.stringify({ provider, username, password }),
    }),
};
