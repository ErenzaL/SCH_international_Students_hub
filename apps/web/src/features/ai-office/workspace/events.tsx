"use client";

/**
 * Mia (Event agent) - events-first workspace over the existing announcements API: published announcements that
 * carry an event date or a deadline, upcoming or past, by category, with an inline detail view and the link to the
 * official notice. Registration is never called "open": only the dates written in the notice are shown.
 */
import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAgentTasks } from "@/features/ai-office/agent-api";
import { useWorkspace } from "@/features/ai-office/workspace/context";
import {
  AgentActionBar, AgentTaskList, AnnouncementCard, DeadlineDisplay, EmptyState, FilterChips, LoadState, SignInPrompt,
  SourceCitation, WorkspaceSection, todayKst, useCommonNextSteps,
} from "@/features/ai-office/workspace/parts";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import type { AnnouncementDetail, AnnouncementSummary, Page } from "@/types/api";

/** the date an event is sorted and filtered by: its event date, else its deadline */
export const eventDate = (a: AnnouncementSummary) => a.event_date ?? a.deadline;

/** Dated announcements split into upcoming (soonest first) and past (latest first), duplicates removed. */
export function splitEvents(items: AnnouncementSummary[], today = todayKst()) {
  const seen = new Set<string>();
  const dated = items.filter((a) => eventDate(a) && !seen.has(a.id) && (seen.add(a.id), true));
  const upcoming = dated.filter((a) => eventDate(a)!.slice(0, 10) >= today)
    .sort((a, b) => eventDate(a)!.localeCompare(eventDate(b)!));
  const past = dated.filter((a) => eventDate(a)!.slice(0, 10) < today)
    .sort((a, b) => eventDate(b)!.localeCompare(eventDate(a)!));
  return { upcoming, past };
}

export function EventsWorkspace() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.events");
  const tCat = useTranslations("categories");
  const locale = useLocale();
  const [when, setWhen] = useState<"upcoming" | "past">("upcoming");
  const [category, setCategory] = useState("all");
  const [open, setOpen] = useState<string | null>(null);
  const data = useApi(`ws-events:${locale}`, async () => {
    const pages = await Promise.all((["active", "upcoming", "expired"] as const).map((status) =>
      api.get<Page<AnnouncementSummary>>("/api/v1/announcements", { status, page_size: 40, display_language: locale })));
    return splitEvents(pages.flatMap((p) => p.items));
  });
  const { tasks, reload } = useAgentTasks(ws.agent, ws.signedIn, ws.onChanged);
  const tNext = useTranslations("office.ws.next");
  const common = useCommonNextSteps();

  if (open) return <EventDetail id={open} onBack={() => setOpen(null)} />;

  const list = data.data ? data.data[when] : [];
  const categories = [...new Set(list.map((a) => a.category))];
  const shown = list.filter((a) => category === "all" || a.category === category);
  return (
    <div className="space-y-4" data-testid="ws-events">
      <p className="text-muted-foreground">{t("intro")}</p>
      <FilterChips label={t("when")} value={when} testId="events-when"
        onChange={(v) => { setWhen(v); setCategory("all"); }}
        options={[{ id: "upcoming", label: t("upcoming", { count: data.data?.upcoming.length ?? 0 }) },
          { id: "past", label: t("past", { count: data.data?.past.length ?? 0 }) }]} />
      {categories.length > 1 && (
        <FilterChips label={t("category")} value={category} onChange={setCategory} testId="events-category"
          options={[{ id: "all", label: t("allCategories") },
            ...categories.map((c) => ({ id: c, label: tCat.has(c) ? tCat(c) : c }))]} />
      )}
      <WorkspaceSection title={when === "upcoming" ? t("upcomingTitle") : t("pastTitle")} testId="events-list">
        <LoadState loading={data.loading && !data.data} error={data.error} onRetry={data.reload} />
        {data.data && (shown.length === 0 ? <EmptyState next={[
          when === "upcoming" ? { label: tNext("showPast"), onClick: () => { setWhen("past"); setCategory("all"); } }
            : { label: tNext("showUpcoming"), onClick: () => { setWhen("upcoming"); setCategory("all"); } },
          { label: tNext("allAnnouncements"), href: "/announcements" }, ...common.askChat]}>
          {when === "upcoming" ? t("noUpcoming") : t("noPast")}
        </EmptyState> : (
          <ul className="space-y-2">{shown.map((a) => <li key={a.id}><AnnouncementCard a={a} onOpen={setOpen} /></li>)}</ul>
        ))}
        <p className="text-xs text-muted-foreground">{t("registrationNote")}</p>
      </WorkspaceSection>
      <WorkspaceSection title={t("changesTitle")}>
        {ws.signedIn ? (
          <>
            <AgentActionBar ids={ws.agent.interface?.task_actions ?? []} onDone={() => void reload()} />
            <AgentTaskList startHint tasks={tasks} types={["event_digest"]} limit={1} title={t("latestDigest")}
              onChanged={() => { void reload(); ws.onChanged(); }} />
          </>
        ) : <SignInPrompt text={t("signInForDigest")} />}
      </WorkspaceSection>
    </div>
  );
}

function EventDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const t = useTranslations("office.ws.events");
  const tCat = useTranslations("categories");
  const locale = useLocale();
  const d = useApi(`ws-event:${id}:${locale}`, () =>
    api.get<AnnouncementDetail>(`/api/v1/announcements/${id}`, { lang: locale }));
  const a = d.data;
  const title = a?.translation?.title ?? a?.title;
  const body = a?.translation?.body ?? a?.body;
  return (
    <article className="space-y-3" data-testid="event-detail">
      <Button size="sm" variant="ghost" className="-ml-2 min-h-9" onClick={onBack} data-testid="event-back">
        <ArrowLeft className="size-4" aria-hidden /> {t("backToList")}
      </Button>
      <LoadState loading={d.loading && !a} error={d.error} onRetry={d.reload} />
      {a && (
        <>
          <p className="text-[11px] font-bold text-muted-foreground">{tCat.has(a.category) ? tCat(a.category) : a.category}</p>
          <h3 className="text-base font-bold leading-snug">{title}</h3>
          {a.translation && (
            <p className="text-[11px] font-semibold text-muted-foreground" data-testid="event-translation">
              {a.translation.status === "verified" ? t("translationVerified") : t("translationMachine")}
            </p>
          )}
          <div className="flex flex-col gap-1">
            {a.event_date && <DeadlineDisplay date={a.event_date} kind="event" />}
            {a.deadline && <DeadlineDisplay date={a.deadline} />}
          </div>
          {body && <p className="max-h-72 overflow-y-auto whitespace-pre-line rounded-xl bg-muted/50 p-3 text-xs leading-relaxed">{body}</p>}
          <p className="text-xs text-muted-foreground">{t("detailNote")}</p>
          <div className="flex flex-wrap gap-1.5">
            <SourceCitation href={`/announcements/${a.id}`} kind="hub" label={t("openInHub")} />
            {a.source?.url && <SourceCitation href={a.source.url} kind="official" label={a.source.organization || t("officialNotice")} />}
          </div>
        </>
      )}
    </article>
  );
}
