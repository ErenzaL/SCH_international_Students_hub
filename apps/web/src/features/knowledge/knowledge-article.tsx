"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, ArrowLeft, BadgeCheck, Bot, ExternalLink, Languages, MessageCircle, Paperclip } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label, Select } from "@/components/ui/input";
import { AuthorityBadge, ScopeBadge, StaleBadge } from "@/components/shared/badges";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { openChat } from "@/features/chatbot/open-chat";
import { api } from "@/lib/api";
import { LOCALE_LABELS, LOCALES } from "@/lib/constants";
import { articleView, contentLanguage, textBlocks } from "@/lib/doc-translation";
import { useApi } from "@/lib/use-api";
import { useCategoryName } from "@/lib/use-category-name";
import { formatDate } from "@/lib/utils";
import { formatFieldValue } from "@/lib/format-field";
import type { KnowledgeDocumentDetail, LanguageCode } from "@/types/api";

export function KnowledgeArticle({ id }: { id: string }) {
  const t = useTranslations("knowledge");
  const tr = useTranslations("knowledge.tr");
  const c = useTranslations("common");
  const locale = useLocale();
  const categoryName = useCategoryName();
  // the reading language defaults to the site language (the profile's preferred language once signed in);
  // switching it here never changes the profile
  const [lang, setLang] = useState<LanguageCode>(contentLanguage(null, locale));
  const [showOriginal, setShowOriginal] = useState(false);
  const { data: d, error, loading, reload } = useApi<KnowledgeDocumentDetail>(`kdoc:${id}:${lang}`, () =>
    api.get<KnowledgeDocumentDetail>(`/api/v1/knowledge/documents/${encodeURIComponent(id)}`, { lang }),
  );
  const view = d ? articleView(d, lang, showOriginal) : null;
  const originalLabel = d ? LOCALE_LABELS[d.language] ?? d.language : "";

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <Link href="/knowledge" className="mb-4 inline-flex items-center gap-1 text-sm text-primary hover:underline">
        <ArrowLeft className="size-4" /> {t("backToList")}
      </Link>
      {loading && !d && <LoadingState rows={4} />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {d && view && (
        <article className="space-y-6">
          <header className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <ScopeBadge scope={d.scope} />
              <AuthorityBadge authority={d.authority_type} />
              <Badge variant="outline">{categoryName(d.category)}</Badge>
              {d.is_stale && <StaleBadge days={d.verification_age_days} />}
              {view.mode === "verified" && (
                <Badge variant="success"><BadgeCheck className="size-3.5" aria-hidden /> {tr("verifiedBadge")}</Badge>
              )}
              {view.mode === "machine" && (
                <Badge variant="warning"><Bot className="size-3.5" aria-hidden /> {tr("machineBadge")}</Badge>
              )}
              {(view.mode === "original" || view.mode === "fallback") && (
                <Badge variant="muted">{tr("originalBadge", { language: originalLabel })}</Badge>
              )}
            </div>
            <h1 lang={view.language} className="text-2xl font-bold tracking-tight md:text-3xl">{view.title}</h1>
            {view.mode !== "original" && view.mode !== "fallback" && (
              <p lang={d.language} className="text-sm text-muted-foreground">{tr("originalTitle", { title: d.title })}</p>
            )}
            <div className="flex flex-wrap items-end gap-3">
              <div className="space-y-1">
                <Label htmlFor="kdoc-lang" className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Languages className="size-3.5" aria-hidden /> {tr("readIn")}
                </Label>
                <Select id="kdoc-lang" value={lang} onChange={(e) => { setLang(e.target.value as LanguageCode); setShowOriginal(false); }}>
                  {LOCALES.map((l) => (
                    <option key={l} value={l}>
                      {LOCALE_LABELS[l]}{l === d.language ? ` · ${tr("originalShort")}` : (d.verified_languages ?? []).includes(l) ? ` · ${tr("verifiedShort")}` : ""}
                    </option>
                  ))}
                </Select>
              </div>
              <Button variant="outline" size="sm" data-testid="ask-about-document"
                onClick={() => openChat(t("askAssistantPrefill", { title: view.title }))}>
                <MessageCircle /> {t("askAssistant")}
              </Button>
              {d.translation && lang !== d.language && (
                <Button variant="outline" size="sm" onClick={() => setShowOriginal((v) => !v)}>
                  {showOriginal ? tr("viewTranslation", { language: LOCALE_LABELS[lang] }) : tr("viewOriginal", { language: originalLabel })}
                </Button>
              )}
            </div>
          </header>

          {view.mode === "verified" && d.translation && (
            <Alert variant="success">
              <BadgeCheck className="size-4" aria-hidden />
              <AlertDescription>
                {tr("verifiedNote", { version: d.translation.source_version_number, date: formatDate(d.translation.reviewed_at, locale), original: originalLabel })}
              </AlertDescription>
            </Alert>
          )}
          {view.mode === "machine" && (
            <Alert variant="warning">
              <Bot className="size-4" aria-hidden />
              <AlertTitle>{tr("machineBadge")}</AlertTitle>
              <AlertDescription>{tr("machineNote", { original: originalLabel })}</AlertDescription>
            </Alert>
          )}
          {view.mode === "fallback" && !d.translation && (
            <Alert variant="info">
              <Languages className="size-4" aria-hidden />
              <AlertTitle>{tr("fallbackTitle", { language: LOCALE_LABELS[lang] })}</AlertTitle>
              <AlertDescription>{tr("fallbackBody", { original: originalLabel })}</AlertDescription>
            </Alert>
          )}

          {d.is_stale && (
            <Alert variant="warning">
              <AlertTriangle className="size-4" aria-hidden />
              <AlertTitle>{t("staleTitle")}</AlertTitle>
              <AlertDescription>{t("staleBody", { days: d.verification_age_days ?? 0 })}</AlertDescription>
            </Alert>
          )}

          {d.key_facts && Object.keys(d.key_facts).length > 0 && (
            <section aria-labelledby="kf-h" className="rounded-lg border border-border bg-card p-5">
              <h2 id="kf-h" className="mb-2 font-semibold">{t("keyFacts")}</h2>
              <dl className="grid gap-2 text-sm sm:grid-cols-2">
                {Object.entries(d.key_facts).map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t.has(`facts.${k}`) ? t(`facts.${k}`) : k}</dt>
                    <dd>{formatFieldValue(v)}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-2 text-xs text-muted-foreground">{t("keyFactsNote")}</p>
            </section>
          )}

          <Card>
            <CardContent className="grid gap-4 p-5 text-sm sm:grid-cols-2">
              <Meta label={t("organization")} value={d.organization} />
              <Meta label={t("sourcePublished")} value={formatDate(d.source_published_at, locale)} />
              <Meta label={t("verifiedAt")} value={formatDate(d.verified_at, locale)} />
              <Meta label={t("version")} value={`v${d.version_number}`} />
              <Meta label={tr("originalLanguage")} value={originalLabel} />
              <Meta label={tr("translationStatus")} value={
                view.mode === "verified" ? tr("statusVerified") : view.mode === "machine" ? tr("statusMachine")
                  : lang === d.language ? tr("statusOriginal") : tr("statusNone")} />
              {d.valid_until && <Meta label={t("validUntil")} value={formatDate(d.valid_until, locale)} />}
              {d.notice_no && <Meta label={t("noticeNo")} value={`#${d.notice_no}`} />}
              <div className="sm:col-span-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("officialSource")}
                </p>
                {d.source_url ? (
                  <a
                    href={d.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 break-all text-primary hover:underline"
                  >
                    <ExternalLink className="size-4 shrink-0" aria-hidden /> {d.source_url}
                  </a>
                ) : (
                  <p className="text-muted-foreground">{c("noSourceUrl")}</p>
                )}
              </div>
              {(d.attachments ?? []).length > 0 && (
                <div className="sm:col-span-2">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t("attachments")}</p>
                  <ul className="mt-1 space-y-0.5">
                    {d.attachments!.map((a) => (
                      <li key={a.url}>
                        <a href={a.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                          <Paperclip className="size-3.5" aria-hidden /> {a.name}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>

          <div lang={view.language} data-testid="article-body" className="space-y-3 rounded-lg border border-border bg-card p-5 leading-relaxed">
            {textBlocks(view.content).map((b, i) =>
              b.kind === "p" ? (
                <p key={i} className="whitespace-pre-wrap">{b.text}</p>
              ) : b.kind === "h1" ? (
                <h2 key={i} className="pt-2 text-xl font-semibold">{b.text}</h2>
              ) : b.kind === "h2" ? (
                <h3 key={i} className="pt-2 text-lg font-semibold">{b.text}</h3>
              ) : (
                <h4 key={i} className="pt-1 font-semibold">{b.text}</h4>
              ),
            )}
          </div>
          <p className="text-xs text-muted-foreground">{t("articleDisclaimer")}</p>
        </article>
      )}
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5">{value}</p>
    </div>
  );
}
