"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { AlertTriangle, Database, Inbox, RefreshCw, WifiOff } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { API_BASE_URL } from "@/lib/constants";

export function LoadingState({ rows = 3, label }: { rows?: number; label?: string }) {
  const t = useTranslations("common");
  return (
    <div role="status" aria-live="polite" className="space-y-3">
      <span className="sr-only">{label ?? t("loading")}</span>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-20 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border bg-muted/30 px-6 py-12 text-center">
      <Inbox className="size-8 text-muted-foreground" aria-hidden />
      <p className="font-medium">{title}</p>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action}
    </div>
  );
}

export function SetupInstructions() {
  const t = useTranslations("errors");
  return (
    <Alert variant="warning">
      <Database className="size-4" aria-hidden />
      <AlertTitle>{t("notConfiguredTitle")}</AlertTitle>
      <AlertDescription>
        <p>{t("notConfiguredBody")}</p>
        <ol className="mt-2 list-decimal space-y-1 pl-5">
          <li>{t("notConfiguredStep1")}</li>
          <li>{t("notConfiguredStep2")}</li>
          <li>{t("notConfiguredStep3")}</li>
        </ol>
        <p className="mt-2">
          <Link href="/support" className="underline">
            {t("seeDocs")}
          </Link>
        </p>
      </AlertDescription>
    </Alert>
  );
}

/** Renders any ApiError honestly – including the "Supabase not configured" setup state. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const t = useTranslations("errors");
  const c = useTranslations("common");
  const err = error instanceof ApiError ? error : null;

  if (err?.isSupabaseNotConfigured) return <SetupInstructions />;

  const network = err?.isNetwork;
  return (
    <Alert variant="destructive">
      {network ? <WifiOff className="size-4" aria-hidden /> : <AlertTriangle className="size-4" aria-hidden />}
      <AlertTitle>{network ? t("networkTitle") : t("genericTitle")}</AlertTitle>
      <AlertDescription>
        <p>{network ? t("networkBody", { url: API_BASE_URL }) : (err?.message ?? String(error))}</p>
        {err && !network && (
          <p className="mt-1 text-xs opacity-80">
            {t("code")}: <code>{err.code}</code>
            {err.requestId && (
              <>
                {" · "}
                {t("requestId")}: <code>{err.requestId}</code>
              </>
            )}
          </p>
        )}
        {onRetry && (
          <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
            <RefreshCw /> {c("retry")}
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}) {
  const t = useTranslations("common");
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  return (
    <nav aria-label={t("pagination")} className="flex items-center justify-between gap-3 pt-4">
      <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        {t("previous")}
      </Button>
      <span className="text-sm text-muted-foreground">{t("pageOf", { page, pages, total })}</span>
      <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onChange(page + 1)}>
        {t("next")}
      </Button>
    </nav>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground md:text-3xl">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </div>
  );
}
