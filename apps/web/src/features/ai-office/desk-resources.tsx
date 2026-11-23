"use client";

/**
 * Real data shown at the service desks, read from the existing public APIs (approved / published content only):
 * Knowledge Center guides by category, announcements by category, and current / upcoming events. Nothing is
 * invented: an empty result says so.
 */
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { CalendarDays, FileText, Megaphone } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/utils";
import type { AnnouncementSummary, KnowledgeDocumentSummary, Page } from "@/types/api";

function useGuides(categories: string[]) {
  const locale = useLocale();
  return useApi<KnowledgeDocumentSummary[]>(`office-guides:${categories.join(",")}:${locale}`, async () => {
    const pages = await Promise.all(categories.map((category) =>
      api.get<Page<KnowledgeDocumentSummary>>("/api/v1/knowledge/documents", { category, page_size: 6, lang: locale })));
    return pages.flatMap((p) => p.items);
  });
}

function useAnnouncements(category: string | undefined) {
  return useApi<AnnouncementSummary[]>(`office-ann:${category ?? "all"}`, async () =>
    (await api.get<Page<AnnouncementSummary>>("/api/v1/announcements", { category, page_size: 6 })).items);
}

/** Published announcements that are running or upcoming, soonest date first (event date, else deadline). */
export function upcoming(items: AnnouncementSummary[]): AnnouncementSummary[] {
  const seen = new Set<string>();
  return items
    .filter((a) => (seen.has(a.id) ? false : (seen.add(a.id), true)))
    .filter((a) => a.event_date || a.deadline)
    .sort((a, b) => String(a.event_date ?? a.deadline).localeCompare(String(b.event_date ?? b.deadline)));
}

function State({ loading, error, empty, onRetry }: { loading: boolean; error: unknown; empty: string | null; onRetry: () => void }) {
  const t = useTranslations("office");
  if (loading) return <p className="py-6 text-center text-sm text-muted-foreground" role="status">{t("loading")}</p>;
  if (error) {
    return (
      <p className="py-4 text-sm text-destructive">
        {t("loadError")}{" "}
        <button type="button" onClick={onRetry} className="font-medium underline">{t("retry")}</button>
      </p>
    );
  }
  return empty ? <p className="rounded-xl bg-muted/60 p-3 text-sm text-muted-foreground" data-testid="desk-empty">{empty}</p> : null;
}

function Item({ href, title, meta, icon }: { href: string; title: string; meta?: string | null; icon: React.ReactNode }) {
  return (
    <li>
      <Link href={href} className="flex items-start gap-2.5 rounded-xl px-2.5 py-2 hover:bg-muted">
        <span className="mt-0.5 text-primary" aria-hidden>{icon}</span>
        <span className="min-w-0">
          <span className="block font-medium leading-snug">{title}</span>
          {meta && <span className="block text-xs text-muted-foreground">{meta}</span>}
        </span>
      </Link>
    </li>
  );
}

export function GuidesList({ categories }: { categories: string[] }) {
  const t = useTranslations("office.lists");
  const { data, loading, error, reload } = useGuides(categories);
  return (
    <section className="space-y-2" data-testid="desk-guides">
      <h3 className="text-sm font-semibold">{t("guidesTitle")}</h3>
      <State loading={loading && !data} error={error} empty={data && data.length === 0 ? t("noGuides") : null} onRetry={reload} />
      {data && data.length > 0 && (
        <ul className="space-y-0.5 text-sm">
          {data.map((d) => (
            <Item key={d.id} href={`/knowledge/${d.id}`} title={d.translated_title ?? d.title} meta={d.organization}
              icon={<FileText className="size-4" />} />
          ))}
        </ul>
      )}
      <Link href="/knowledge" className="inline-block text-sm font-medium text-primary hover:underline">{t("allGuides")}</Link>
    </section>
  );
}

export function NoticesList({ category }: { category?: string }) {
  const t = useTranslations("office.lists");
  const locale = useLocale();
  const { data, loading, error, reload } = useAnnouncements(category);
  return (
    <section className="space-y-2" data-testid="desk-notices">
      <h3 className="text-sm font-semibold">{t("noticesTitle")}</h3>
      <State loading={loading && !data} error={error} empty={data && data.length === 0 ? t("noNotices") : null} onRetry={reload} />
      {data && data.length > 0 && (
        <ul className="space-y-0.5 text-sm">
          {data.map((a) => (
            <Item key={a.id} href={`/announcements/${a.id}`} title={a.title}
              meta={a.deadline ? t("deadlineOn", { date: formatDate(a.deadline, locale) }) : formatDate(a.published_at, locale)}
              icon={<Megaphone className="size-4" />} />
          ))}
        </ul>
      )}
      <Link href="/announcements" className="inline-block text-sm font-medium text-primary hover:underline">{t("allNotices")}</Link>
    </section>
  );
}

export function EventsList() {
  const t = useTranslations("office.lists");
  const locale = useLocale();
  const { data, loading, error, reload } = useApi<AnnouncementSummary[]>("office-events", async () => {
    const [active, soon] = await Promise.all(["active", "upcoming"].map((status) =>
      api.get<Page<AnnouncementSummary>>("/api/v1/announcements", { status, page_size: 20 })));
    return upcoming([...active.items, ...soon.items]);
  });
  return (
    <section className="space-y-2" data-testid="desk-events">
      <h3 className="text-sm font-semibold">{t("eventsTitle")}</h3>
      <State loading={loading && !data} error={error} empty={data && data.length === 0 ? t("noEvents") : null} onRetry={reload} />
      {data && data.length > 0 && (
        <ul className="space-y-0.5 text-sm">
          {data.map((a) => (
            <Item key={a.id} href={`/announcements/${a.id}`} title={a.title}
              meta={[a.event_date && t("eventOn", { date: formatDate(a.event_date, locale) }),
                a.deadline && t("deadlineOn", { date: formatDate(a.deadline, locale) })].filter(Boolean).join(" · ")}
              icon={<CalendarDays className="size-4" />} />
          ))}
        </ul>
      )}
      <Link href="/announcements" className="inline-block text-sm font-medium text-primary hover:underline">{t("allNotices")}</Link>
    </section>
  );
}

export function OpportunitiesList({ announcementCategory, categories }: { announcementCategory: string; categories: string[] }) {
  const t = useTranslations("office.lists");
  const locale = useLocale();
  const ann = useAnnouncements(announcementCategory);
  const guides = useGuides(categories);
  const loading = (ann.loading && !ann.data) || (guides.loading && !guides.data);
  const none = ann.data && guides.data && ann.data.length === 0 && guides.data.length === 0;
  return (
    <section className="space-y-2" data-testid="desk-opportunities">
      <h3 className="text-sm font-semibold">{t("opportunitiesTitle")}</h3>
      <State loading={loading} error={ann.error || guides.error} empty={none ? t("noOpportunities") : null}
        onRetry={() => { ann.reload(); guides.reload(); }} />
      {(ann.data?.length ?? 0) + (guides.data?.length ?? 0) > 0 && (
        <ul className="space-y-0.5 text-sm">
          {ann.data?.map((a) => (
            <Item key={a.id} href={`/announcements/${a.id}`} title={a.title}
              meta={a.deadline ? t("deadlineOn", { date: formatDate(a.deadline, locale) }) : t("fromAnnouncements")}
              icon={<Megaphone className="size-4" />} />
          ))}
          {guides.data?.map((d) => (
            <Item key={d.id} href={`/knowledge/${d.id}`} title={d.translated_title ?? d.title} meta={t("fromGuides")}
              icon={<FileText className="size-4" />} />
          ))}
        </ul>
      )}
    </section>
  );
}
