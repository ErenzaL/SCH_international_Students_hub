import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import { AdminProvider } from "@/features/admin/shell/admin-context";
import type { MachineTranslationInfo, Me, TranslationDetail } from "@/types/api";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } };
});

import { TranslationEditor } from "@/features/admin/translations/translation-editor";

const ME: Me = { id: "u1", email: "a@x", display_name: "Admin", role: "admin", preferred_language: "en", languages: ["id"], is_staff: true };
const GPU = { route: "gpu_worker" as const, provider: "ollama", model: "translategemma:12b", fallback_to_gemini: false };

const machine = (over: Partial<MachineTranslationInfo> = {}): MachineTranslationInfo => ({
  state: "ready", machine_made: false, provider: null, model: null, generated_at: null, warnings: [], job: null,
  llm_enabled: true, blocked: null, worker: { enabled: true, online: true, last_seen_at: "2026-11-28T01:00:00Z" },
  executor: null, configured: GPU, poll_seconds: null, ...over,
});

const detail = (m: MachineTranslationInfo, tr: Partial<TranslationDetail["translation"]> = {}): TranslationDetail => ({
  original: { announcement_id: "a1", title: "기숙사 입사 안내", body: "2027년 2월 24일 입사", language: "ko",
    publication_status: "published", version_id: "v1", content_hash: "h", category: "housing", deadline: null,
    event_date: null, is_test_data: false },
  translation: { id: "t1", announcement_id: "a1", language_code: "id", title: "", body: "", translation_status: "todo",
    reviewed_by: null, reviewed_by_name: null, reviewed_at: null, is_machine_translated: false, is_outdated: false,
    published: false, review_note: null, last_edited_by: null, last_edited_by_name: null, last_edited_at: null,
    submitted_at: null, original_verified_at: null, ...tr } as TranslationDetail["translation"],
  revisions: [], permissions: { can_edit: true, can_review: true }, language: "id", machine: m,
});

function show(d: TranslationDetail) {
  get.mockResolvedValue(d);
  return renderWithIntl(<AdminProvider value={ME}><TranslationEditor announcementId="a1" language="id" /></AdminProvider>);
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("Machine translation panel", () => {
  it("a task without a job is ready: the button works (the production 'Queued' + disabled button)", async () => {
    show(detail(machine()));
    expect(await screen.findByTestId("machine-state")).toHaveTextContent("Ready to translate");
    expect(screen.getByTestId("machine-route")).toHaveTextContent("translategemma:12b on the university GPU worker");
    const run = screen.getByTestId("machine-run");
    expect(run).toBeEnabled();
    post.mockResolvedValue({ job_id: "j1", status: "queued" });
    await userEvent.setup().click(run);
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/v1/admin/announcements/a1/translations/id/machine-translate"));
  });

  it("while the GPU worker is offline it says so, offers no button that does nothing, and keeps the job queued", async () => {
    show(detail(machine({ state: "waiting_worker", executor: "gpu", poll_seconds: 30,
      worker: { enabled: true, online: false, last_seen_at: "2026-11-27T01:00:00Z" },
      job: { id: "j1", status: "queued", error_code: null, error_message: null, created_at: "2026-11-28T01:00:00Z", run_after: null } })));
    expect(await screen.findByTestId("machine-state")).toHaveTextContent("Waiting for the GPU worker");
    expect(screen.getByTestId("machine-explain")).toHaveTextContent(/offline .*No paid model is used/);
    expect(screen.queryByTestId("machine-run")).toBeNull();
    expect(screen.getByTestId("machine-refresh")).toBeEnabled();
  });

  it("a blocked request explains why instead of showing a disabled button", async () => {
    show(detail(machine({ blocked: { code: "translation_worker_disabled", message: "x" }, configured: { ...GPU, route: null } })));
    expect(await screen.findByTestId("machine-blocked")).toHaveTextContent(/GPU worker, which is not switched on/);
    expect(screen.queryByTestId("machine-run")).toBeNull();
  });

  it("a stalled job can be resumed safely; an approved translation is protected", async () => {
    const { unmount } = show(detail(machine({ state: "stalled", executor: "local",
      job: { id: "j1", status: "queued", error_code: null, error_message: null, created_at: "2026-11-28T01:00:00Z", run_after: null } })));
    expect(await screen.findByTestId("machine-resume")).toBeEnabled();
    unmount();
    show(detail(machine({ state: "approved", blocked: { code: "translation_approved", message: "x" } }),
      { translation_status: "human_approved", title: "Panduan", body: "Isi", published: true }));
    expect(await screen.findByTestId("machine-blocked")).toHaveTextContent(/protected/);
    expect(screen.queryByTestId("machine-regenerate")).toBeNull();
  });

  it("the finished draft is loaded into the editor for review; replacing it needs a confirmation", async () => {
    show(detail(machine({ state: "needs_review", machine_made: true, provider: "ollama", model: "translategemma:12b",
      generated_at: "2026-11-28T01:05:00Z", warnings: [{ type: "number", value: "24" }] }),
    { translation_status: "needs_review", title: "Panduan masuk asrama", body: "Masuk asrama 24 Februari 2027" }));
    expect(await screen.findByDisplayValue("Panduan masuk asrama")).toBeInTheDocument();
    expect(screen.getByTestId("machine-explain")).toHaveTextContent(/must be reviewed/);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("machine-regenerate"));
    expect(screen.getByText(/replaced by a new one/)).toBeInTheDocument();
    post.mockResolvedValue({ job_id: "j2", status: "queued" });
    await user.click(screen.getByRole("button", { name: "Replace the draft" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/v1/admin/announcements/a1/translations/id/machine-translate?force=true"));
  });
});
