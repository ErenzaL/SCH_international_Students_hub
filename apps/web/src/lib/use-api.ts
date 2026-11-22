"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";

export interface UseApiResult<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

function toApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  return new ApiError({
    status: 0,
    code: "unexpected_error",
    message: e instanceof Error ? e.message : "Unexpected error",
  });
}

/**
 * Minimal data hook. `key` identifies the request (re-fetches when it changes);
 * pass `null` to skip. Errors are surfaced, never swallowed or replaced with fake data.
 */
export function useApi<T>(key: string | null, fetcher: () => Promise<T>): UseApiResult<T> {
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean }>({
    data: null,
    error: null,
    loading: key !== null,
  });
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- start of an async fetch cycle
    setState((s) => ({ ...s, loading: true, error: null }));
    fetcherRef
      .current()
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((e) => {
        if (!cancelled) setState({ data: null, error: toApiError(e), loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
