import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import type { SourceDeletionCheck } from "@/types/api";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } };
});

import { DeleteSourceDialog } from "@/features/admin/knowledge/source-lifecycle-actions";

const source = { id: "s1", title: "Old visa page" };
const check = (over: Partial<SourceDeletionCheck> = {}): SourceDeletionCheck => ({
  eligible: true,
  blockers: [],
  title: "Old visa page",
  organization: "Hi Korea",
  source_type: "website",
  is_active: false,
  is_archived: true,
  documents: 2,
  published_documents: 0,
  versions: 3,
  approved_versions: 1,
  chunks: 7,
  indexed_chunks: 7,
  searchable_chunks: 0,
  is_searchable: false,
  jobs: 4,
  queued_jobs: 1,
  running_jobs: 0,
  storage_files: [],
  requires_destructive_confirmation: true,
  recommended_action: "archive",
  ...over,
});

function setup(c: SourceDeletionCheck) {
  get.mockResolvedValue(c);
  const props = { onClose: vi.fn(), onDeleted: vi.fn(), onArchived: vi.fn() };
  renderWithIntl(<DeleteSourceDialog source={source} {...props} />);
  return props;
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("DeleteSourceDialog", () => {
  it("shows the impact summary and requires title, reason and the second confirmation", async () => {
    const props = setup(check());
    const summary = await screen.findByTestId("source-delete-summary");
    expect(get).toHaveBeenCalledWith("/api/v1/admin/sources/s1/deletion-check");
    expect(summary).toHaveTextContent("Hi Korea");
    expect(summary).toHaveTextContent("Approved versions1");
    expect(summary).toHaveTextContent("Indexed chunks7");
    expect(summary).toHaveTextContent("Currently searchableNo");
    const del = screen.getByRole("button", { name: /delete permanently/i });
    expect(del).toBeDisabled();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/reason/i), "duplicate of the official page");
    await user.type(screen.getByLabelText(/exact source title/i), "Old visa page");
    expect(del).toBeDisabled(); // second explicit confirmation still missing
    await user.click(screen.getByTestId("confirm-destructive"));
    expect(del).toBeEnabled();

    post.mockResolvedValue({ deleted: true, title: "Old visa page", documents: 2, versions: 3, chunks: 7, jobs_kept: 4,
      queued_jobs_canceled: 1, files_removed: 0, files_failed: [] });
    await user.click(del);
    await waitFor(() => expect(props.onDeleted).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith("/api/v1/admin/sources/s1/delete", {
      reason: "duplicate of the official page",
      confirm_title: "Old visa page",
      confirm_destructive: true,
    });
    expect(await screen.findByText("Source deleted")).toBeInTheDocument();
    expect(screen.getByText("2 documents removed")).toBeInTheDocument();
  });

  it("recommends Archive for live content and explains the blocker", async () => {
    const props = setup(check({ eligible: false, is_archived: false, is_active: true, published_documents: 1,
      is_searchable: true, searchable_chunks: 7, blockers: ["published: 1 document(s) are live; withdraw..."] }));
    expect(await screen.findByText(/1 document is published/)).toBeInTheDocument();
    expect(screen.getByText(/Recommended: archive this source/)).toBeInTheDocument();
    expect(screen.getByText(/Yes – 7 chunks are live in search/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/exact source title/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete permanently/i })).toBeDisabled();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/reason/i), "replaced by new source");
    post.mockResolvedValue({});
    await user.click(screen.getByRole("button", { name: /archive instead/i }));
    await waitFor(() => expect(props.onArchived).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith("/api/v1/admin/sources/s1/archive", { reason: "replaced by new source" });
  });

  it("deletes an unused source without the destructive checkbox and shows server errors", async () => {
    setup(check({ documents: 0, versions: 0, approved_versions: 0, chunks: 0, indexed_chunks: 0,
      requires_destructive_confirmation: false, recommended_action: "delete", is_archived: false }));
    await screen.findByTestId("source-delete-summary");
    expect(screen.queryByTestId("confirm-destructive")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /archive instead/i })).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/reason/i), "created by mistake");
    await user.type(screen.getByLabelText(/exact source title/i), "Old visa page");
    post.mockRejectedValue(new Error("Not permitted by database policy."));
    await user.click(screen.getByRole("button", { name: /delete permanently/i }));
    expect(await screen.findByText("Not permitted by database policy.")).toBeInTheDocument();
  });
});
