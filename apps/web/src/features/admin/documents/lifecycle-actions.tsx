"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Archive, ArchiveRestore, Loader2, Trash2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Textarea } from "@/components/ui/input";
import { api, errorMessage } from "@/lib/api";
import {
  ARCHIVE_REASON_MIN,
  canSubmitDelete,
  DELETE_REASON_MIN,
  LIFECYCLE_VARIANT,
  parseBlocker,
  recommendArchive,
  titleMatches,
} from "@/lib/document-lifecycle";
import type { DeletionCheck, DeletionResult, DocumentLifecycle } from "@/types/api";

type Size = "default" | "sm";

export function LifecycleBadge({ lifecycle }: { lifecycle: DocumentLifecycle }) {
  const t = useTranslations("admin.lifecycle");
  return <Badge variant={LIFECYCLE_VARIANT[lifecycle]}>{t(`state.${lifecycle}`)}</Badge>;
}

/** POST /admin/documents/{id}/archive — reversible; removed from search and the Knowledge Center, history kept. */
export function ArchiveButton({
  documentId,
  title,
  onDone,
  size = "default",
}: {
  documentId: string;
  title: string;
  onDone: (message: string) => void;
  size?: Size;
}) {
  const t = useTranslations("admin.lifecycle");
  const c = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    if (reason.trim().length < ARCHIVE_REASON_MIN) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/admin/documents/${encodeURIComponent(documentId)}/archive`, { reason: reason.trim() });
      setOpen(false);
      setReason("");
      onDone(t("archived", { title }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="outline" size={size} onClick={() => setOpen(true)}>
        <Archive /> {t("archive")}
      </Button>
      <Dialog open={open} onOpenChange={(o) => !busy && setOpen(o)}>
        <DialogContent closeLabel={c("close")}>
          <DialogHeader>
            <DialogTitle>{t("archiveTitle")}</DialogTitle>
            <DialogDescription>{t("archiveBody", { title })}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor={`ar-${documentId}`}>{t("reason")}</Label>
            <Textarea
              id={`ar-${documentId}`}
              rows={3}
              value={reason}
              aria-invalid={invalid}
              onChange={(e) => setReason(e.target.value)}
            />
            <FieldError>{invalid ? t("reasonMin", { min: ARCHIVE_REASON_MIN }) : undefined}</FieldError>
            {error && <Alert variant="destructive">{error}</Alert>}
          </div>
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button disabled={busy} onClick={confirm}>
              {busy ? <Loader2 className="animate-spin" /> : <Archive />} {t("archiveConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** POST /admin/documents/{id}/restore — undo archive / withdrawal (409 for announcement documents). */
export function RestoreButton({
  documentId,
  title,
  lifecycle,
  onDone,
  size = "default",
}: {
  documentId: string;
  title: string;
  lifecycle: DocumentLifecycle;
  onDone: (message: string) => void;
  size?: Size;
}) {
  const t = useTranslations("admin.lifecycle");
  const c = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/admin/documents/${encodeURIComponent(documentId)}/restore`, { note: note.trim() || undefined });
      setOpen(false);
      setNote("");
      onDone(t("restored", { title }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="outline" size={size} onClick={() => setOpen(true)}>
        <ArchiveRestore /> {t("restore")}
      </Button>
      <Dialog open={open} onOpenChange={(o) => !busy && setOpen(o)}>
        <DialogContent closeLabel={c("close")}>
          <DialogHeader>
            <DialogTitle>{t("restoreTitle")}</DialogTitle>
            <DialogDescription>
              {t(lifecycle === "withdrawn" ? "restoreBodyWithdrawn" : "restoreBodyArchived", { title })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor={`rs-${documentId}`}>{t("note")}</Label>
            <Textarea id={`rs-${documentId}`} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
            {error && <Alert variant="destructive">{error}</Alert>}
          </div>
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button disabled={busy} onClick={confirm}>
              {busy ? <Loader2 className="animate-spin" /> : <ArchiveRestore />} {t("restoreConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/**
 * Super-admin only. Loads GET /deletion-check when opened, explains consequences and blockers, and only then
 * allows POST /delete with a reason and the exact title. `onFinished` runs when the result dialog is closed.
 */
export function DeleteDocumentButton({
  documentId,
  onFinished,
  size = "default",
}: {
  documentId: string;
  onFinished: (result: DeletionResult) => void;
  size?: Size;
}) {
  const t = useTranslations("admin.lifecycle");
  const c = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [check, setCheck] = useState<DeletionCheck | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DeletionResult | null>(null);

  async function openDialog() {
    setOpen(true);
    setCheck(null);
    setCheckError(null);
    setTyped("");
    setReason("");
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      setCheck(await api.get<DeletionCheck>(`/api/v1/admin/documents/${encodeURIComponent(documentId)}/deletion-check`));
    } catch (err) {
      setCheckError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  function close() {
    if (busy) return;
    setOpen(false);
    if (result) onFinished(result);
  }

  async function submit() {
    if (!check || !canSubmitDelete({ check, typedTitle: typed, reason, busy })) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<DeletionResult>(`/api/v1/admin/documents/${encodeURIComponent(documentId)}/delete`, {
        reason: reason.trim(),
        confirm_title: typed.trim(),
      });
      setResult(res);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = canSubmitDelete({ check, typedTitle: typed, reason, busy });
  return (
    <>
      <Button variant="destructive" size={size} onClick={openDialog}>
        <Trash2 /> {t("delete")}
      </Button>
      <Dialog open={open} onOpenChange={(o) => !o && close()}>
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
                    <li>{t("removedVersions", { count: result.versions })}</li>
                    <li>{t("removedChunks", { count: result.chunks })}</li>
                    <li>{t("removedFiles", { count: result.files_removed })}</li>
                    <li>{t("tombstoneKept")}</li>
                    {result.reimport_blocked && <li>{t("reimportBlocked")}</li>}
                  </ul>
                </AlertDescription>
              </Alert>
              {result.files_failed.length > 0 && (
                <Alert variant="warning">
                  <AlertDescription>
                    <p>{t("filesFailed", { count: result.files_failed.length })}</p>
                    <ul className="mt-1 list-disc pl-5 font-mono text-xs">
                      {result.files_failed.map((f) => (
                        <li key={f} className="break-all">
                          {f}
                        </li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}
              <DialogFooter>
                <Button onClick={close}>{t("backToList")}</Button>
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
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t("document")}</p>
                    <p className="mt-0.5 break-words font-medium">{check.title}</p>
                  </div>
                  <div>
                    <p className="font-medium">{t("consequences")}</p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
                      <li>{t("willRemoveVersions", { count: check.versions })}</li>
                      <li>{t("willRemoveChunks", { count: check.chunks })}</li>
                      <li>{t("willRemoveFiles", { count: check.storage_files.length })}</li>
                      <li>{t("tombstone")}</li>
                      {check.suppress_reimport && <li>{t("willBlockReimport")}</li>}
                    </ul>
                  </div>
                  {check.blockers.length > 0 && (
                    <Alert variant="destructive">
                      <AlertDescription>
                        <p className="font-medium">{t("blocked")}</p>
                        <ul className="mt-1 list-disc pl-5">
                          {check.blockers.map((b) => {
                            const { code, message } = parseBlocker(b);
                            const known = ["published", "announcement", "busy"].includes(code);
                            return <li key={b}>{known ? t(`blocker.${code}`) : message}</li>;
                          })}
                        </ul>
                      </AlertDescription>
                    </Alert>
                  )}
                  {recommendArchive(check) && (
                    <Alert variant="info">
                      <AlertDescription>{t("recommendArchive", { count: check.approved_versions })}</AlertDescription>
                    </Alert>
                  )}
                  {check.eligible && (
                    <>
                      <div className="space-y-1.5">
                        <Label htmlFor={`del-reason-${documentId}`}>{t("deleteReason")}</Label>
                        <Textarea
                          id={`del-reason-${documentId}`}
                          rows={2}
                          value={reason}
                          onChange={(e) => setReason(e.target.value)}
                        />
                        <FieldError>
                          {reason && reason.trim().length < DELETE_REASON_MIN ? t("reasonMin", { min: DELETE_REASON_MIN }) : undefined}
                        </FieldError>
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor={`del-title-${documentId}`}>{t("typeTitle")}</Label>
                        <Input
                          id={`del-title-${documentId}`}
                          value={typed}
                          autoComplete="off"
                          spellCheck={false}
                          onChange={(e) => setTyped(e.target.value)}
                        />
                        <FieldError>{typed && !titleMatches(typed, check.title) ? t("titleMismatch") : undefined}</FieldError>
                      </div>
                    </>
                  )}
                </>
              )}
              {error && <Alert variant="destructive">{error}</Alert>}
              <DialogFooter>
                <Button variant="outline" disabled={busy} onClick={close}>
                  {t("cancel")}
                </Button>
                <Button variant="destructive" disabled={!canSubmit} onClick={submit}>
                  {busy ? <Loader2 className="animate-spin" /> : <Trash2 />} {t("deleteConfirm")}
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
