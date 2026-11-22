import { describe, expect, it } from "vitest";
import { DEV_API_FALLBACK, normalizeApiUrl, resolveApiBaseUrl } from "@/lib/api-url";

const PROD_API = "https://sch-hub-api.onrender.com";

describe("resolveApiBaseUrl", () => {
  it("uses NEXT_PUBLIC_API_URL in production", () => {
    expect(resolveApiBaseUrl({ apiUrl: PROD_API, nodeEnv: "production" })).toBe(PROD_API);
  });

  it("prefers NEXT_PUBLIC_API_URL over the legacy name", () => {
    expect(
      resolveApiBaseUrl({ apiUrl: PROD_API, legacyApiBaseUrl: "https://old.example.com", nodeEnv: "production" }),
    ).toBe(PROD_API);
  });

  it("still accepts the legacy NEXT_PUBLIC_API_BASE_URL", () => {
    expect(resolveApiBaseUrl({ legacyApiBaseUrl: PROD_API, nodeEnv: "production" })).toBe(PROD_API);
  });

  it("never falls back to localhost in production", () => {
    expect(resolveApiBaseUrl({ nodeEnv: "production" })).toBe("");
    expect(resolveApiBaseUrl({ apiUrl: "   ", nodeEnv: "production" })).toBe("");
  });

  it("falls back to localhost only in development", () => {
    expect(resolveApiBaseUrl({ nodeEnv: "development" })).toBe(DEV_API_FALLBACK);
  });
});

describe("normalizeApiUrl", () => {
  it("strips whitespace, trailing slashes and a trailing /api/v1", () => {
    expect(normalizeApiUrl(` ${PROD_API}/ `)).toBe(PROD_API);
    expect(normalizeApiUrl(`${PROD_API}/api/v1/`)).toBe(PROD_API);
  });
});
