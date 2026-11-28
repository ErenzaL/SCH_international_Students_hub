"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ArrowLeft, Ban, Check, Pencil, Send, X } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label, Textarea } from "@/components/ui/input";
import { PublicationBadge, TestDataBadge } from "@/components/shared/badges";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { AnnouncementForm } from "@/features/admin/announcements/announcement-form";
import { AutoTranslationCard } from "@/features/admin/announcements/auto-translation-card";
import { TranslationPanel } from "@/features/admin/announcements/translation-panel";
import { isAdminRole, useMe } from "@/features/admin/shell/admin-context";
import { api, errorMessage } from "@/lib/api";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDate, formatDateTime } from "@/lib/utils";
import type { AdminAnnouncement, AuditEntry } from "@/types/api";

export function AnnouncementAdminDetail({ id }: { id: string }) {
  const t = useTranslations("admin.announcements");
  const e = useTranslations("enums");
  const locale = useLocale();
  const me = useMe();
  const categoryName = useCategoryName();
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const action = useAction();

  const ann = useApi<AdminAnnouncement>(`admin-ann:${id}`, () => api.get<AdminAnnouncement>(`/api/v1/admin/announcements/${id}`));
  const history = useApi<{ items: AuditEntry[] }>(`admin-ann-hist:${id}`, () =>
    api.get<{ items: AuditEntry[] }>(`/api/v1/admin/announcements/${id}/history`),
  );

  const a = ann.data;
  const admin = isAdminRole(me.role);

  async function run(path: string, body: unknown, done: string, needReason = false) {
    if (needReason && !note.trim()) {
      setNoteError(true);
      return;
    }
    setNoteError(false);
    setNotice(null);
    const res = await action.run(() => api.post<AdminAnnouncement>(`/api/v1/admin/announcements/${id}/${path}`, body));
    if (res) {
      setNotice(done);
      setNote("");
      ann.reload();
      history.reload();
    }
  }

  return (
    <div className="space-y-6">
      <Link href="/admin/announcements" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
        <ArrowLeft className="size-4" /> {t("form.back")}
      </Link>
      {ann.loading && <LoadingState rows={3} />}
      {!ann.loading && ann.error && <ErrorState error={ann.error} onRetry={ann.reload} />}
      {notice && <Alert variant="success">{notice}</Alert>}
      {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}

      {a && (
        <>
          <header className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <PublicationBadge status={a.publication_status} />
              {a.is_test_data && <TestDataBadge />}
            </div>
            <h1 className="text-2xl font-bold">{a.title}</h1>
          </header>

          {editing && (a.publication_status === "draft" || a.publication_status === "rejected") ? (
            <AnnouncementForm
              existing={a}
              onSaved={() => {
                setEditing(false);
                setNotice(t("saved"));
                ann.reload();
                history.reload();
              }}
            />
          ) : (
            <>
              <Card>
                <CardContent className="grid gap-4 p-5 text-sm sm:grid-cols-2 lg:grid-cols-3">
                  <Fact label={t("form.category")} value={categoryName(a.category)} />
                  <Fact label={t("form.audience")} value={a.target_audience ?? "—"} />
                  <Fact label={t("form.sourceType")} value={e(`sourceType.${a.source_type}`)} />
                  <Fact label={t("form.eventDate")} value={formatDate(a.event_date, locale)} />
                  <Fact label={t("form.deadline")} value={formatDate(a.deadline, locale)} />
                  <Fact label={t("form.validFrom")} value={formatDate(a.valid_from, locale)} />
                  <Fact label={t("submitter")} value={a.created_by_name ?? "—"} />
                  <Fact label={t("submittedAt")} value={formatDateTime(a.submitted_at ?? a.created_at, locale)} />
                  <Fact label={t("approvedAt")} value={formatDateTime(a.approved_at, locale)} />
                  <div className="sm:col-span-2 lg:col-span-3">
                    <Fact label={t("form.evidenceNote")} value={a.evidence_note ?? "—"} />
                    {a.evidence_url && (
                      <a href={a.evidence_url} target="_blank" rel="noopener noreferrer" className="break-all text-primary hover:underline">
                        {a.evidence_url}
                      </a>
                    )}
                  </div>
                  {a.rejection_reason && (
                    <div className="sm:col-span-2 lg:col-span-3">
                      <Fact label={t("rejectionReason")} value={a.rejection_reason} />
                    </div>
                  )}
                </CardContent>
              </Card>

              <section aria-labelledby="orig-h">
                <h2 id="orig-h" className="mb-2 text-lg font-semibold">
                  {t("originalContent")}
                </h2>
                <div lang={a.original_language} className="whitespace-pre-wrap rounded-lg border border-border bg-card p-4 text-sm leading-relaxed">
                  {a.body}
                </div>
              </section>

              <section aria-labelledby="act-h" className="space-y-3 rounded-xl border border-border bg-card p-5">
                <h2 id="act-h" className="text-lg font-semibold">
                  {t("actions")}
                </h2>
                <div className="flex flex-wrap gap-2">
                  {(a.publication_status === "draft" || a.publication_status === "rejected") && (
                    <>
                      <Button variant="outline" disabled={action.busy} onClick={() => setEditing(true)}>
                        <Pencil /> {t("edit")}
                      </Button>
                      <Button disabled={action.busy} onClick={() => run("submit", {}, t("submittedDone"))}>
                        <Send /> {t("form.submitForApproval")}
                      </Button>
                    </>
                  )}
                  {admin && a.publication_status === "pending_approval" && (
                    <Button disabled={action.busy} onClick={() => run("approve", { note: note.trim() || undefined }, t("approvedDone"))}>
                      <Check /> {t("approve")}
                    </Button>
                  )}
                  {admin && a.publication_status === "pending_approval" && (
                    <Button variant="destructive" disabled={action.busy} onClick={() => run("reject", { reason: note.trim() }, t("rejectedDone"), true)}>
                      <X /> {t("reject")}
                    </Button>
                  )}
                  {/* pending too: withdraws an announcement whose text is already searchable (approved in document review) */}
                  {admin && (a.publication_status === "published" || a.publication_status === "pending_approval") && (
                    <Button variant="outline" disabled={action.busy} onClick={() => run("cancel", { reason: note.trim() }, t("canceledDone"), true)}>
                      <Ban /> {t("cancel")}
                    </Button>
                  )}
                </div>
                {admin && (a.publication_status === "pending_approval" || a.publication_status === "published") && (
                  <div>
                    <Label htmlFor="an-note">{t("noteOrReason")}</Label>
                    <Textarea id="an-note" rows={2} value={note} aria-invalid={noteError} onChange={(ev) => setNote(ev.target.value)} />
                    {noteError && (
                      <p role="alert" className="mt-1 text-xs text-destructive">
                        {t("reasonRequired")}
                      </p>
                    )}
                  </div>
                )}
                {!admin && a.publication_status === "pending_approval" && (
                  <p className="text-sm text-muted-foreground">{t("awaitingAdmin")}</p>
                )}
              </section>
            </>
          )}

          {a.publication_status !== "canceled" && (
            <AutoTranslationCard key={`${a.id}:${(a.translation_targets ?? []).join(",")}:${a.publication_status}`}
              announcement={a} admin={admin} onChanged={() => { ann.reload(); history.reload(); }} />
          )}
          <TranslationPanel announcement={a} onChanged={ann.reload} />

          <section aria-labelledby="hist-h" className="space-y-2">
            <h2 id="hist-h" className="text-lg font-semibold">
              {t("history")}
            </h2>
            {history.loading && <LoadingState rows={1} />}
            {history.error && <ErrorState error={history.error} onRetry={history.reload} />}
            {history.data && history.data.items.length === 0 && <p className="text-sm text-muted-foreground">{t("noHistory")}</p>}
            {history.data && history.data.items.length > 0 && (
              <ol className="space-y-2 border-l-2 border-border pl-4">
                {history.data.items.map((h) => (
                  <li key={h.id} className="text-sm">
                    <span className="font-medium">{h.action}</span> · {h.actor_name ?? h.actor_id ?? "—"}
                    <span className="block text-xs text-muted-foreground">{formatDateTime(h.created_at, locale)}</span>
                    {h.details && Object.keys(h.details).length > 0 && (
                      <span className="block break-words text-xs text-muted-foreground">{JSON.stringify(h.details)}</span>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5">{value}</p>
    </div>
  );
}
