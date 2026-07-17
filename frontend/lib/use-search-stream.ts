"use client";

import { useEffect, useRef, useState } from "react";

import { api, API_URL } from "./api";
import { AUTH_DISABLED } from "./supabase";
import type { SearchProgress, SearchStatus } from "./types";

export interface StreamState {
  status: SearchStatus;
  progress: SearchProgress;
  result_count: number;
  error: string | null;
}

const isTerminal = (s: SearchStatus) => s === "completed" || s === "failed";

/**
 * Live search status. Uses SSE when auth is disabled (EventSource can't carry a
 * bearer token); otherwise falls back to polling the status endpoint. Both stop
 * once the job reaches a terminal state.
 */
export function useSearchStream(searchId: string, initialStatus: SearchStatus) {
  const [state, setState] = useState<StreamState>({
    status: initialStatus,
    progress: {},
    result_count: 0,
    error: null,
  });
  const settled = useRef(false);

  useEffect(() => {
    settled.current = false;
    let cancelled = false;

    if (AUTH_DISABLED) {
      const es = new EventSource(`${API_URL}/search/${searchId}/stream`);
      es.addEventListener("status", (e) => {
        const data = JSON.parse((e as MessageEvent).data) as StreamState;
        setState(data);
        if (isTerminal(data.status)) {
          settled.current = true;
          es.close();
        }
      });
      es.addEventListener("error", () => es.close());
      return () => es.close();
    }

    const poll = async () => {
      while (!cancelled) {
        try {
          const s = await api.getSearch(searchId);
          setState({
            status: s.status,
            progress: s.progress,
            result_count: s.result_count,
            error: s.error,
          });
          if (isTerminal(s.status)) {
            settled.current = true;
            break;
          }
        } catch {
          /* transient — keep polling */
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
    };
    void poll();
    return () => {
      cancelled = true;
    };
  }, [searchId]);

  return { ...state, settled: settled.current };
}
