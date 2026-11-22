import { describe, expect, it } from "vitest";
import {
  EMPTY_SOURCE_FORM,
  toSourceCreate,
  validateSourceForm,
  type SourceFormValues,
} from "@/features/admin/sources/source-validation";

const valid: SourceFormValues = {
  ...EMPTY_SOURCE_FORM,
  title: "Study in Korea – Visa",
  organization: "Study in Korea",
  original_url: "https://www.studyinkorea.go.kr/en_US/plan/visaAndStay.do",
};

describe("validateSourceForm", () => {
  it("accepts a valid website source", () => {
    expect(validateSourceForm(valid)).toEqual({});
  });

  it("requires title and organization", () => {
    const errors = validateSourceForm({ ...valid, title: "  ", organization: "" });
    expect(errors.title).toBe("required");
    expect(errors.organization).toBe("required");
  });

  it("requires an http(s) URL for website sources", () => {
    expect(validateSourceForm({ ...valid, original_url: "" }).original_url).toBe("urlRequired");
    expect(validateSourceForm({ ...valid, original_url: "not a url" }).original_url).toBe("invalidUrl");
    expect(validateSourceForm({ ...valid, original_url: "ftp://example.com/file" }).original_url).toBe("invalidUrl");
    expect(validateSourceForm({ ...valid, original_url: "javascript:alert(1)" }).original_url).toBe("invalidUrl");
  });

  it("allows non-website sources without a URL but rejects automatic sync", () => {
    const pdf = { ...valid, source_type: "pdf" as const, original_url: "" };
    expect(validateSourceForm(pdf)).toEqual({});
    expect(validateSourceForm({ ...pdf, sync_frequency: "daily" }).sync_frequency).toBe("manualOnly");
  });

  it("requires supporter authority for KakaoTalk submissions", () => {
    const kakao = { ...valid, source_type: "kakao_message" as const, original_url: "" };
    expect(validateSourceForm({ ...kakao, authority_type: "official_government" }).authority_type).toBe("kakaoAuthority");
    expect(validateSourceForm({ ...kakao, authority_type: "supporter_submitted" })).toEqual({});
  });

  it("builds the API payload with trimmed values and no empty URL", () => {
    const payload = toSourceCreate({ ...valid, title: "  T  ", source_type: "manual_text", original_url: "  " });
    expect(payload.title).toBe("T");
    expect(payload.original_url).toBeUndefined();
    expect(payload.is_active).toBe(true);
  });
});
