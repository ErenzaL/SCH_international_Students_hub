"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ExternalLink } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { VersionStatusBadge } from "@/components/shared/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/shared/states";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { formatDateTime, shortHash } from "@/lib/utils";
import type { DocumentDetail, Source, SourceDetail } from "@/types/api";

export type SourceDialogMode = "content" | "versions";

export function SourceDocumentsDialog({
  source,
  mode,
  onClose,
}: {
  source: Source | null;
  mode: SourceDialogMode;
  onClose: () => void;
}) {
  const t = useTranslations("admin.sources.docsDialog");
  const c = useTranslations("common");
  return (
    <Dialog open={!!source} onOpenChange={(o) => !o && onClose()}>
      <DialogContent closeLabel={c("close")} className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{mode === "content" ? t("contentTitle") : t("versionsTitle")}</DialogTitle>
          <DialogDescription>{source?.title}</DialogDescription>
        </DialogHeader>
        {source && <Body sourceId={source.id} mode={mode} />}
      </DialogContent>
    </Dialog>
  );
}

function Body({ sourceId, mode }: { sourceId: string; mode: SourceDialogMode }) {
  const t = useTranslations("admin.sources.docsDialog");
  const { data, error, loading, reload } = useApi<SourceDetail>(`source:${sourceId}`, () =>
    api.get<SourceDetail>(`/api/v1/admin/sources/${sourceId}`),
  );
  if (loading) return <LoadingState rows={2} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data || data.documents.length === 0) {
    return <EmptyState title={t("noDocs")} description={t("noDocsBody")} />;
  }
  return (
    <ul className="space-y-4">
      {data.documents.map((d) => (
        <li key={d.id} className="space-y-2 rounded-lg border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Link href={`/admin/documents/${d.id}`} className="font-medium text-primary hover:underline">
              {d.title}
            </Link>
            {d.canonical_url && (
              <a href={d.canonical_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:underline">
                <ExternalLink className="size-3" aria-hidden /> {t("original")}
              </a>
            )}
          </div>
          {mode === "content" ? <LatestContent documentId={d.id} /> : <Versions documentId={d.id} />}
        </li>
      ))}
    </ul>
  );
}

function LatestContent({ documentId }: { documentId: string }) {
  const t = useTranslations("admin.sources.docsDialog");
  const { data, error, loading, reload } = useApi<DocumentDetail>(`doc:${documentId}`, () =>
    api.get<DocumentDetail>(`/api/v1/admin/documents/${documentId}`),
  );
  if (loading) return <LoadingState rows={1} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const v = data?.pending_version ?? data?.current_version;
  if (!v) return <p className="text-sm text-muted-foreground">{t("noVersion")}</p>;
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <VersionStatusBadge status={v.verification_status} /> v{v.version_number} · {v.content_length} chars
      </div>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">{v.extracted_text}</pre>
    </div>
  );
}

function Versions({ documentId }: { documentId: string }) {
  const t = useTranslations("admin.sources.docsDialog");
  const locale = useLocale();
  const { data, error, loading, reload } = useApi<DocumentDetail>(`doc:${documentId}`, () =>
    api.get<DocumentDetail>(`/api/v1/admin/documents/${documentId}`),
  );
  if (loading) return <LoadingState rows={1} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data || data.versions.length === 0) return <p className="text-sm text-muted-foreground">{t("noVersion")}</p>;
  return (
    <ul className="divide-y divide-border text-sm">
      {data.versions.map((v) => (
        <li key={v.id} className="flex flex-wrap items-center gap-3 py-2">
          <span className="font-mono">v{v.version_number}</span>
          <VersionStatusBadge status={v.verification_status} />
          {v.is_current && <span className="text-xs font-semibold text-emerald-700">{t("current")}</span>}
          <code className="text-xs text-muted-foreground">{shortHash(v.content_hash)}</code>
          <span className="text-xs text-muted-foreground">{formatDateTime(v.created_at, locale)}</span>
        </li>
      ))}
    </ul>
  );
}
