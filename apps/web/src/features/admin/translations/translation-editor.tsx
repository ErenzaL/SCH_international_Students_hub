"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, ArrowLeft, Bot, Check, ClipboardCopy, MessageSquareWarning, RotateCcw, Save, Send, XCircle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Label, Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { PublicationBadge, TestDataBadge } from "@/components/shared/badges";
import { TranslationStateBadge } from "@/features/admin/translations/translation-state-badge";
import { api, ApiError, errorMessage } from "@/lib/api";
import { LOCALE_LABELS } from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { formatDate, formatDateTime } from "@/lib/utils";
import type { LanguageCode, MachineTranslationInfo, TranslationDetail } from "@/types/api";

/** Original announcement next to the draft; save / submit / approve / reject / request changes. */
export function TranslationEditor({ announcementId, language }: { announcementId: string; language: LanguageCode }) {
  const t = useTranslations("admin.trreview");
  const locale = useLocale();
  const base = `/api/v1/admin/announcements/${announcementId}/translations/${language}`;
  const { data, error, loading, reload } = useApi<TranslationDetail>(`tr:${announcementId}:${language}`, () =>
    api.get<TranslationDetail>(base),
  );
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [verified, setVerified] = useState(false);
  const [note, setNote] = useState("");
  const [dialog, setDialog] = useState<null | "reject" | "changes">(null);
  const [reason, setReason] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const action = useAction();

  useEffect(() => {
    if (data?.translation) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- the loaded draft fills the editor
      setTitle(data.translation.title);
      setBody(data.translation.body);
    }
    setVerified(false);
  }, [data]);

  if (loading && !data) return <LoadingState rows={4} />;
  if (error && !data) {
    if (error instanceof ApiError && error.status === 403) {
      return (
        <Alert variant="destructive">
          <AlertTitle>{t("notAssignedTitle")}</AlertTitle>
          <AlertDescription>{t("notAssignedBody", { language: LOCALE_LABELS[language] ?? language })}</AlertDescription>
        </Alert>
      );
    }
    return <ErrorState error={error} onRetry={reload} />;
  }
  if (!data) return null;
  const { original, translation: tr, permissions, revisions } = data;
  const hasDraft = Boolean(tr && tr.translation_status !== "todo");
  const dirty = !tr || title !== tr.title || body !== tr.body;
  const reviewable = hasDraft && !tr!.is_outdated && tr!.translation_status !== "human_approved" && tr!.translation_status !== "rejected";

  async function save(submit: boolean) {
    setDone(null);
    const res = await action.run(() =>
      api.put(base, { title: title.trim(), body, translation_status: submit ? "in_review" : "machine_draft" }),
    );
    if (res) {
      setDone(submit ? t("submittedDone") : t("savedDone"));
      reload();
    }
  }
  async function review(path: "approve" | "reject" | "request-changes", payload: Record<string, unknown>) {
    setDone(null);
    const res = await action.run(() => api.post(`${base}/${path}`, payload));
    if (res) {
      setDone(t(`${path === "request-changes" ? "changesDone" : path === "approve" ? "approvedDone" : "rejectedDone"}`));
      setDialog(null);
      setReason("");
      reload();
    }
  }
  async function copyForKakao() {
    const res = await action.run(() => api.get<{ text: string }>(`${base}/share-text`));
    if (!res) return;
    try {
      await navigator.clipboard.writeText(res.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    } catch {
      setDone(res.text); // clipboard blocked: show the text so it can be copied manually
    }
  }

  return (
    <div className="space-y-5">
      <Button asChild variant="ghost" size="sm">
        <Link href="/admin/translations">
          <ArrowLeft /> {t("back")}
        </Link>
      </Button>
      <PageHeader
        title={t("editorTitle", { language: LOCALE_LABELS[language] })}
        description={original.title}
        actions={tr ? <TranslationStateBadge translation={tr} /> : undefined}
      />
      {tr?.is_outdated && (
        <Alert variant="warning">
          <AlertTriangle className="size-4" aria-hidden />
          <AlertTitle>{t("outdatedTitle")}</AlertTitle>
          <AlertDescription>{t("outdatedBody")}</AlertDescription>
        </Alert>
      )}
      {original.publication_status !== "published" && (
        <Alert variant="info">
          <AlertDescription>{t("originalNotPublished")}</AlertDescription>
        </Alert>
      )}
      {tr?.review_note && (
        <Alert variant={tr.translation_status === "rejected" ? "destructive" : "warning"}>
          <MessageSquareWarning className="size-4" aria-hidden />
          <AlertTitle>{t("reviewNote")}</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{tr.review_note}</AlertDescription>
        </Alert>
      )}
      {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
      {done && <Alert variant="success" className="whitespace-pre-wrap">{done}</Alert>}
      {data.machine && original.language !== language && (
        <MachinePanel info={data.machine} canRun={permissions.can_edit || permissions.can_review}
          published={original.publication_status === "published"} busy={action.busy}
          onRun={async () => {
            setDone(null);
            const res = await action.run(() => api.post(`${base}/machine-translate`));
            if (res) {
              setDone(t("machine.queued"));
              reload();
            }
          }} />
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2 text-base">
              {t("original", { language: LOCALE_LABELS[original.language] })}
              <PublicationBadge status={original.publication_status} />
              {original.is_test_data && <TestDataBadge />}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm" lang={original.language}>
            <p className="font-semibold">{original.title}</p>
            <p className="whitespace-pre-wrap">{original.body}</p>
            {(original.deadline || original.event_date) && (
              <p className="text-xs text-muted-foreground">
                {original.deadline && `${t("deadline")}: ${formatDate(original.deadline, locale)} `}
                {original.event_date && `${t("eventDate")}: ${formatDate(original.event_date, locale)}`}
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("translation", { language: LOCALE_LABELS[language] })}</CardTitle>
            {tr?.last_edited_at && (
              <p className="text-xs text-muted-foreground">
                {t("editedBy", { name: tr.last_edited_by_name ?? "—", date: formatDateTime(tr.last_edited_at, locale) })}
              </p>
            )}
            {tr?.reviewed_at && (
              <p className="text-xs text-muted-foreground">
                {t("reviewedBy", { name: tr.reviewed_by_name ?? "—", date: formatDateTime(tr.reviewed_at, locale) })}
              </p>
            )}
          </CardHeader>
          <CardContent className="space-y-3">
            {!permissions.can_edit && <p className="text-xs text-muted-foreground">{t("readOnly")}</p>}
            <div className="space-y-1.5">
              <Label htmlFor="tre-title">{t("fieldTitle")}</Label>
              <Input id="tre-title" lang={language} value={title} disabled={!permissions.can_edit} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tre-body">{t("fieldBody")}</Label>
              <Textarea id="tre-body" lang={language} rows={12} value={body} disabled={!permissions.can_edit} onChange={(e) => setBody(e.target.value)} />
            </div>
            {permissions.can_edit && (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" disabled={action.busy || !title.trim() || !body.trim()} onClick={() => save(false)}>
                  <Save /> {t("saveDraft")}
                </Button>
                <Button disabled={action.busy || !title.trim() || !body.trim()} onClick={() => save(true)}>
                  <Send /> {t("submit")}
                </Button>
              </div>
            )}
            {tr?.published && (
              <Button variant="secondary" disabled={action.busy} onClick={copyForKakao}>
                <ClipboardCopy /> {copied ? t("copied") : t("copyKakao")}
              </Button>
            )}
          </CardContent>
        </Card>
      </div>

      {permissions.can_review && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("reviewTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {!hasDraft && <p className="text-sm text-muted-foreground">{t("nothingToReview")}</p>}
            {hasDraft && dirty && <p className="text-sm text-amber-800">{t("unsavedChanges")}</p>}
            {hasDraft && (
              <>
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-1" checked={verified} onChange={(e) => setVerified(e.target.checked)} />
                  <span>{t("verifyOriginal")}</span>
                </label>
                <div className="space-y-1.5">
                  <Label htmlFor="tre-note">{t("approvalNote")}</Label>
                  <Input id="tre-note" maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    disabled={action.busy || !verified || !reviewable || dirty || original.publication_status !== "published"}
                    onClick={() => review("approve", { original_verified: true, note: note.trim() || undefined })}
                  >
                    <Check /> {t("approve")}
                  </Button>
                  <Button variant="outline" disabled={action.busy || !reviewable} onClick={() => setDialog("changes")}>
                    <MessageSquareWarning /> {t("requestChanges")}
                  </Button>
                  <Button variant="outline" disabled={action.busy || !reviewable} onClick={() => setDialog("reject")}>
                    <XCircle /> {t("reject")}
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("history")}</CardTitle>
        </CardHeader>
        <CardContent>
          {revisions.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noHistory")}</p>
          ) : (
            <ol className="space-y-2 text-sm">
              {revisions.map((r) => (
                <li key={r.id} className="rounded-md border border-border p-2">
                  <p className="font-medium">
                    {t(`action.${r.action}`)} · {r.actor_name || t("system")}
                  </p>
                  <p className="text-xs text-muted-foreground">{formatDateTime(r.created_at, locale)}</p>
                  {r.note && <p className="mt-1 whitespace-pre-wrap text-xs">{r.note}</p>}
                  {r.title && (
                    <p className="mt-1 truncate text-xs text-muted-foreground" lang={language}>
                      {r.title}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialog !== null} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent closeLabel={t("cancel")}>
          <DialogHeader>
            <DialogTitle>{dialog === "reject" ? t("rejectTitle") : t("changesTitle")}</DialogTitle>
            <DialogDescription>{dialog === "reject" ? t("rejectBody") : t("changesBody")}</DialogDescription>
          </DialogHeader>
          <Label htmlFor="tre-reason">{t("reason")}</Label>
          <Textarea id="tre-reason" rows={3} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              {t("cancel")}
            </Button>
            <Button
              variant={dialog === "reject" ? "destructive" : "default"}
              disabled={action.busy || reason.trim().length < 3}
              onClick={() => review(dialog === "reject" ? "reject" : "request-changes", { reason: reason.trim() })}
            >
              {dialog === "reject" ? t("reject") : t("requestChanges")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** Automatic machine translation for this language: status, model, automated checks and a retry button. */
function MachinePanel({ info, canRun, published, busy, onRun }: {
  info: MachineTranslationInfo; canRun: boolean; published: boolean; busy: boolean; onRun: () => void;
}) {
  const t = useTranslations("admin.trreview.machine");
  const tw = useTranslations("admin.doctr.warning");
  const locale = useLocale();
  const running = info.state === "pending" || info.state === "processing";
  return (
    <Card data-testid="machine-panel">
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <Bot className="size-4 text-primary" aria-hidden /> {t("title")}
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium" data-testid="machine-state">{t(`state.${info.state}`)}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {info.generated_at && (
          <p className="text-muted-foreground">
            {t("generated", { date: formatDateTime(info.generated_at, locale), model: info.model ?? info.provider ?? "?" })}
          </p>
        )}
        {info.job?.status === "failed" && info.job.error_message && (
          <p className="text-destructive">{t("failed", { error: info.job.error_message })}</p>
        )}
        {info.job?.status === "queued" && info.job.error_code && (
          <p className="text-muted-foreground">{t("waiting", { error: info.job.error_message ?? info.job.error_code })}</p>
        )}
        {info.warnings.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-5 text-amber-800 dark:text-amber-300">
            {info.warnings.map((w, i) => <li key={i}>{tw.has(w.type) ? tw(w.type, { value: w.value }) : `${w.type}: ${w.value}`}</li>)}
          </ul>
        )}
        {!info.llm_enabled ? (
          <p className="text-muted-foreground">{t("disabled")}</p>
        ) : canRun && published && info.state !== "approved" && info.state !== "human_draft" && (
          <Button size="sm" variant="outline" disabled={busy || running} onClick={onRun} data-testid="machine-run">
            <RotateCcw /> {info.state === "missing" || (info.state === "pending" && !info.job) ? t("run") : t("retry")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
