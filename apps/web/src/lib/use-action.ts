"use client";

import { useCallback, useState } from "react";
import { ApiError } from "@/lib/api";

/** Wraps a mutating call: tracks busy state and keeps the real error for display. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e
          : new ApiError({
              status: 0,
              code: "unexpected_error",
              message: e instanceof Error ? e.message : "Unexpected error",
            }),
      );
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);

  const clear = useCallback(() => setError(null), []);
  return { run, busy, error, clear };
}
