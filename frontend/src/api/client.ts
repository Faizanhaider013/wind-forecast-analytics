// Small typed fetch layer. All backend access goes through here so the base URL,
// error handling, and JSON decoding live in one place.

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/** Error carrying the HTTP status and any `detail` message the API returned. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * GET a JSON endpoint relative to the API base URL.
 *
 * Throws {@link ApiError} for non-2xx responses (surfacing the backend's
 * `detail` text when present) and for network/parse failures, so callers get a
 * single error type to render.
 */
export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(
      `Could not reach the backend at ${API_BASE_URL}. Is it running?`,
      0,
    );
  }

  if (!response.ok) {
    let detail = `Request failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Non-JSON error body; keep the generic message.
    }
    throw new ApiError(detail, response.status);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("The backend returned a malformed response.", response.status);
  }
}
