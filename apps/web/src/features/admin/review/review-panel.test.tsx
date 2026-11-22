import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import { ReviewPanel } from "@/features/admin/review/review-panel";
import type { DocumentDetail, Version } from "@/types/api";

const version = (over: Partial<Version>): Version => ({
  id: "v",
  document_id: "d1",
  version_number: 1,
  extracted_text: "text",
  content_hash: "a".repeat(64),
  content_length: 4,
  source_published_at: null,
  fetched_at: "2030-01-01T00:00:00Z",
  valid_from: null,
  valid_until: null,
  verification_status: "approved",
  approved_by: null,
  approved_at: "2030-01-02T00:00:00Z",
  rejected_reason: null,
  created_at: "2030-01-01T00:00:00Z",
  chunk_count: 2,
  embedded_chunk_count: 2,
  embedding_model: "intfloat/multilingual-e5-small",
  is_current: true,
  ...over,
});

const current = version({ id: "v1", version_number: 1, content_hash: "1".repeat(64) });
const pending = version({
  id: "v2",
  version_number: 2,
  content_hash: "2".repeat(64),
  verification_status: "pending_review",
  approved_at: null,
  is_current: false,
  extracted_text: "NEW TEXT BODY",
  content_length: 13,
});

const detail = {
  id: "d1",
  source_id: "s1",
  source_title: "Source",
  title: "Doc",
  canonical_url: "https://www.studyinkorea.go.kr/x",
  language: "en",
  document_type: "webpage",
  organization: "Study in Korea",
  category: "visa-immigration",
  current_version_id: "v1",
  pending_version_id: "v2",
  latest_version_number: 2,
  is_canceled: false,
  created_at: "2030-01-01T00:00:00Z",
  source: { id: "s1", title: "Source", organization: "Study in Korea", status: "pending_review" },
  current_version: current,
  pending_version: pending,
  versions: [
    { ...pending, extracted_text: undefined },
    { ...current, extracted_text: undefined },
  ],
  diff: { added_count: 1, removed_count: 1, added_lines: ["new line"], removed_lines: ["old line"], unified: "" },
} as unknown as DocumentDetail;

function handlers() {
  return {
    onApprove: vi.fn(),
    onReject: vi.fn(),
    onRetryExtraction: vi.fn(),
    onReprocess: vi.fn(),
    onRollback: vi.fn(),
    onCancelDocument: vi.fn(),
  };
}

describe("ReviewPanel", () => {
  it("shows the current approved and the proposed version side by side with the diff", () => {
    renderWithIntl(<ReviewPanel detail={detail} handlers={handlers()} />);
    expect(screen.getByText("Current approved version")).toBeInTheDocument();
    expect(screen.getByText("Proposed new version")).toBeInTheDocument();
    expect(screen.getByText("NEW TEXT BODY")).toBeInTheDocument();
    expect(screen.getByText(/new line/)).toBeInTheDocument();
    expect(screen.getByText(/old line/)).toBeInTheDocument();
    expect(screen.getByText("2".repeat(64))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /studyinkorea/ })).toHaveAttribute("href", detail.canonical_url);
  });

  it("calls onApprove with the pending version id", async () => {
    const h = handlers();
    renderWithIntl(<ReviewPanel detail={detail} handlers={h} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(h.onApprove).toHaveBeenCalledWith("v2", "");
  });

  it("requires a reason before rejecting, then calls onReject", async () => {
    const h = handlers();
    renderWithIntl(<ReviewPanel detail={detail} handlers={h} />);
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(h.onReject).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("A reason is required.");
    await userEvent.type(screen.getByLabelText(/Reason/), "Content is outdated");
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(h.onReject).toHaveBeenCalledWith("v2", "Content is outdated");
  });

  it("offers retry extraction and hides approve/reject when nothing is pending", async () => {
    const h = handlers();
    const none = { ...detail, pending_version: null, pending_version_id: null, diff: null } as DocumentDetail;
    renderWithIntl(<ReviewPanel detail={none} handlers={h} />);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByText("No version is waiting for review.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry extraction" }));
    expect(h.onRetryExtraction).toHaveBeenCalled();
  });

  it("allows rollback only to previously approved, non-current versions", async () => {
    const h = handlers();
    const withOld = {
      ...detail,
      current_version: version({ id: "v3", version_number: 3 }),
      versions: [
        { ...version({ id: "v3", version_number: 3 }), extracted_text: undefined },
        { ...version({ id: "v1", version_number: 1, is_current: false, verification_status: "superseded" }), extracted_text: undefined },
        { ...version({ id: "v2", version_number: 2, is_current: false, approved_at: null, verification_status: "rejected" }), extracted_text: undefined },
      ],
      pending_version: null,
    } as unknown as DocumentDetail;
    renderWithIntl(<ReviewPanel detail={withOld} handlers={h} />);
    const buttons = screen.getAllByRole("button", { name: /Roll back/ });
    expect(buttons).toHaveLength(1);
    await userEvent.click(buttons[0]);
    expect(h.onRollback).toHaveBeenCalledWith("v1");
  });
});
