"use client";

import { useEffect, useRef, useState } from "react";

import { api, API_URL } from "./api";
import { AUTH_DISABLED } from "./supabase";
import type { Degradation, SearchProgress, SearchStatus } from "./types";

export interface StreamState {
  status: SearchStatus;
  progress: SearchProgress;
  result_count: number;
  error: string | null;
  /** Carried on the live stream rather than read from the initial fetch: the
   *  page loads while the search is still queued, so a copy taken then always
   *  says nothing was degraded — which is how a search whose company filter
   *  never applied still showed the ordinary "no candidates" message. */
  degraded_reasons: Degradation[] | null;
  /** The status endpoint has stopped answering. The search may well be running
   *  fine — we simply cannot see it, and saying nothing looks identical to a
   *  search that is taking a long time. */
  unreachable: boolean;
}

const isTerminal = (s: SearchStatus) => s === "completed" || s === "failed";

/** ~6 seconds of failed polls before we say so. Long enough to ride out a
 *  redeploy, short enough that nobody watches a dead spinner. */
const UNREACHABLE_AFTER = 4;

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
    degraded_reasons: null,
    unreachable: false,
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
      // Deliberately *not* closed here. The browser reconnects an EventSource
      // by itself; closing it defeats that. The server hangs up after ten
      // minutes so a stuck job cannot hold a connection open forever, and a
      // scrape-backed run of twenty profiles outlives that window — so the
      // stream ending mid-run is expected, not a failure. Closing on it left
      // the page showing "Running" and stale counters for a search that had
      // finished several minutes earlier.
      es.addEventListener("error", () => {
        if (settled.current) es.close();
      });
      return () => es.close();
    }

    const poll = async () => {
      // A single failed poll is ordinary — a redeploy, a dropped packet. Many
      // in a row is not, and swallowing them all left the recruiter watching a
      // spinner forever with no way to tell that nothing was coming.
      let consecutiveFailures = 0;

      while (!cancelled) {
        try {
          const s = await api.getSearch(searchId);
          consecutiveFailures = 0;
          setState({
            status: s.status,
            progress: s.progress,
            result_count: s.result_count,
            error: s.error,
            degraded_reasons: s.degraded_reasons,
            unreachable: false,
          });
          if (isTerminal(s.status)) {
            settled.current = true;
            break;
          }
        } catch {
          consecutiveFailures += 1;
          if (consecutiveFailures >= UNREACHABLE_AFTER) {
            setState((prev) => ({ ...prev, unreachable: true }));
          }
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
