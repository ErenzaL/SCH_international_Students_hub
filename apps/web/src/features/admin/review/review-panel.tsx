"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Ban, Check, ExternalLink, RefreshCw, RotateCcw, Undo2, X } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldError, Label, Textarea } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SourceStatusBadge, VersionStatusBadge } from "@/components/shared/badges";
import { formatDateTime, shortHash } from "@/lib/utils";
import type { DocumentDetail, Version, VersionSummary } from "@/types/api";

export interface ReviewHandlers {
  onApprove: (versionId: string, note: string) => void | Promise<void>;
  onReject: (versionId: string, reason: string) => void | Promise<void>;
  onRetryExtraction: () => void | Promise<void>;
  onReprocess: (versionId: string) => void | Promise<void>;
  onRollback: (versionId: string) => void | Promise<void>;
  onCancelDocument: (reason: string) => void | Promise<void>;
  onViewChunks?: (versionId: string) => void;
}

/** Presentational review UI: current approved vs proposed version, diff and actions. */
export function ReviewPanel({
  detail,
  busy = false,
  handlers,
}: {
  detail: DocumentDetail;
  busy?: boolean;
  handlers: ReviewHandlers;
}) {
  const t = useTranslations("admin.review");
  const locale = useLocale();
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState(false);
  const pending = detail.pending_version;
  const current = detail.current_version;

  const previouslyApproved = detail.versions.filter((v) => v.approved_at && !v.is_current);

  async function reject() {
    if (!pending) return;
    if (!reason.trim()) {
      setReasonError(true);
      return;
    }
    setReasonError(false);
    await handlers.onReject(pending.id, reason.trim());
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="grid gap-4 p-5 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <Meta label={t("originalUrl")}>
            {detail.canonical_url ? (
              <a href={detail.canonical_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 break-all text-primary hover:underline">
                <ExternalLink className="size-3.5 shrink-0" aria-hidden /> {detail.canonical_url}
              </a>
            ) : (
              "—"
            )}
          </Meta>
          <Meta label={t("organization")}>{detail.source.organization}</Meta>
          <Meta label={t("source")}>
            {detail.source.title} <SourceStatusBadge status={detail.source.status} />
          </Meta>
          <Meta label={t("documentType")}>{detail.document_type}</Meta>
          <Meta label={t("language")}>{detail.language}</Meta>
          {detail.is_canceled && (
            <Meta label={t("state")}>
              <Badge variant="danger">{t("canceled")}</Badge>
            </Meta>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <VersionCard title={t("currentApproved")} version={current} emptyText={t("noCurrent")} locale={locale} />
        <VersionCard title={t("proposed")} version={pending} emptyText={t("noPending")} locale={locale} highlight />
      </div>

      {pending && (
        <section aria-labelledby="diff-h" className="space-y-2">
          <h2 id="diff-h" className="text-lg font-semibold">
            {t("changes")}
          </h2>
          {detail.diff ? (
            <>
              <p className="text-sm text-muted-foreground">
                <span className="font-semibold text-emerald-700">+{detail.diff.added_count}</span>{" "}
                <span className="font-semibold text-red-700">−{detail.diff.removed_count}</span> {t("lines")}
              </p>
              <div className="max-h-96 overflow-auto rounded-md border border-border bg-card font-mono text-xs">
                {detail.diff.removed_lines.map((l, i) => (
                  <div key={`r${i}`} className="whitespace-pre-wrap bg-red-50 px-3 py-0.5 text-red-900">
                    − {l}
                  </div>
                ))}
                {detail.diff.added_lines.map((l, i) => (
                  <div key={`a${i}`} className="whitespace-pre-wrap bg-emerald-50 px-3 py-0.5 text-emerald-900">
                    + {l}
                  </div>
                ))}
                {detail.diff.added_count + detail.diff.removed_count === 0 && (
                  <p className="p-3 text-muted-foreground">{t("noTextChanges")}</p>
                )}
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{t("noDiff")}</p>
          )}
        </section>
      )}

      {pending && (
        <section aria-labelledby="content-h" className="space-y-2">
          <h2 id="content-h" className="text-lg font-semibold">
            {t("extractedContent")}
          </h2>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted p-4 text-xs" tabIndex={0}>
            {pending.extracted_text}
          </pre>
          {handlers.onViewChunks && (
            <Button variant="outline" size="sm" onClick={() => handlers.onViewChunks?.(pending.id)}>
              {t("viewChunks")}
            </Button>
          )}
        </section>
      )}

      <section aria-labelledby="actions-h" className="space-y-3 rounded-xl border border-border bg-card p-5">
        <h2 id="actions-h" className="text-lg font-semibold">
          {t("actions")}
        </h2>
        {pending ? (
          <div className="space-y-4">
            <div>
              <Label htmlFor="rv-note">{t("approvalNote")}</Label>
              <Textarea id="rv-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
              <Button className="mt-2" disabled={busy} onClick={() => handlers.onApprove(pending.id, note.trim())}>
                <Check /> {t("approve")}
              </Button>
              {pending.embedded_chunk_count < pending.chunk_count && (
                <p className="mt-1 text-xs text-amber-800">{t("missingEmbeddings")}</p>
              )}
            </div>
            <div>
              <Label htmlFor="rv-reason">{t("rejectReason")}</Label>
              <Textarea id="rv-reason" rows={2} value={reason} aria-invalid={reasonError} onChange={(e) => setReason(e.target.value)} />
              <FieldError>{reasonError ? t("reasonRequired") : undefined}</FieldError>
              <Button variant="destructive" className="mt-2" disabled={busy} onClick={reject}>
                <X /> {t("reject")}
              </Button>
            </div>
          </div>
        ) : (
          <Alert variant="info">{t("nothingToReview")}</Alert>
        )}
        <div className="flex flex-wrap gap-2 border-t border-border pt-4">
          <Button variant="outline" disabled={busy} onClick={() => handlers.onRetryExtraction()}>
            <RefreshCw /> {t("retryExtraction")}
          </Button>
          {(pending ?? current) && (
            <Button variant="outline" disabled={busy} onClick={() => handlers.onReprocess((pending ?? current)!.id)}>
              <RotateCcw /> {t("reprocess")}
            </Button>
          )}
          {!detail.is_canceled && (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                if (!reason.trim()) return setReasonError(true);
                handlers.onCancelDocument(reason.trim());
              }}
            >
              <Ban /> {t("cancelDocument")}
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{t("cancelHint")}</p>
      </section>

      <section aria-labelledby="versions-h" className="space-y-2">
        <h2 id="versions-h" className="text-lg font-semibold">
          {t("versions")}
        </h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("version")}</TableHead>
              <TableHead>{t("status")}</TableHead>
              <TableHead>{t("hash")}</TableHead>
              <TableHead>{t("fetchedAt")}</TableHead>
              <TableHead>{t("approvedAt")}</TableHead>
              <TableHead>
                <span className="sr-only">{t("actions")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {detail.versions.map((v) => (
              <TableRow key={v.id}>
                <TableCell className="font-mono">v{v.version_number}</TableCell>
                <TableCell>
                  <VersionStatusBadge status={v.verification_status} />{" "}
                  {v.is_current && <Badge variant="success">{t("current")}</Badge>}
                </TableCell>
                <TableCell className="font-mono text-xs">{shortHash(v.content_hash)}</TableCell>
                <TableCell className="text-xs">{formatDateTime(v.fetched_at ?? v.created_at, locale)}</TableCell>
                <TableCell className="text-xs">{formatDateTime(v.approved_at, locale)}</TableCell>
                <TableCell>
                  {previouslyApproved.some((p: VersionSummary) => p.id === v.id) && (
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => handlers.onRollback(v.id)}>
                      <Undo2 /> {t("rollback")}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}

function VersionCard({
  title,
  version,
  emptyText,
  locale,
  highlight,
}: {
  title: string;
  version: Version | null;
  emptyText: string;
  locale: string;
  highlight?: boolean;
}) {
  const t = useTranslations("admin.review");
  return (
    <Card className={highlight && version ? "border-amber-300" : undefined}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {!version ? (
          <p className="text-sm text-muted-foreground">{emptyText}</p>
        ) : (
          <dl className="space-y-2 text-sm">
            <Row label={t("version")}>
              <span className="font-mono">v{version.version_number}</span> <VersionStatusBadge status={version.verification_status} />
            </Row>
            <Row label={t("contentLength")}>{t("chars", { count: version.content_length })}</Row>
            <Row label={t("hash")}>
              <code className="break-all text-xs" title={version.content_hash}>
                {version.content_hash}
              </code>
            </Row>
            <Row label={t("extractedAt")}>{formatDateTime(version.fetched_at ?? version.created_at, locale)}</Row>
            <Row label={t("sourcePublished")}>{formatDateTime(version.source_published_at, locale)}</Row>
            <Row label={t("chunks")}>
              {version.embedded_chunk_count}/{version.chunk_count} {t("embedded")}
              {version.embedding_model ? ` · ${version.embedding_model}` : ""}
            </Row>
            {version.approved_at && <Row label={t("approvedAt")}>{formatDateTime(version.approved_at, locale)}</Row>}
            {version.rejected_reason && <Row label={t("rejectedReason")}>{version.rejected_reason}</Row>}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
