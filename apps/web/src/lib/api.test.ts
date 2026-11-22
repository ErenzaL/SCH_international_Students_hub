import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, buildUrl, errorMessage, needsAuth, parseApiError } from "@/lib/api";

async function failure(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p;
  } catch (e) {
    return e as ApiError;
  }
  throw new Error("expected the request to fail");
}

describe("parseApiError", () => {
  it("parses the structured error body", () => {
    const err = parseApiError(
      422,
      { error: { code: "url_not_allowed", message: "Domain not allowed", details: [{ field: "url" }] }, request_id: "r1" },
    );
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(err.code).toBe("url_not_allowed");
    expect(err.message).toBe("Domain not allowed");
    expect(err.requestId).toBe("r1");
    expect(err.details).toEqual([{ field: "url" }]);
    expect(errorMessage(err)).toContain("ref r1");
  });

  it("flags supabase_not_configured", () => {
    const err = parseApiError(503, { error: { code: "supabase_not_configured", message: "x" } });
    expect(err.isSupabaseNotConfigured).toBe(true);
  });

  it("falls back for non-JSON / unexpected bodies", () => {
    const err = parseApiError(500, null, "Internal Server Error");
    expect(err.code).toBe("http_500");
    expect(err.message).toBe("Internal Server Error");
    expect(parseApiError(400, { detail: "bad" }).message).toBe("bad");
  });
});

describe("apiRequest", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reports network failures with a distinct error kind", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await failure(api.get("/api/v1/categories"));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isNetwork).toBe(true);
    expect(err.code).toBe("network_error");
  });

  it("throws a parsed ApiError on non-2xx responses (no fake data)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: "not_found", message: "Missing" }, request_id: "z" }), { status: 404 }),
      ),
    );
    const err = await failure(api.get("/api/v1/announcements/x"));
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
  });

  it("returns parsed JSON on success and builds query strings", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const data = await api.get<{ items: unknown[] }>("/api/v1/announcements", { q: "visa", page: 2, category: "" });
    expect(data.items).toEqual([]);
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("q=visa");
    expect(url).toContain("page=2");
    expect(url).not.toContain("category=");
  });

  it("refuses admin calls without a session instead of sending anonymous requests", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const err = await failure(api.get("/api/v1/admin/sources"));
    expect(err.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("buildUrl skips empty values", () => {
    expect(buildUrl("/x", { a: "1", b: "", c: undefined, d: null })).toMatch(/\/x\?a=1$/);
  });
});


describe("needsAuth", () => {
  it("attaches the token to every user-specific API", () => {
    for (const p of ["/api/v1/me", "/api/v1/me/notifications", "/api/v1/conversations", "/api/v1/conversations/1/messages",
      "/api/v1/support/tickets", "/api/v1/support/inbox?view=queue", "/api/v1/admin/sources"]) {
      expect(needsAuth(p)).toBe(true);
    }
  });
  it("keeps public endpoints anonymous", () => {
    for (const p of ["/api/v1/knowledge/search", "/api/v1/announcements", "/api/v1/categories", "/api/v1/meta"]) {
      expect(needsAuth(p)).toBe(false);
    }
  });
});
