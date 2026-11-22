import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import type { DocTranslationDetail } from "@/types/api";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } };
});

import { ApiError } from "@/lib/api";
import { DocTranslationEditor } from "@/features/admin/translations/doc-translation-editor";

const detail = (over: Partial<DocTranslationDetail> = {}): DocTranslationDetail => ({
  original: { document_id: "d1", version_id: "v2", version_number: 2, title: "Visa and Stay", body: "# Visa\n\nFee 30,000 KRW",
    language: "en", content_hash: "h", headings: ["Visa"], source_url: "https://x.example/v", organization: "NIIED",
    category: "visa-immigration", approved_at: null, is_live: true },
  translation: { id: "t1", document_id: "d1", version_id: "v2", source_version_number: 2, source_content_hash: "h", language_code: "id",
    title: "Visa", headings: ["Visa"], body: "# Visa\n\nBiaya 30.000 KRW", translation_status: "machine_draft", is_outdated: false,
    outdated_at: null, provider: "anthropic", model: "claude-opus-5-5", generated_at: "2026-11-22T00:00:00Z", human_edited: false,
    is_machine_translated: true, warnings: [{ type: "number", value: "30000" }], review_note: null, reviewed_by: null,
    reviewed_by_name: null, reviewed_at: null, last_edited_by: null, last_edited_by_name: null, last_edited_at: null,
    submitted_at: null, previous_translation_id: "t0", updated_at: null, created_at: null, verified: false },
  previous: { translation: { id: "t0", title: "Visa", body: "# Visa\n\nBiaya 20.000 KRW" } as never, original_body: "# Visa\n\nFee 20,000 KRW",
    original_version_number: 1 },
  revisions: [],
  permissions: { can_edit: true, can_review: true, can_generate: true },
  language: "id",
  job: null,
  llm: { enabled: true, provider: "anthropic", model: "claude-opus-5-5" },
  ...over,
});

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("DocTranslationEditor", () => {
  it("shows original and AI draft side by side; approval needs the explicit original check", async () => {
    get.mockResolvedValue(detail());
    renderWithIntl(<DocTranslationEditor documentId="d1" language="id" />);
    expect(await screen.findByTestId("original-body")).toHaveTextContent("Fee 30,000 KRW");
    expect(screen.getByText("AI draft – not reviewed", { selector: "h5,div,p,span,*" })).toBeInTheDocument();
    expect(screen.getByText("Number missing or changed: 30000")).toBeInTheDocument();
    expect(screen.getByText(/The original changed \(version 1 → 2\)/)).toBeInTheDocument();
    const approve = screen.getByRole("button", { name: /Approve and publish/ });
    expect(approve).toBeDisabled();
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: /I checked this translation/ }));
    expect(approve).toBeEnabled();
    post.mockResolvedValue({});
    await user.click(approve);
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/v1/admin/documents/d1/translations/id/approve",
      { original_verified: true, note: undefined }));
    // version comparison: what changed in the original
    await user.click(screen.getByRole("button", { name: /What changed in the original/ }));
    expect(screen.getByTestId("diff")).toHaveTextContent("− Fee 20,000 KRW");
    expect(screen.getByTestId("diff")).toHaveTextContent("+ Fee 30,000 KRW");
  });

  it("explains when the supporter is not assigned to the language", async () => {
    get.mockRejectedValue(new ApiError({ status: 403, code: "forbidden", message: "nope" }));
    renderWithIntl(<DocTranslationEditor documentId="d1" language="vi" />);
    expect(await screen.findByText("Not assigned to this language")).toBeInTheDocument();
  });
});
