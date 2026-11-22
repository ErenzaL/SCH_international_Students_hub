import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithIntl } from "@/test/utils";
import { JobProgress } from "@/features/admin/knowledge/job-progress";
import { jobStageKey, progressPercent } from "@/lib/job-progress";
import type { Job } from "@/types/api";

const base: Job = {
  id: "j1", source_id: "s1", source_title: "비자 안내", status: "running", trigger: "manual", outcome: null,
  document_id: null, version_id: null, error_code: null, error_message: null, statistics: {},
  created_at: "2026-11-22T10:11:00Z", started_at: "2026-11-22T10:11:05Z", completed_at: null, job_type: "ingest",
  attempts: 1, max_attempts: 3,
};

describe("JobProgress", () => {
  it("shows the current stage, page progress and the last signal for a running extraction", () => {
    renderWithIntl(<JobProgress job={{ ...base, stage: "extract", progress: { done: 3, total: 12, unit: "pages" },
      heartbeat_age_seconds: 4 }} />);
    expect(screen.getByText("Extracting text")).toBeInTheDocument();
    expect(screen.getByText(/page 3 of 12/)).toBeInTheDocument();
    expect(screen.getByText(/last signal 4 seconds ago/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  });

  it("warns when the worker stopped responding and explains the automatic retry", () => {
    renderWithIntl(<JobProgress job={{ ...base, stage: "extract", stale: true, heartbeat_age_seconds: 600, attempts: 1 }} />);
    expect(screen.getByText(/the service probably restarted.*attempt 1 of 3/)).toBeInTheDocument();
  });

  it("reports a resumed attempt, stage timings and the PDF diagnosis after the job ran", () => {
    renderWithIntl(<JobProgress job={{ ...base, status: "failed", attempts: 2, resumed_from_stage: "extract",
      error_code: "needs_ocr",
      stages: [{ stage: "download", ms: 420, ok: true }, { stage: "extract", ms: 12500, ok: false, error: "needs_ocr" }],
      pdf: { pages: 12, pages_with_text: 0, needs_ocr_pages: 12, hangul_ratio: 0 } }} />);
    expect(screen.getByText(/Resumed after an interruption during “Extracting text” \(attempt 2\)/)).toBeInTheDocument();
    expect(screen.getByText("Loading the file 420 ms")).toBeInTheDocument();
    expect(screen.getByText("Extracting text 13 s (needs_ocr)")).toBeInTheDocument();
    expect(screen.getByText(/12 pages, 0 with text, 12 need OCR/)).toBeInTheDocument();
  });

  it("compact form for the sources table", () => {
    renderWithIntl(<JobProgress compact job={{ ...base, stage: "ocr", progress: { done: 1, total: 5, unit: "pages" }, stale: true }} />);
    expect(screen.getByTestId("job-progress-compact")).toHaveTextContent("Running OCR · page 1 of 5");
    expect(screen.getByTestId("job-progress-compact")).toHaveTextContent("retried automatically");
  });

  it("helpers", () => {
    expect(jobStageKey("extract")).toBe("extract");
    expect(jobStageKey("mystery")).toBe("other");
    expect(progressPercent({ done: 5, total: 0, unit: "pages" })).toBeNull();
    expect(progressPercent({ done: 7, total: 7, unit: "pages" })).toBe(100);
  });
});
