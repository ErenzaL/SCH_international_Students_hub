"use client";

/**
 * Knowledge-source lifecycle dialogs (migration 0010). They are rendered once at page level and driven by the
 * `source` prop, so a dialog survives the list refresh that removes the deleted row.
 *  - Archive  (admin, reversible): source disabled + its documents archived -> nothing from it is retrievable.
 *  - Restore  (admin): undoes exactly that archive.
 *  - Delete   (super_admin, permanent): GET /deletion-check first, Archive offered as the recommended action,
 *             exact title + reason, and a second explicit confirmation when documents would be destroyed.
 */
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Archive, ArchiveRestore, Loader2, Trash2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Textarea } from "@/components/ui/input";
import { api, errorMessage } from "@/lib/api";
import { parseBlocker, titleMatches } from "@/lib/document-lifecycle";
import {
  canSubmitSourceDelete,
  DELETE_REASON_MIN,
  needsDestructiveConfirmation,
  offerArchive,
  SOURCE_ARCHIVE_REASON_MIN,
  SOURCE_BLOCKER_CODES,
} from "@/lib/source-lifecycle";
import type { Source, SourceDeletionCheck, SourceDeletionResult } from "@/types/api";

type MinimalSource = Pick<Source, "id" | "title">;
const enc = encodeURIComponent;

/** POST /admin/sources/{id}/archive */
export function ArchiveSourceDialog({
  source,
  onClose,
  onDone,
}: {
  source: MinimalSource | null;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const t = useTranslations("admin.sourceLifecycle");
  const c = useTranslations("common");
  const [reason, setReason] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset the form whenever a new source is opened
    setReason("");
    setInvalid(false);
    setError(null);
  }, [source?.id]);

  async function confirm() {
    if (!source) return;
    if (reason.trim().length < SOURCE_ARCHIVE_REASON_MIN) {
      setInvalid(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post<Source>(`/api/v1/admin/sources/${enc(source.id)}/archive`, { reason: reason.trim() });
      onDone(t("archived", { title: source.title }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={!!source} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent closeLabel={c("close")}>
        <DialogHeader>
          <DialogTitle>{t("archiveTitle")}</DialogTitle>
          <DialogDescription>{t("archiveBody", { title: source?.title ?? "" })}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="src-archive-reason">{t("reason")}</Label>
          <Textarea id="src-archive-reason" rows={3} value={reason} aria-invalid={invalid} onChange={(e) => setReason(e.target.value)} />
          <FieldError>{invalid ? t("reasonMin", { min: SOURCE_ARCHIVE_REASON_MIN }) : undefined}</FieldError>
          {error && <Alert variant="destructive">{error}</Alert>}
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>{t("cancel")}</Button>
          <Button disabled={busy} onClick={confirm}>
            {busy ? <Loader2 className="animate-spin" /> : <Archive />} {t("archiveConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** POST /admin/sources/{id}/restore */
export function RestoreSourceDialog({
  source,
  onClose,
  onDone,
}: {
  source: MinimalSource | null;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const t = useTranslations("admin.sourceLifecycle");
  const c = useTranslations("common");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset when a new source is opened
    setError(null);
  }, [source?.id]);

  async function confirm() {
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      await api.post<Source>(`/api/v1/admin/sources/${enc(source.id)}/restore`);
      onDone(t("restored", { title: source.title }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={!!source} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent closeLabel={c("close")}>
        <DialogHeader>
          <DialogTitle>{t("restoreTitle")}</DialogTitle>
          <DialogDescription>{t("restoreBody", { title: source?.title ?? "" })}</DialogDescription>
        </DialogHeader>
        {error && <Alert variant="destructive">{error}</Alert>}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>{t("cancel")}</Button>
          <Button disabled={busy} onClick={confirm}>
            {busy ? <Loader2 className="animate-spin" /> : <ArchiveRestore />} {t("restoreConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Super-admin only. `onDeleted` fires as soon as the server confirms (so the list and stats refresh behind the
 * dialog); the result stays visible until the dialog is closed. `onArchived` fires when Archive is chosen instead.
 */
export function DeleteSourceDialog({
  source,
  onClose,
  onDeleted,
  onArchived,
}: {
  source: MinimalSource | null;
  onClose: () => void;
  onDeleted: (result: SourceDeletionResult) => void;
  onArchived: (message: string) => void;
}) {
  const t = useTranslations("admin.sourceLifecycle");
  const c = useTranslations("common");
  const [check, setCheck] = useState<SourceDeletionCheck | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const [destructive, setDestructive] = useState(false);
  const [busy, setBusy] = useState<"delete" | "archive" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SourceDeletionResult | null>(null);
  const sid = source?.id ?? null;

  useEffect(() => {
    if (!sid) return;
    let alive = true;
    /* eslint-disable react-hooks/set-state-in-effect -- reset + start the deletion-check fetch for a newly opened source */
    setCheck(null);
    setCheckError(null);
    setTyped("");
    setReason("");
    setDestructive(false);
    setError(null);
    setResult(null);
    setLoading(true);
    /* eslint-enable react-hooks/set-state-in-effect */
    api
      .get<SourceDeletionCheck>(`/api/v1/admin/sources/${enc(sid)}/deletion-check`)
      .then((r) => alive && setCheck(r))
      .catch((err) => alive && setCheckError(errorMessage(err)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [sid]);

  function close() {
    if (busy) return;
    onClose();
  }

  async function submit() {
    if (!source || !canSubmitSourceDelete({ check, typedTitle: typed, reason, destructiveConfirmed: destructive })) return;
    setBusy("delete");
    setError(null);
    try {
      const res = await api.post<SourceDeletionResult>(`/api/v1/admin/sources/${enc(source.id)}/delete`, {
        reason: reason.trim(),
        confirm_title: typed.trim(),
        confirm_destructive: destructive,
      });
      setResult(res);
      onDeleted(res);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function archiveInstead() {
    if (!source) return;
    if (reason.trim().length < SOURCE_ARCHIVE_REASON_MIN) {
      setError(t("archiveReasonNeeded", { min: SOURCE_ARCHIVE_REASON_MIN }));
      return;
    }
    setBusy("archive");
    setError(null);
    try {
      await api.post<Source>(`/api/v1/admin/sources/${enc(source.id)}/archive`, { reason: reason.trim() });
      onArchived(t("archived", { title: source.title }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const canSubmit = canSubmitSourceDelete({ check, typedTitle: typed, reason, destructiveConfirmed: destructive, busy: !!busy });
  const showArchive = !!check && offerArchive(check);
  return (
    <Dialog open={!!source} onOpenChange={(o) => !o && close()}>
      <DialogContent closeLabel={c("close")} className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{result ? t("deletedTitle") : t("deleteTitle")}</DialogTitle>
          <DialogDescription>{result ? t("deletedBody", { title: result.title }) : t("deleteIntro")}</DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-3 text-sm">
            <Alert variant="success">
              <AlertDescription>
                <ul className="list-disc space-y-0.5 pl-5">
                  <li>{t("removedDocuments", { count: result.documents })}</li>
                  <li>{t("removedVersions", { count: result.versions })}</li>
                  <li>{t("removedChunks", { count: result.chunks })}</li>
                  <li>{t("removedFiles", { count: result.files_removed })}</li>
                  {result.queued_jobs_canceled > 0 && <li>{t("jobsCanceled", { count: result.queued_jobs_canceled })}</li>}
                  <li>{t("historyKept")}</li>
                </ul>
              </AlertDescription>
            </Alert>
            {result.files_failed.length > 0 && (
              <Alert variant="warning">
                <AlertDescription>
                  <p>{t("filesFailed", { count: result.files_failed.length })}</p>
                  <ul className="mt-1 list-disc pl-5 font-mono text-xs">
                    {result.files_failed.map((f) => <li key={f} className="break-all">{f}</li>)}
                  </ul>
                </AlertDescription>
              </Alert>
            )}
            <DialogFooter>
              <Button onClick={close}>{t("done")}</Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4 text-sm">
            {loading && (
              <p className="flex items-center gap-2 text-muted-foreground" aria-live="polite">
                <Loader2 className="size-4 animate-spin" aria-hidden /> {t("checking")}
              </p>
            )}
            {checkError && <Alert variant="destructive">{checkError}</Alert>}
            {check && (
              <>
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-lg border border-border p-3" data-testid="source-delete-summary">
                  <dt className="text-muted-foreground">{t("fields.title")}</dt>
                  <dd className="break-words font-medium">{check.title}</dd>
                  <dt className="text-muted-foreground">{t("fields.organization")}</dt>
                  <dd>{check.organization}</dd>
                  <dt className="text-muted-foreground">{t("fields.documents")}</dt>
                  <dd>{check.documents}</dd>
                  <dt className="text-muted-foreground">{t("fields.approvedVersions")}</dt>
                  <dd>{check.approved_versions}</dd>
                  <dt className="text-muted-foreground">{t("fields.indexedChunks")}</dt>
                  <dd>{check.indexed_chunks}</dd>
                  <dt className="text-muted-foreground">{t("fields.searchable")}</dt>
                  <dd className={check.is_searchable ? "font-medium text-destructive" : undefined}>
                    {check.is_searchable ? t("searchableYes", { count: check.searchable_chunks }) : t("searchableNo")}
                  </dd>
                </dl>

                <div>
                  <p className="font-medium">{t("consequences")}</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
                    <li>{t("willRemoveSource")}</li>
                    <li>{t("willRemoveDocuments", { count: check.documents, versions: check.versions })}</li>
                    <li>{t("willRemoveChunks", { count: check.chunks })}</li>
                    <li>{t("willRemoveFiles", { count: check.storage_files.length })}</li>
                    {check.queued_jobs > 0 && <li>{t("willCancelJobs", { count: check.queued_jobs })}</li>}
                    <li>{t("willKeepHistory")}</li>
                  </ul>
                </div>

                {check.blockers.length > 0 && (
                  <Alert variant="destructive">
                    <AlertDescription>
                      <p className="font-medium">{t("blocked")}</p>
                      <ul className="mt-1 list-disc pl-5">
                        {check.blockers.map((b) => {
                          const { code, message } = parseBlocker(b);
                          const known = (SOURCE_BLOCKER_CODES as readonly string[]).includes(code);
                          return <li key={b}>{known ? t(`blocker.${code}`, { count: check.published_documents }) : message}</li>;
                        })}
                      </ul>
                    </AlertDescription>
                  </Alert>
                )}

                {showArchive && (
                  <Alert variant="info">
                    <AlertDescription>{t("recommendArchive")}</AlertDescription>
                  </Alert>
                )}

                <div className="space-y-1.5">
                  <Label htmlFor="src-del-reason">{showArchive ? t("reasonBoth") : t("deleteReason")}</Label>
                  <Textarea id="src-del-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
                  <FieldError>
                    {reason && reason.trim().length < DELETE_REASON_MIN && check.eligible ? t("reasonMin", { min: DELETE_REASON_MIN }) : undefined}
                  </FieldError>
                </div>

                {check.eligible && (
                  <>
                    <div className="space-y-1.5">
                      <Label htmlFor="src-del-title">{t("typeTitle")}</Label>
                      <Input id="src-del-title" value={typed} autoComplete="off" spellCheck={false} onChange={(e) => setTyped(e.target.value)} />
                      <FieldError>{typed && !titleMatches(typed, check.title) ? t("titleMismatch") : undefined}</FieldError>
                    </div>
                    {needsDestructiveConfirmation(check) && (
                      <label className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
                        <input
                          type="checkbox"
                          className="mt-0.5 size-4 accent-[var(--color-destructive)]"
                          checked={destructive}
                          onChange={(e) => setDestructive(e.target.checked)}
                          data-testid="confirm-destructive"
                        />
                        <span>{t("confirmDestructive", { count: check.documents, chunks: check.chunks })}</span>
                      </label>
                    )}
                  </>
                )}
              </>
            )}
            {error && <Alert variant="destructive">{error}</Alert>}
            <DialogFooter className="flex-wrap gap-2">
              <Button variant="outline" disabled={!!busy} onClick={close}>{t("cancel")}</Button>
              {showArchive && (
                <Button disabled={!!busy} onClick={archiveInstead}>
                  {busy === "archive" ? <Loader2 className="animate-spin" /> : <Archive />} {t("archiveInstead")}
                </Button>
              )}
              <Button variant="destructive" disabled={!canSubmit} onClick={submit}>
                {busy === "delete" ? <Loader2 className="animate-spin" /> : <Trash2 />} {t("deleteConfirm")}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
