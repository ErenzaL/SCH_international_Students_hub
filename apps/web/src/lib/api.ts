import { API_BASE_URL } from "@/lib/constants";
import { getAccessToken } from "@/lib/supabase/client";

export type ApiErrorKind = "api" | "network";

/** Structured error for every failed API interaction. */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(opts: {
    message: string;
    status: number;
    code: string;
    details?: unknown;
    requestId?: string | null;
    kind?: ApiErrorKind;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.kind = opts.kind ?? "api";
    this.status = opts.status;
    this.code = opts.code;
    this.details = opts.details ?? null;
    this.requestId = opts.requestId ?? null;
  }

  get isNetwork() {
    return this.kind === "network";
  }
  get isSupabaseNotConfigured() {
    return this.code === "supabase_not_configured";
  }
  get isUnauthenticated() {
    return this.status === 401;
  }
}

/** Parse a non-2xx response body into an ApiError (tolerates non-JSON bodies). */
export function parseApiError(status: number, body: unknown, statusText = ""): ApiError {
  const b = body as {
    error?: { code?: string; message?: string; details?: unknown };
    request_id?: string;
    detail?: unknown;
  } | null;
  if (b && typeof b === "object" && b.error && typeof b.error === "object") {
    return new ApiError({
      status,
      code: b.error.code ?? `http_${status}`,
      message: b.error.message ?? (statusText || `Request failed (${status})`),
      details: b.error.details,
      requestId: b.request_id ?? null,
    });
  }
  const detail = b && typeof b === "object" && typeof b.detail === "string" ? b.detail : null;
  return new ApiError({
    status,
    code: `http_${status}`,
    message: detail ?? (statusText || `Request failed (${status})`),
    requestId: b?.request_id ?? null,
  });
}

export type QueryValue = string | number | boolean | null | undefined;

export function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = new URL(API_BASE_URL + path);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === "") continue;
      url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

interface RequestOptions {
  query?: Record<string, QueryValue>;
  body?: unknown;
  formData?: FormData;
  /** Attach the Supabase access token. Defaults to true for /me and /admin paths. */
  auth?: boolean;
  signal?: AbortSignal;
}

function needsAuth(path: string) {
  return path.startsWith("/api/v1/admin") || path.startsWith("/api/v1/me");
}

export async function apiRequest<T>(
  method: string,
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const wantsAuth = opts.auth ?? needsAuth(path);
  if (wantsAuth) {
    const token = await getAccessToken();
    if (!token) {
      throw new ApiError({
        status: 401,
        code: "not_authenticated",
        message: "You are not signed in.",
      });
    }
    headers.Authorization = `Bearer ${token}`;
  }
  let body: BodyInit | undefined;
  if (opts.formData) {
    body = opts.formData;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      body,
      signal: opts.signal,
      cache: "no-store",
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError({
      kind: "network",
      status: 0,
      code: "network_error",
      message: `Cannot reach the API at ${API_BASE_URL}. Is the backend running and CORS configured?`,
    });
  }

  let parsed: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!res.ok) throw parseApiError(res.status, parsed, res.statusText);
  return parsed as T;
}

export const api = {
  get: <T>(path: string, query?: Record<string, QueryValue>, opts?: Omit<RequestOptions, "query" | "body">) =>
    apiRequest<T>("GET", path, { ...opts, query }),
  post: <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, "body">) =>
    apiRequest<T>("POST", path, { ...opts, body: body ?? {} }),
  put: <T>(path: string, body?: unknown) => apiRequest<T>("PUT", path, { body: body ?? {} }),
  patch: <T>(path: string, body?: unknown) => apiRequest<T>("PATCH", path, { body: body ?? {} }),
  upload: <T>(path: string, formData: FormData) =>
    apiRequest<T>("POST", path, { formData }),
};

/** Human-readable text for any thrown value. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.requestId ? `${err.message} (ref ${err.requestId})` : err.message;
  }
  return err instanceof Error ? err.message : "Unexpected error";
}
