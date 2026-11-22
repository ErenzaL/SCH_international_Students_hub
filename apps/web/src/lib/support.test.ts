import { describe, expect, it } from "vitest";
import {
  buildHandoffPayload,
  defaultSelection,
  defaultSubject,
  defaultSummary,
  notificationHref,
  PRIORITY_VARIANT,
  shouldPollTicket,
  studentCanReply,
  TICKET_STATUS_VARIANT,
  translationBadge,
  type HandoffDraft,
} from "@/lib/support";

const base: HandoffDraft = {
  language: "vi",
  subject: "Visa extension",
  summary: "How do I extend my D-2 visa?",
  conversationId: "c1",
  selectedIds: ["m1", "m2"],
  availableIds: ["m1", "m2", "m3"],
  consent: true,
};

describe("buildHandoffPayload", () => {
  it("builds exactly the documented body", () => {
    const r = buildHandoffPayload({ ...base, additional: "  please help  " });
    expect(r).toEqual({
      ok: true,
      body: {
        language: "vi",
        subject: "Visa extension",
        summary: "How do I extend my D-2 visa?",
        message_ids: ["m1", "m2"],
        consent: true,
        conversation_id: "c1",
        additional_message: "please help",
      },
    });
  });

  it("requires consent and never builds a body without it", () => {
    const r = buildHandoffPayload({ ...base, consent: false });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors).toContain("consent");
  });

  it("validates language, subject and summary", () => {
    const r = buildHandoffPayload({ ...base, language: "", subject: "ab", summary: "   " });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors).toEqual(expect.arrayContaining(["language", "subject", "summary"]));
    const long = buildHandoffPayload({ ...base, summary: "x".repeat(4001) });
    expect(long.ok).toBe(false);
  });

  it("rejects sharing messages from a private conversation", () => {
    const r = buildHandoffPayload({ ...base, isPrivate: true });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors).toContain("private");
  });

  it("omits conversation_id and messages for a private conversation with nothing selected", () => {
    const r = buildHandoffPayload({ ...base, isPrivate: true, selectedIds: [] });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.body.message_ids).toEqual([]);
      expect(r.body).not.toHaveProperty("conversation_id");
    }
  });

  it("rejects ids that are not in the conversation and dedupes the rest", () => {
    const bad = buildHandoffPayload({ ...base, selectedIds: ["m1", "evil"] });
    expect(bad.ok).toBe(false);
    if (!bad.ok) expect(bad.errors).toContain("selection");
    const dup = buildHandoffPayload({ ...base, selectedIds: ["m1", "m1", "m3"] });
    expect(dup.ok && dup.body.message_ids).toEqual(["m1", "m3"]);
  });

  it("sends no conversation fields without a conversation", () => {
    const r = buildHandoffPayload({ ...base, conversationId: null, availableIds: undefined });
    expect(r.ok && r.body.message_ids).toEqual([]);
    expect(r.ok && "conversation_id" in r.body).toBe(false);
  });
});

describe("handoff defaults", () => {
  const msgs = [
    { id: "u1", role: "user" as const, content: "first" },
    { id: "a1", role: "assistant" as const, content: "answer 1" },
    { id: "u2", role: "user" as const, content: "  second\n question " },
    { id: "a2", role: "assistant" as const, content: "answer 2" },
  ];
  it("selects all user messages and the latest assistant answer", () => {
    expect(defaultSelection(msgs)).toEqual(["u1", "u2", "a2"]);
  });
  it("summarises the last user question", () => {
    expect(defaultSummary(msgs)).toBe("second question");
    expect(defaultSummary([])).toBe("");
  });
  it("truncates long subjects with an ellipsis", () => {
    expect(defaultSubject("short")).toBe("short");
    const s = defaultSubject("word ".repeat(40));
    expect(s.length).toBeLessThanOrEqual(80);
    expect(s.endsWith("…")).toBe(true);
  });
});

describe("ticket helpers", () => {
  it("has a badge variant for every status and priority", () => {
    expect(Object.keys(TICKET_STATUS_VARIANT).sort()).toEqual(
      ["assigned", "open", "resolved", "waiting", "waiting_for_student"].sort(),
    );
    expect(Object.keys(PRIORITY_VARIANT).sort()).toEqual(["high", "low", "normal", "urgent"]);
  });
  it("lets students reply until resolved", () => {
    expect(studentCanReply("waiting")).toBe(true);
    expect(studentCanReply("resolved")).toBe(false);
  });
  it("polls only open tickets while the tab is visible", () => {
    expect(shouldPollTicket("open", true)).toBe(true);
    expect(shouldPollTicket("open", false)).toBe(false);
    expect(shouldPollTicket("resolved", true)).toBe(false);
    expect(shouldPollTicket(undefined, true)).toBe(false);
  });
});

describe("translationBadge", () => {
  it("shows outdated first, except for untranslated tasks", () => {
    expect(translationBadge({ translation_status: "human_approved", is_outdated: true, published: true }).key).toBe("outdated");
    expect(translationBadge({ translation_status: "todo", is_outdated: true }).key).toBe("todo");
  });
  it("distinguishes approved from published", () => {
    expect(translationBadge({ translation_status: "human_approved", published: true }).key).toBe("published");
    expect(translationBadge({ translation_status: "human_approved", published: false }).key).toBe("human_approved");
  });
  it("maps workflow statuses", () => {
    expect(translationBadge({ translation_status: "changes_requested" })).toEqual({ key: "changes_requested", variant: "warning" });
    expect(translationBadge({ translation_status: "machine_draft" }).key).toBe("machine_draft");
  });
});

describe("notificationHref", () => {
  it("keeps same-site links", () => {
    expect(notificationHref({ link: "/support/requests/1", entity_type: null, entity_id: null })).toBe("/support/requests/1");
  });
  it("never follows external or protocol-relative links", () => {
    expect(notificationHref({ link: "https://evil.example", entity_type: null, entity_id: null })).toBeNull();
    expect(notificationHref({ link: "//evil.example", entity_type: null, entity_id: null })).toBeNull();
    expect(notificationHref({ link: "/\\evil.example", entity_type: null, entity_id: null })).toBeNull();
  });
  it("falls back to the ticket page for the viewer's side", () => {
    const n = { link: null, entity_type: "support_ticket", entity_id: "t1" };
    expect(notificationHref(n)).toBe("/support/requests/t1");
    expect(notificationHref(n, true)).toBe("/admin/support/t1");
  });
});
