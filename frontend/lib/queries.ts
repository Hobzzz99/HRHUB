"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "./api";
import type { SearchCreateInput } from "./types";

export const queryKeys = {
  dashboard: ["dashboard"] as const,
  searches: ["searches"] as const,
  search: (id: string) => ["search", id] as const,
  results: (id: string) => ["results", id] as const,
  candidate: (id: string) => ["candidate", id] as const,
  saved: ["saved"] as const,
  providerAccount: (provider: string) => ["provider-account", provider] as const,
};

export function useDashboard() {
  return useQuery({ queryKey: queryKeys.dashboard, queryFn: api.getDashboard });
}

export function useSearches(limit = 20) {
  return useQuery({
    queryKey: [...queryKeys.searches, limit],
    queryFn: () => api.listSearches(limit),
  });
}

export function useSearchResults(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.results(id),
    queryFn: () => api.getResults(id),
    enabled,
  });
}

export function useCandidate(id: string | null) {
  return useQuery({
    queryKey: queryKeys.candidate(id ?? "none"),
    queryFn: () => api.getCandidate(id as string),
    enabled: !!id,
  });
}

export function useSaved() {
  return useQuery({ queryKey: queryKeys.saved, queryFn: api.listSaved });
}

export function useCreateSearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: SearchCreateInput) => api.createSearch(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.searches });
      qc.invalidateQueries({ queryKey: queryKeys.dashboard });
    },
  });
}

export function useSaveCandidate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ candidateId, notes }: { candidateId: string; notes?: string }) =>
      api.saveCandidate(candidateId, notes),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.saved }),
  });
}

export function useUnsaveCandidate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (candidateId: string) => api.unsaveCandidate(candidateId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.saved }),
  });
}

export function useProviderAccount(provider: string) {
  return useQuery({
    queryKey: queryKeys.providerAccount(provider),
    queryFn: () => api.getProviderAccount(provider),
  });
}

export function useConnectProvider(provider: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      api.connectProvider(provider, username, password),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: queryKeys.providerAccount(provider) }),
  });
}
