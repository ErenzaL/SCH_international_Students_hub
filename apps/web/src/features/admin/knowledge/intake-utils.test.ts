import { describe, expect, it } from "vitest";
import {
  changedFields,
  documentKind,
  fieldsPayload,
  formatFieldValue,
  isSchBoardUrl,
  structuredToFieldValues,
  suggestedSync,
  validateDocumentFile,
  validateImageFile,
} from "@/features/admin/knowledge/intake-utils";

const MB = 1024 * 1024;

describe("file validation", () => {
  it("accepts pdf/docx/txt/md and maps kinds", () => {
    expect(documentKind("a.PDF")).toBe("pdf");
    expect(documentKind("b.docx")).toBe("docx");
    expect(documentKind("c.md")).toBe("text_file");
    expect(documentKind("d.txt")).toBe("text_file");
    expect(documentKind("e.hwp")).toBeNull();
    expect(validateDocumentFile({ name: "x.pdf", size: 10 }, 10)).toBeNull();
  });
  it("rejects wrong type, empty and oversized files", () => {
    expect(validateDocumentFile({ name: "x.exe", size: 10 }, 10)).toBe("unsupportedType");
    expect(validateDocumentFile({ name: "x.pdf", size: 0 }, 10)).toBe("empty");
    expect(validateDocumentFile({ name: "x.pdf", size: 11 * MB }, 10)).toBe("tooLarge");
    expect(validateDocumentFile({ name: "x.docx", size: 10 }, 10, "pdf")).toBe("unsupportedType");
  });
  it("validates screenshots", () => {
    expect(validateImageFile({ name: "s.png", size: 100 }, 8)).toBeNull();
    expect(validateImageFile({ name: "s.JPEG", size: 100 }, 8)).toBeNull();
    expect(validateImageFile({ name: "s.gif", size: 100 }, 8)).toBe("unsupportedType");
    expect(validateImageFile({ name: "s.webp", size: 9 * MB }, 8)).toBe("tooLarge");
  });
});

describe("SCH board URL + sync suggestion", () => {
  it("recognises SCH notice boards only", () => {
    expect(isSchBoardUrl("https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore&loc_mnu=3")).toBe(true);
    expect(isSchBoardUrl("https://www.studyinkorea.go.kr/en_US/plan/visaAndStay.do")).toBe(false);
    expect(isSchBoardUrl("https://evil-sch.ac.kr.example.com/notice01.php")).toBe(false);
    expect(isSchBoardUrl("not a url")).toBe(false);
  });
  it("suggests schedules by category and never for non-network sources", () => {
    expect(suggestedSync("university-announcements", "sch_board")).toBe("daily");
    expect(suggestedSync("visa-immigration", "website")).toBe("weekly");
    expect(suggestedSync("visa-immigration", "pdf")).toBe("manual");
  });
});

describe("structured field mapping", () => {
  it("maps detected fields to editable strings", () => {
    const v = structuredToFieldValues({
      fields: {
        deadline: { value: "2026-11-06", evidence: "…", confirmed: false, source: "rule" },
        application_period: { value: { start: "2026-10-27", end: "2026-11-06" }, evidence: null, confirmed: false, source: "rule" },
        unknown_key: { value: "x", evidence: null, confirmed: false, source: "rule" },
        event_date: { value: null, evidence: null, confirmed: false, source: "rule", needs_year: true },
      },
    });
    expect(v).toEqual({ deadline: "2026-11-06", application_period: "2026-10-27 ~ 2026-11-06" });
    expect(formatFieldValue({ start: null, end: "2026-01-01" })).toBe("? ~ 2026-01-01");
  });
  it("builds payloads without empty values and computes changes", () => {
    expect(fieldsPayload({ deadline: " 2026-11-06 ", fee: "", bogus: "x" })).toEqual({ deadline: "2026-11-06" });
    expect(changedFields({ deadline: "2026-11-06", fee: "무료" }, { deadline: "2026-11-07", fee: "" })).toEqual({
      deadline: "2026-11-07",
      fee: null,
    });
  });
});
