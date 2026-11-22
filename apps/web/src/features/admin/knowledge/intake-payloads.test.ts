import { describe, expect, it } from "vitest";
import { pastePayload, type PasteValues } from "@/features/admin/knowledge/intake-paste";
import { EMPTY_META, metaErrors, metaPayload } from "@/features/admin/knowledge/source-meta-fields";

const meta = { ...EMPTY_META, title: " 동계방학 생활관 입사 안내 ", organization: " 국제교육교류처 ", original_url: "  " };
const values: PasteValues = {
  original_text: "원문 그대로의 공지 텍스트입니다. 010-1234-5678",
  normalized_text: "",
  target_audience: "외국인 유학생",
  event_date: "",
  deadline: "2026-12-01",
  location: " ",
  application_method: "",
  notes: "",
  received_via: "kakaotalk",
};

describe("intake payloads", () => {
  it("validates and trims source metadata", () => {
    expect(metaErrors({ ...EMPTY_META })).toEqual({ title: "required", organization: "required" });
    expect(metaErrors({ ...meta, original_url: "ftp://x" }).original_url).toBe("invalidUrl");
    expect(metaPayload(meta)).toMatchObject({ title: "동계방학 생활관 입사 안내", organization: "국제교육교류처", original_url: undefined });
  });

  it("keeps the original text unchanged and omits empty optional fields", () => {
    const p = pastePayload(meta, values, { submit: false, redact: true, authorized: true });
    expect(p.original_text).toBe(values.original_text);
    expect(p.normalized_text).toBeUndefined();
    expect(p.deadline).toBe("2026-12-01");
    expect(p.target_audience).toBe("외국인 유학생");
    expect(p.location).toBeUndefined();
    expect(p.event_date).toBeUndefined();
    expect(p).toMatchObject({ received_via: "kakaotalk", redact_personal_info: true, authorized_by_supporter: true, submit: false });
  });

  it("never sends an official government authority for pasted staff messages", () => {
    const p = pastePayload({ ...meta, authority_type: "official_government" }, values, { submit: true, redact: false, authorized: true });
    expect(p.authority_type).toBe("staff_communication");
  });
});
