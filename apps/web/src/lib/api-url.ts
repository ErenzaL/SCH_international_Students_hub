/**
 * Resolves the FastAPI base URL.
 *
 * `NEXT_PUBLIC_*` values are inlined into the browser bundle at BUILD time, so changing
 * them on the host requires a rebuild. `NEXT_PUBLIC_API_URL` is the primary name;
 * `NEXT_PUBLIC_API_BASE_URL` is still accepted for older setups.
 *
 * The localhost fallback is used ONLY outside production. In a production build with no
 * URL configured this returns "" and every request fails with `api_not_configured`
 * instead of silently calling http://localhost:8000.
 */
export const DEV_API_FALLBACK = "http://localhost:8000";

export interface ApiUrlEnv {
  apiUrl?: string;
  legacyApiBaseUrl?: string;
  nodeEnv?: string;
}

export function normalizeApiUrl(raw: string): string {
  let url = raw.trim().replace(/\/+$/, "");
  // Request paths already start with /api/v1, so tolerate a base URL that includes it.
  url = url.replace(/\/api\/v1$/i, "");
  return url;
}

export function resolveApiBaseUrl(env: ApiUrlEnv): string {
  const configured = (env.apiUrl ?? "").trim() || (env.legacyApiBaseUrl ?? "").trim();
  if (configured) return normalizeApiUrl(configured);
  return env.nodeEnv === "production" ? "" : DEV_API_FALLBACK;
}
