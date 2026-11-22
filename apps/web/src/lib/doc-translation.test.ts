import { describe, expect, it } from "vitest";
import { articleView, contentLanguage, docTranslationState, lineDiff, textBlocks } from "@/lib/doc-translation";
import type { PublicDocTranslation } from "@/types/api";

const doc = { title: "Visa and Stay", content: "# Visa and Stay\n\nKeep your status valid.", language: "en" as const };
const verifiedId: PublicDocTranslation = {
  status: "verified", language: "id", title: "Visa dan Izin Tinggal", content: "# Visa dan Izin Tinggal\n\nJaga status Anda.",
  headings: ["Visa dan Izin Tinggal"], reviewed_at: "2026-11-22T00:00:00Z", generated_at: null, source_version_number: 1,
};

describe("articleView", () => {
  it("shows the English original in English", () => {
    expect(articleView({ ...doc, translation: null }, "en", false)).toMatchObject({ mode: "original", title: "Visa and Stay", language: "en" });
  });
  it("shows the approved Indonesian translation when Indonesian is selected", () => {
    expect(articleView({ ...doc, translation: verifiedId }, "id", false)).toMatchObject({
      mode: "verified", title: "Visa dan Izin Tinggal", language: "id",
    });
  });
  it("falls back to the original when no approved translation exists", () => {
    expect(articleView({ ...doc, translation: null }, "vi", false)).toMatchObject({ mode: "fallback", title: "Visa and Stay", language: "en" });
  });
  it("lets the reader view the original instead of the translation", () => {
    expect(articleView({ ...doc, translation: verifiedId }, "id", true)).toMatchObject({ mode: "original", language: "en" });
  });
  it("never presents a machine draft as verified", () => {
    const v = articleView({ ...doc, translation: { ...verifiedId, status: "machine", reviewed_at: null } }, "id", false);
    expect(v.mode).toBe("machine");
  });
  it("ignores a translation for another language", () => {
    expect(articleView({ ...doc, translation: verifiedId }, "vi", false).mode).toBe("fallback");
  });
});

describe("helpers", () => {
  it("picks the content language without touching the profile", () => {
    expect(contentLanguage("vi", "id")).toBe("vi");
    expect(contentLanguage(null, "zh-CN")).toBe("zh-CN");
    expect(contentLanguage("xx", "fr")).toBe("en");
  });
  it("outdated beats every status", () => {
    expect(docTranslationState({ translation_status: "human_approved", is_outdated: true })).toBe("outdated");
    expect(docTranslationState({ translation_status: "machine_draft", is_outdated: false })).toBe("machine_draft");
    expect(docTranslationState(null)).toBe("none");
  });
  it("diffs lines", () => {
    expect(lineDiff("a\nb\nc", "a\nB\nc")).toEqual([
      { op: "same", text: "a" }, { op: "del", text: "b" }, { op: "add", text: "B" }, { op: "same", text: "c" },
    ]);
  });
  it("splits markdown into headings and paragraphs (text only)", () => {
    expect(textBlocks("# T\n\nBody <b>x</b>\n\n## H ##")).toEqual([
      { kind: "h1", text: "T" }, { kind: "p", text: "Body <b>x</b>" }, { kind: "h2", text: "H" },
    ]);
  });
});
