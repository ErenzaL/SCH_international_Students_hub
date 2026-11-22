import { describe, expect, it } from "vitest";
import { buildSignupMetadata } from "@/lib/signup";

describe("buildSignupMetadata", () => {
  it("requires a supported language", () => {
    expect(buildSignupMetadata("", "")).toBeNull();
    expect(buildSignupMetadata("fr", "x")).toBeNull();
  });
  it("includes only the language and an optional trimmed name, never a role", () => {
    expect(buildSignupMetadata("zh-CN", "")).toEqual({ preferred_language: "zh-CN" });
    const m = buildSignupMetadata("ko", "  Min  ");
    expect(m).toEqual({ preferred_language: "ko", display_name: "Min" });
    expect(m).not.toHaveProperty("role");
  });
});
