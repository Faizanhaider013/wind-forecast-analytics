import { useEffect, useState } from "react";

import { ApiError } from "../api/client";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; message: string; httpStatus?: number };

/**
 * Run an async loader whenever `deps` change, exposing loading/success/error.
 *
 * The loader receives an AbortSignal; stale requests are aborted on change or
 * unmount so late responses never overwrite newer state.
 */
export function useAsync<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: ReadonlyArray<unknown>,
): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });

    loader(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setState({ status: "success", data });
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (error instanceof ApiError) {
          setState({ status: "error", message: error.message, httpStatus: error.status });
        } else {
          const message = error instanceof Error ? error.message : "Unexpected error";
          setState({ status: "error", message });
        }
      });

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
