"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, ArrowLeft, Bot, Check, ExternalLink, GitCompare, Loader2, MessageSquareWarning, Save, Send, XCircle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Label, Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { api, ApiError, errorMessage } from "@/lib/api";
import { LOCALE_LABELS } from "@/lib/constants";
import { DOC_TR_VARIANT, docTranslationState, lineDiff, type DiffOp } from "@/lib/doc-translation";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import type { DocTranslationDetail, LanguageCode } from "@/types/api";

export function DocTranslationEditor({ documentId, language }: { documentId: string; language: LanguageCode }) {
  const t = useTranslations("admin.doctr");
  const locale = useLocale();
  const base = `/api/v1/admin/documents/${encodeURIComponent(documentId)}/translations/${language}`;
  const [key, setKey] = useState(0);
  const { data, error, loading, reload } = useApi<DocTranslationDetail>(`doctr-ed:${documentId}:${language}:${key}`, () =>
    api.get<DocTranslationDetail>(base),
  );
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [verified, setVerified] = useState(false);
  const [note, setNote] = useState("");
  const [dialog, setDialog] = useState<null | "reject" | "changes">(null);
  const [reason, setReason] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [compare, setCompare] = useState<null | { label: string; ops: DiffOp[] }>(null);
  const action = useAction();
  const jobActive = !!data?.job && (data.job.status === "queued" || data.job.status === "running");

  useEffect(() => {
    if (data?.translation) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- the loaded draft fills the editor
      setTitle(data.translation.title);
      setBody(data.translation.body ?? "");
    }
    setVerified(false);
  }, [data]);

  useEffect(() => {
    if (!jobActive) return;
    const id = setInterval(() => setKey((k) => k + 1), 3000);
    return () => clearInterval(id);
  }, [jobActive]);

  const origDiff = useMemo(
    () => (data?.previous?.original_body != null ? lineDiff(data.previous.original_body, data.original.body) : null),
    [data],
  );

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
  const { original, translation: tr, permissions, revisions, previous } = data;
  const state = docTranslationState(tr);
  const hasDraft = Boolean(tr && tr.translation_status !== "todo");
  const dirty = !tr || title !== tr.title || body !== (tr.body ?? "");
  const reviewable = hasDraft && !tr!.is_outdated && tr!.translation_status !== "human_approved";

  async function save(submit: boolean) {
    setDone(null);
    const res = await action.run(() => api.put(base, { title: title.trim(), body, submit }));
    if (res) {
      setDone(submit ? t("submittedDone") : t("savedDone"));
      setKey((k) => k + 1);
    }
  }
  async function review(path: "approve" | "reject" | "request-changes", payload: Record<string, unknown>) {
    setDone(null);
    const res = await action.run(() => api.post(`${base}/${path}`, payload));
    if (res) {
      setDone(t(path === "approve" ? "approvedDone" : path === "reject" ? "rejectedDone" : "changesDone"));
      setDialog(null);
      setReason("");
      setKey((k) => k + 1);
    }
  }
  async function generate() {
    setDone(null);
    const res = await action.run(() =>
      api.post(`/api/v1/admin/documents/${encodeURIComponent(documentId)}/translations/drafts`, {
        languages: [language],
        force: hasDraft && tr!.translation_status !== "machine_draft",
      }),
    );
    if (res) {
      setDone(t("draftsQueued", { count: 1 }));
      setKey((k) => k + 1);
    }
  }

  return (
    <div className="space-y-5">
      <Button asChild variant="ghost" size="sm">
        <Link href="/admin/translations?kind=documents">
          <ArrowLeft /> {t("back")}
        </Link>
      </Button>
      <PageHeader
        title={t("editorTitle", { language: LOCALE_LABELS[language] })}
        description={original.title}
        actions={
          <Badge variant={state === "outdated" || state === "none" ? "warning" : DOC_TR_VARIANT[state]}>{t(`state.${state}`)}</Badge>
        }
      />
      {!original.is_live && (
        <Alert variant="info"><AlertDescription>{t("notLive")}</AlertDescription></Alert>
      )}
      {tr?.is_machine_translated && (
        <Alert variant="info">
          <Bot className="size-4" aria-hidden />
          <AlertTitle>{t("machineTitle")}</AlertTitle>
          <AlertDescription>{t("machineBody", { model: `${tr.provider ?? ""}:${tr.model ?? ""}` })}</AlertDescription>
        </Alert>
      )}
      {previous && (
        <Alert variant="warning">
          <AlertTriangle className="size-4" aria-hidden />
          <AlertTitle>{t("updatedOriginalTitle", { from: previous.original_version_number, to: original.version_number })}</AlertTitle>
          <AlertDescription>{t("updatedOriginalBody")}</AlertDescription>
        </Alert>
      )}
      {tr?.review_note && (
        <Alert variant={tr.translation_status === "rejected" ? "destructive" : "warning"}>
          <MessageSquareWarning className="size-4" aria-hidden />
          <AlertTitle>{t("reviewNote")}</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{tr.review_note}</AlertDescription>
        </Alert>
      )}
      {jobActive && (
        <Alert variant="info" aria-live="polite">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          <AlertDescription>{t("generating")}</AlertDescription>
        </Alert>
      )}
      {data.job?.status === "failed" && (
        <Alert variant="destructive">
          <AlertDescription>{t("generationFailed", { error: data.job.error_message ?? data.job.error_code ?? "" })}</AlertDescription>
        </Alert>
      )}
      {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
      {done && <Alert variant="success">{done}</Alert>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t("original", { language: LOCALE_LABELS[original.language], version: original.version_number })}
            </CardTitle>
            {original.source_url && (
              <a href={original.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 break-all text-xs text-primary hover:underline">
                <ExternalLink className="size-3" aria-hidden /> {original.source_url}
              </a>
            )}
          </CardHeader>
          <CardContent className="space-y-2 text-sm" lang={original.language}>
            <p className="font-semibold">{original.title}</p>
            <div className="max-h-[36rem] overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-muted/30 p-3" data-testid="original-body">
              {original.body}
            </div>
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
              <Label htmlFor="dte-title">{t("fieldTitle")}</Label>
              <Input id="dte-title" lang={language} value={title} disabled={!permissions.can_edit || jobActive} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="dte-body">{t("fieldBody")}</Label>
              <Textarea id="dte-body" lang={language} rows={18} value={body} disabled={!permissions.can_edit || jobActive} onChange={(e) => setBody(e.target.value)} />
              <p className="text-xs text-muted-foreground">{t("bodyHint")}</p>
            </div>
            {tr && tr.warnings.length > 0 && (
              <Alert variant="warning">
                <AlertTriangle className="size-4" aria-hidden />
                <AlertTitle>{t("warningsTitle")}</AlertTitle>
                <AlertDescription>
                  <ul className="list-disc pl-5 text-xs">
                    {tr.warnings.map((w, i) => (
                      <li key={i}>{t(`warning.${w.type}`, { value: w.value })}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}
            <div className="flex flex-wrap gap-2">
              {permissions.can_edit && (
                <>
                  <Button variant="outline" disabled={action.busy || jobActive || !title.trim() || !body.trim()} onClick={() => save(false)}>
                    <Save /> {t("saveDraft")}
                  </Button>
                  <Button disabled={action.busy || jobActive || !title.trim() || !body.trim()} onClick={() => save(true)}>
                    <Send /> {t("submit")}
                  </Button>
                </>
              )}
              {permissions.can_generate && data.llm.enabled && (
                <Button variant="secondary" disabled={action.busy || jobActive} onClick={generate}>
                  <Bot /> {hasDraft ? t("regenerate") : t("generateOne")}
                </Button>
              )}
            </div>
            {permissions.can_generate && !data.llm.enabled && <p className="text-xs text-muted-foreground">{t("aiDisabled")}</p>}
          </CardContent>
        </Card>
      </div>

      {(previous || revisions.some((r) => r.body)) && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><GitCompare className="size-4" aria-hidden /> {t("compareTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex flex-wrap gap-2">
              {origDiff && previous && (
                <Button size="sm" variant="outline" onClick={() => setCompare({ label: t("compareOriginal", { from: previous.original_version_number, to: original.version_number }), ops: origDiff })}>
                  {t("compareOriginal", { from: previous.original_version_number, to: original.version_number })}
                </Button>
              )}
              {previous?.translation.body && (
                <Button size="sm" variant="outline" onClick={() => setCompare({ label: t("comparePrevious"), ops: lineDiff(previous.translation.body ?? "", body) })}>
                  {t("comparePrevious")}
                </Button>
              )}
              {previous?.translation.body && permissions.can_edit && !hasDraft && (
                <Button size="sm" variant="ghost" onClick={() => { setTitle(previous.translation.title); setBody(previous.translation.body ?? ""); }}>
                  {t("startFromPrevious")}
                </Button>
              )}
            </div>
            {compare && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">{compare.label}</p>
                <pre className="max-h-96 overflow-auto rounded-md border border-border p-2 text-xs leading-5" data-testid="diff">
                  {compare.ops.map((o, i) => (
                    <div key={i} className={o.op === "add" ? "bg-emerald-500/15" : o.op === "del" ? "bg-red-500/15 line-through" : ""}>
                      {o.op === "add" ? "+ " : o.op === "del" ? "− " : "  "}
                      {o.text}
                    </div>
                  ))}
                </pre>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {permissions.can_review && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("reviewTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {!hasDraft && <p className="text-sm text-muted-foreground">{t("nothingToReview")}</p>}
            {hasDraft && dirty && <p className="text-sm text-amber-800 dark:text-amber-300">{t("unsavedChanges")}</p>}
            {hasDraft && (
              <>
                <label className="flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-1" checked={verified} onChange={(e) => setVerified(e.target.checked)} />
                  <span>{t("verifyOriginal")}</span>
                </label>
                <div className="space-y-1.5">
                  <Label htmlFor="dte-note">{t("approvalNote")}</Label>
                  <Input id="dte-note" maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button disabled={action.busy || !verified || !reviewable || dirty} onClick={() => review("approve", { original_verified: true, note: note.trim() || undefined })}>
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
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium">
                      {t(`action.${r.action}`)} · {r.actor_name || t("system")}
                      {r.model && <span className="ml-1 text-xs text-muted-foreground">({r.model})</span>}
                    </p>
                    {r.body && (
                      <Button size="sm" variant="ghost" onClick={() => setCompare({ label: t("compareRevision", { date: formatDateTime(r.created_at, locale) }), ops: lineDiff(r.body ?? "", body) })}>
                        <GitCompare /> {t("compareWithCurrent")}
                      </Button>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">{formatDateTime(r.created_at, locale)}</p>
                  {r.note && <p className="mt-1 whitespace-pre-wrap text-xs">{r.note}</p>}
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
          <Label htmlFor="dte-reason">{t("reason")}</Label>
          <Textarea id="dte-reason" rows={3} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>{t("cancel")}</Button>
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
