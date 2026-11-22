"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, Bot, Languages, Loader2, PenLine } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label, Select } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { isAdminRole, useMe } from "@/features/admin/shell/admin-context";
import { api, ApiError, errorMessage } from "@/lib/api";
import { LOCALE_LABELS, LOCALES } from "@/lib/constants";
import { DOC_TR_VARIANT, docTranslationState } from "@/lib/doc-translation";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import type { DocTranslationOverview, LanguageCode } from "@/types/api";

/** Admin → Documents → Translations: per-language status of the current approved version. */
export function DocumentTranslationsPanel({ documentId }: { documentId: string }) {
  const t = useTranslations("admin.doctr");
  const locale = useLocale();
  const me = useMe();
  const [key, setKey] = useState(0);
  const { data, error, loading, reload } = useApi<DocTranslationOverview>(`doctr:${documentId}:${key}`, () =>
    api.get<DocTranslationOverview>(`/api/v1/admin/documents/${encodeURIComponent(documentId)}/translations`),
  );
  const [picked, setPicked] = useState<LanguageCode[]>([]);
  const [force, setForce] = useState(false);
  const [origLang, setOrigLang] = useState<LanguageCode | "">("");
  const [notice, setNotice] = useState<string | null>(null);
  const action = useAction();
  const running = (data?.languages ?? []).some((l) => l.job && (l.job.status === "queued" || l.job.status === "running"));

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setKey((k) => k + 1), 3000);
    return () => clearInterval(id);
  }, [running]);

  if (loading && !data) return <LoadingState rows={3} />;
  if (error && !data) {
    if (error instanceof ApiError && error.status === 409) {
      return <Alert variant="info"><AlertDescription>{error.message}</AlertDescription></Alert>;
    }
    return <ErrorState error={error} onRetry={reload} />;
  }
  if (!data) return null;
  const generatable = data.languages.filter((l) => l.can_generate);

  async function generate() {
    setNotice(null);
    const res = await action.run(() =>
      api.post<{ items: { language: LanguageCode; job_id: string }[] }>(
        `/api/v1/admin/documents/${encodeURIComponent(documentId)}/translations/drafts`,
        { languages: picked, force },
      ),
    );
    if (res) {
      setNotice(t("draftsQueued", { count: res.items.length }));
      setPicked([]);
      setForce(false);
      setKey((k) => k + 1);
    }
  }
  async function saveLanguage() {
    if (!origLang) return;
    const res = await action.run(() =>
      api.patch(`/api/v1/admin/documents/${encodeURIComponent(documentId)}/language`, { language: origLang }),
    );
    if (res) {
      setNotice(t("languageSaved", { language: LOCALE_LABELS[origLang] }));
      setOrigLang("");
      setKey((k) => k + 1);
    }
  }

  return (
    <section aria-labelledby="doctr-h" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="doctr-h" className="flex items-center gap-2 text-lg font-semibold">
            <Languages className="size-5" aria-hidden /> {t("title")}
          </h2>
          <p className="text-sm text-muted-foreground">
            {t("subtitle", { version: data.version_number, language: LOCALE_LABELS[data.original_language] })}
          </p>
        </div>
        <Badge variant={data.completion.verified === data.completion.total ? "success" : "secondary"} data-testid="doctr-completion">
          {t("completion", { verified: data.completion.verified, total: data.completion.total })}
        </Badge>
      </div>

      {notice && <Alert variant="success"><AlertDescription>{notice}</AlertDescription></Alert>}
      {action.error && <Alert variant="destructive"><AlertDescription>{errorMessage(action.error)}</AlertDescription></Alert>}
      {data.languages.some((l) => l.has_outdated_previous && !(l.translation && l.translation.verified)) && (
        <Alert variant="warning">
          <AlertTriangle className="size-4" aria-hidden />
          <AlertTitle>{t("outdatedTitle")}</AlertTitle>
          <AlertDescription>{t("outdatedBody", { version: data.version_number })}</AlertDescription>
        </Alert>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("col.language")}</TableHead>
            <TableHead>{t("col.status")}</TableHead>
            <TableHead>{t("col.reviewer")}</TableHead>
            <TableHead>{t("col.updated")}</TableHead>
            <TableHead>{t("col.checks")}</TableHead>
            <TableHead>{t("col.actions")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.languages.map((l) => {
            const tr = l.translation;
            const state = docTranslationState(tr);
            const jobActive = l.job && (l.job.status === "queued" || l.job.status === "running");
            return (
              <TableRow key={l.language}>
                <TableCell className="font-medium">{LOCALE_LABELS[l.language]}</TableCell>
                <TableCell className="space-y-1 text-xs">
                  <Badge variant={state === "outdated" || state === "none" ? "warning" : DOC_TR_VARIANT[state]}>
                    {t(`state.${state}`)}
                  </Badge>
                  {tr?.is_machine_translated && tr.model && (
                    <div className="flex items-center gap-1 text-muted-foreground"><Bot className="size-3" aria-hidden /> {tr.model}</div>
                  )}
                  {l.has_outdated_previous && <div className="text-amber-800 dark:text-amber-300">{t("previousOutdated")}</div>}
                  {jobActive && (
                    <div className="flex items-center gap-1 text-muted-foreground" role="status">
                      <Loader2 className="size-3 animate-spin" aria-hidden /> {t("generating")}
                    </div>
                  )}
                  {l.job?.status === "failed" && (
                    <div className="text-destructive">{t("generationFailed", { error: l.job.error_message ?? l.job.error_code ?? "" })}</div>
                  )}
                </TableCell>
                <TableCell className="text-xs">
                  {tr?.reviewed_by_name ? (
                    <>
                      {tr.reviewed_by_name}
                      <div className="text-muted-foreground">{formatDateTime(tr.reviewed_at, locale)}</div>
                    </>
                  ) : "—"}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatDateTime(tr?.last_edited_at ?? tr?.generated_at ?? tr?.updated_at ?? null, locale)}
                  {tr?.last_edited_by_name && <div>{tr.last_edited_by_name}</div>}
                </TableCell>
                <TableCell className="text-xs">
                  {tr && tr.translation_status !== "todo" ? (
                    tr.warnings.length ? <Badge variant="warning">{t("warnings", { count: tr.warnings.length })}</Badge> : <Badge variant="success">{t("checksOk")}</Badge>
                  ) : "—"}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-2">
                    {(l.can_edit || l.can_review) && (
                      <Button asChild size="sm" variant="outline">
                        <Link href={`/admin/translations/documents/${documentId}/${l.language}`}>
                          <PenLine /> {l.can_review ? t("review") : t("edit")}
                        </Link>
                      </Button>
                    )}
                    {l.can_generate && data.llm.enabled && (
                      <label className="flex items-center gap-1 text-xs">
                        <input
                          type="checkbox"
                          checked={picked.includes(l.language)}
                          disabled={!!jobActive}
                          onChange={(e) =>
                            setPicked((p) => (e.target.checked ? [...p, l.language] : p.filter((x) => x !== l.language)))
                          }
                        />
                        {t("pick")}
                      </label>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      {generatable.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4 text-sm">
          <p className="flex items-center gap-2 font-medium"><Bot className="size-4" aria-hidden /> {t("aiTitle")}</p>
          {data.llm.enabled ? (
            <>
              <p className="mt-1 text-muted-foreground">{t("aiBody", { model: `${data.llm.provider}:${data.llm.model}` })}</p>
              <label className="mt-2 flex items-center gap-2 text-xs">
                <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> {t("force")}
              </label>
              <Button className="mt-3" disabled={action.busy || picked.length === 0} onClick={generate}>
                {action.busy ? <Loader2 className="animate-spin" /> : <Bot />} {t("generate", { count: picked.length })}
              </Button>
            </>
          ) : (
            <p className="mt-1 text-muted-foreground">{t("aiDisabled")}</p>
          )}
        </div>
      )}

      {isAdminRole(me.role) && (
        <div className="flex flex-wrap items-end gap-2 text-sm">
          <div className="space-y-1">
            <Label htmlFor="doctr-orig">{t("originalLanguage")}</Label>
            <Select id="doctr-orig" value={origLang || data.original_language} onChange={(e) => setOrigLang(e.target.value as LanguageCode)}>
              {LOCALES.map((x) => <option key={x} value={x}>{LOCALE_LABELS[x]}</option>)}
            </Select>
          </div>
          <Button variant="outline" size="sm" disabled={action.busy || !origLang || origLang === data.original_language} onClick={saveLanguage}>
            {t("saveLanguage")}
          </Button>
          <p className="w-full text-xs text-muted-foreground">{t("originalLanguageHint")}</p>
        </div>
      )}
    </section>
  );
}
