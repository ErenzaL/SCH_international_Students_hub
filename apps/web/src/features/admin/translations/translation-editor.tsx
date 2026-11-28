"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, ArrowLeft, Bot, Check, ClipboardCopy, MessageSquareWarning, RefreshCw, RotateCcw, Save, Send, XCircle } from "lucide-react";
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
import { isAdminRole, useMe } from "@/features/admin/shell/admin-context";
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
  const me = useMe();
  // what the server sent last: a refresh (while the machine works) replaces the fields only if nobody typed meanwhile
  const loaded = useRef<{ title: string; body: string } | null>(null);
  const lastState = useRef<string | null>(null);

  useEffect(() => {
    if (data?.translation) {
      const prev = loaded.current;
      const next = { title: data.translation.title, body: data.translation.body };
      const changed = !prev || prev.title !== next.title || prev.body !== next.body;
      setTitle((cur) => (!prev || cur === prev.title ? next.title : cur));
      setBody((cur) => (!prev || cur === prev.body ? next.body : cur));
      loaded.current = next;
      if (changed) setVerified(false);
    }
    const state = data?.machine?.state ?? null;
    if (lastState.current && (lastState.current === "processing" || lastState.current === "pending")
        && (state === "completed" || state === "needs_review")) {
      setDone(t("machine.ready"));
    }
    lastState.current = state;
  }, [data, t]);

  // the server says how often to look again while it works (queued / translating / waiting for the GPU worker)
  const poll = data?.machine?.poll_seconds ?? null;
  useEffect(() => {
    if (!poll) return;
    const timer = setInterval(() => reload(), poll * 1000);
    return () => clearInterval(timer);
  }, [poll, reload]);

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
        <MachinePanel info={data.machine} canRun={permissions.can_edit || permissions.can_review || isAdminRole(me.role)}
          canReplace={permissions.can_review || me.role === "super_admin"} busy={action.busy}
          onRun={async (force: boolean) => {
            setDone(null);
            const res = await action.run(() => api.post(`${base}/machine-translate${force ? "?force=true" : ""}`));
            if (res) {
              setDone(t("machine.queued"));
              reload();
            }
          }}
          onRefresh={reload} />
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
                    {t.has(`action.${r.action}`) ? t(`action.${r.action}`) : r.action} · {r.actor_name || t("system")}
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

const RUNNING = ["pending", "processing", "waiting_worker", "quota", "retrying"];

/** Machine translation for this language: where it runs, what the job is doing right now, why a request is not
 *  possible, automated checks, and the actions that are safe in this state. */
function MachinePanel({ info, canRun, canReplace, busy, onRun, onRefresh }: {
  info: MachineTranslationInfo; canRun: boolean; canReplace: boolean; busy: boolean;
  onRun: (force: boolean) => void; onRefresh: () => void;
}) {
  const t = useTranslations("admin.trreview.machine");
  const tw = useTranslations("admin.doctr.warning");
  const locale = useLocale();
  const [confirm, setConfirm] = useState(false);
  const job = info.job;
  const model = info.configured?.model ?? info.model ?? "—";
  const blocked = info.blocked ?? null;
  const running = RUNNING.includes(info.state);
  const when = (d?: string | null) => (d ? formatDateTime(d, locale) : "—");
  // the first request, and a new attempt after a failure or a changed original
  const canAsk = !blocked && canRun && ["ready", "missing", "failed", "outdated"].includes(info.state);
  // replace a machine draft (or a person's draft: reviewers only, with confirmation)
  const canRegenerate = !blocked && canRun && canReplace && ["completed", "needs_review", "human_draft"].includes(info.state);
  const explain = () => {
    switch (info.state) {
      case "ready":
      case "missing":
        return t("explain.ready", { model });
      case "pending":
        return info.executor === "gpu" ? t("explain.pendingGpu", { model, date: when(job?.created_at) }) : t("explain.pending", { date: when(job?.created_at) });
      case "processing":
        return t("explain.processing", { model, date: when(job?.started_at) });
      case "waiting_worker":
        return info.worker?.last_seen_at ? t("explain.waitingWorker", { date: when(info.worker.last_seen_at) }) : t("explain.waitingWorkerNever");
      case "stalled":
        return t("explain.stalled");
      case "quota":
        return t("explain.quota", { date: when(job?.run_after), error: job?.error_message ?? job?.error_code ?? "" });
      case "retrying":
        return t("explain.retrying", { date: when(job?.run_after), error: job?.error_message ?? job?.error_code ?? "" });
      case "completed":
        return t("explain.completed");
      case "needs_review":
        return t("explain.needsReview");
      case "failed":
        return t("explain.failed", { error: job?.error_message ?? job?.error_code ?? "?" });
      case "outdated":
        return t("explain.outdated");
      case "approved":
        return t("explain.approved");
      default:
        return t("explain.humanDraft");
    }
  };
  return (
    <Card data-testid="machine-panel">
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <Bot className="size-4 text-primary" aria-hidden /> {t("title")}
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium" data-testid="machine-state">{t(`state.${info.state}`)}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p data-testid="machine-explain" className={info.state === "failed" || info.state === "stalled" ? "text-destructive" : undefined}>{explain()}</p>
        <p className="text-xs text-muted-foreground" data-testid="machine-route">
          {info.configured?.route === "gpu_worker" ? t("routeGpu", { model })
            : info.configured?.route === "server" ? t("routeServer", { model }) : t("routeNone")}
          {info.worker?.enabled && ` · ${info.worker.online ? t("workerOnline") : t("workerOffline")}`}
        </p>
        {job && (
          <p className="text-xs text-muted-foreground" data-testid="machine-job">
            {t("jobLine", { status: job.status, attempts: job.attempts ?? 0, max: job.max_attempts ?? 0, date: when(job.created_at) })}
            {job.usage && job.usage.model_calls > 0 && ` · ${t("usage", { input: job.usage.input_tokens, output: job.usage.output_tokens })}`}
          </p>
        )}
        {info.generated_at && (
          <p className="text-muted-foreground">
            {t("generated", { date: formatDateTime(info.generated_at, locale), model: info.model ?? info.provider ?? "?" })}
          </p>
        )}
        {info.warnings.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-5 text-amber-800 dark:text-amber-300">
            {info.warnings.map((w, i) => <li key={i}>{tw.has(w.type) ? tw(w.type, { value: w.value }) : `${w.type}: ${w.value}`}</li>)}
          </ul>
        )}
        {blocked && (
          <p className="text-muted-foreground" data-testid="machine-blocked">
            {t.has(`blocked.${blocked.code}`) ? t(`blocked.${blocked.code}`) : blocked.message}
          </p>
        )}
        {!canRun && !blocked && <p className="text-muted-foreground">{t("noPermission")}</p>}
        <div className="flex flex-wrap gap-2">
          {canAsk && (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => onRun(false)} data-testid="machine-run">
              <RotateCcw /> {info.state === "ready" || info.state === "missing" ? t("run") : t("retry")}
            </Button>
          )}
          {info.state === "stalled" && canRun && (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => onRun(false)} data-testid="machine-resume">
              <RefreshCw /> {t("resume")}
            </Button>
          )}
          {running && (
            <Button size="sm" variant="ghost" disabled={busy} onClick={onRefresh} data-testid="machine-refresh">
              <RefreshCw /> {t("refresh")}
            </Button>
          )}
          {canRegenerate && !confirm && (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirm(true)} data-testid="machine-regenerate">
              <RotateCcw /> {t("regenerate")}
            </Button>
          )}
        </div>
        {confirm && (
          <Alert variant="warning">
            <AlertDescription className="space-y-2">
              <p>{info.state === "human_draft" ? t("regenerateHuman") : t("regenerateMachine")}</p>
              <div className="flex gap-2">
                <Button size="sm" variant="destructive" disabled={busy} onClick={() => { setConfirm(false); onRun(true); }}>{t("regenerateConfirm")}</Button>
                <Button size="sm" variant="outline" onClick={() => setConfirm(false)}>{t("regenerateCancel")}</Button>
              </div>
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
