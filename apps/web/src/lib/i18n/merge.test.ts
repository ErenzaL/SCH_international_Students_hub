import { describe, expect, it } from "vitest";
import { deepMerge, matchLocale, resolveLocale } from "@/lib/i18n/merge";
import en from "@/messages/en.json";
import ko from "@/messages/ko.json";

describe("deepMerge (fallback to English)", () => {
  it("keeps English for keys missing in the target locale", () => {
    const merged = deepMerge({ a: "A", b: { c: "C", d: "D" } }, { b: { c: "씨" } });
    expect(merged).toEqual({ a: "A", b: { c: "씨", d: "D" } });
  });

  it("ignores empty translations", () => {
    expect(deepMerge({ a: "A" }, { a: "  " })).toEqual({ a: "A" });
  });

  it("produces a complete catalog for a partially translated locale", () => {
    // a locale that lacks some keys (e.g. a newly added string) still gets the English text for them
    const partial = { nav: { home: ko.nav.home } };
    const merged = deepMerge(en as never, partial as never) as typeof en;
    expect(merged.nav.home).toBe("홈");
    expect(merged.admin.settings.title).toBe(en.admin.settings.title);
    // the shipped Korean catalog is complete: admin screens are translated too
    expect((deepMerge(en as never, ko as never) as typeof en).admin.settings.title).toBe(ko.admin.settings.title);
    expect(ko.admin.settings.title).not.toBe(en.admin.settings.title);
  });
});

describe("locale resolution", () => {
  it("maps browser tags to supported locales", () => {
    expect(matchLocale("ko-KR")).toBe("ko");
    expect(matchLocale("id")).toBe("id");
    expect(matchLocale("in")).toBe("id");
    expect(matchLocale("vi-VN")).toBe("vi");
    expect(matchLocale("zh-Hans")).toBe("zh-CN");
    expect(matchLocale("zh-CN")).toBe("zh-CN");
    expect(matchLocale("zh-TW")).toBeNull();
    expect(matchLocale("fr")).toBeNull();
  });

  it("prefers an explicit preference, then Accept-Language, then English", () => {
    expect(resolveLocale("vi", "ko")).toBe("vi");
    expect(resolveLocale(undefined, "fr;q=0.9, ko;q=0.8, en;q=0.5")).toBe("ko");
    expect(resolveLocale("xx", "de, fr")).toBe("en");
    expect(resolveLocale(null, null)).toBe("en");
  });
});
