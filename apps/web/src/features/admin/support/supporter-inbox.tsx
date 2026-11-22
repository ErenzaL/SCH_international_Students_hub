"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Hand } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/shared/states";
import { PriorityBadge, TicketStatusBadge } from "@/features/support/ticket-badges";
import { api, errorMessage } from "@/lib/api";
import { LOCALE_LABELS } from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import { relativeTime } from "@/lib/version-state";
import type { AgentStatus, InboxResponse, InboxView, SupportTicket } from "@/types/api";

export function SupporterInbox() {
  const t = useTranslations("admin.support");
  const locale = useLocale();
  const [view, setView] = useState<InboxView>("queue");
  const [page, setPage] = useState(1);
  const [tick, setTick] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const inbox = useApi<InboxResponse>(`inbox:${view}:${page}:${tick}`, () =>
    api.get<InboxResponse>("/api/v1/support/inbox", { view, page, page_size: 25 }),
  );
  const action = useAction();
  const [available, setAvailable] = useState<boolean | null>(null);

  const counts = inbox.data?.counts;
  const lead = (inbox.data?.lead_languages.length ?? 0) > 0;
  const tabs: { id: InboxView; label: string }[] = [
    { id: "queue", label: `${t("tabs.queue")}${counts ? ` (${counts.queue})` : ""}` },
    { id: "assigned", label: `${t("tabs.assigned")}${counts ? ` (${counts.assigned})` : ""}` },
    { id: "open", label: `${t("tabs.open")}${counts ? ` (${counts.open})` : ""}` },
    { id: "waiting", label: `${t("tabs.waiting")}${counts ? ` (${counts.waiting_for_student})` : ""}` },
    { id: "resolved", label: `${t("tabs.resolved")}${counts ? ` (${counts.resolved})` : ""}` },
    ...(lead ? [{ id: "team" as InboxView, label: t("tabs.team") }] : []),
  ];

  async function claim(id: string) {
    setNotice(null);
    const res = await action.run(() => api.post<SupportTicket>(`/api/v1/support/tickets/${id}/accept`));
    if (res) setNotice(t("accepted", { number: res.ticket_number }));
    setTick((x) => x + 1);
  }
  async function toggleAvailability(next: boolean) {
    const res = await action.run(() => api.put<AgentStatus>("/api/v1/support/me/availability", { is_available: next }));
    if (res) setAvailable(res.is_available);
  }

  return (
    <div>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        actions={
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={available ?? true}
              disabled={action.busy}
              onChange={(e) => void toggleAvailability(e.target.checked)}
            />
            {t("available")}
          </label>
        }
      />
      {inbox.data && (
        <p className="mb-3 text-sm text-muted-foreground">
          {inbox.data.languages.length
            ? t("myLanguages", { languages: inbox.data.languages.map((l) => LOCALE_LABELS[l]).join(", ") })
            : t("noLanguages")}
        </p>
      )}
      <Tabs label={t("title")} items={tabs} value={view} onChange={(v) => { setView(v as InboxView); setPage(1); }} className="mb-4" />
      {view === "queue" && (
        <Alert variant="info" className="mb-3">
          <AlertDescription>{t("queueNote")}</AlertDescription>
        </Alert>
      )}
      {notice && <Alert variant="success" className="mb-3">{notice}</Alert>}
      {action.error && (
        <Alert variant="destructive" className="mb-3">
          {action.error.status === 409 ? t("takenFirst") : errorMessage(action.error)}
        </Alert>
      )}
      {inbox.loading && <LoadingState rows={3} />}
      {inbox.error && <ErrorState error={inbox.error} onRetry={inbox.reload} />}
      {inbox.data && inbox.data.items.length === 0 && <EmptyState title={t(`empty.${view}`)} />}
      {inbox.data && inbox.data.items.length > 0 && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead>{t("subject")}</TableHead>
                <TableHead>{t("language")}</TableHead>
                <TableHead>{t("priority")}</TableHead>
                <TableHead>{t("status")}</TableHead>
                <TableHead>{t("submitted")}</TableHead>
                <TableHead>{t("lastReply")}</TableHead>
                <TableHead>
                  <span className="sr-only">{t("actions")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {inbox.data.items.map((it) => (
                <TableRow key={it.id}>
                  <TableCell className="font-mono text-xs">#{it.ticket_number}</TableCell>
                  <TableCell>
                    {it.can_open ? (
                      <Link href={`/admin/support/${it.id}`} className="font-medium text-primary hover:underline">
                        {it.subject}
                      </Link>
                    ) : (
                      <span className="font-medium">{it.subject}</span>
                    )}
                    {it.escalated && <Badge variant="danger" className="ml-1">{t("escalated")}</Badge>}
                    {view === "team" && it.assigned_to_name && <div className="text-xs text-muted-foreground">{it.assigned_to_name}</div>}
                  </TableCell>
                  <TableCell>{LOCALE_LABELS[it.language]}</TableCell>
                  <TableCell>
                    <PriorityBadge priority={it.priority} />
                  </TableCell>
                  <TableCell>
                    <TicketStatusBadge status={it.status} />
                  </TableCell>
                  <TableCell className="text-xs">{formatDateTime(it.created_at, locale)}</TableCell>
                  <TableCell className="text-xs">{it.last_message_at ? relativeTime(it.last_message_at, locale) : "—"}</TableCell>
                  <TableCell>
                    {it.status === "waiting" ? (
                      <Button size="sm" disabled={action.busy} onClick={() => claim(it.id)}>
                        <Hand /> {t("accept")}
                      </Button>
                    ) : it.can_open ? (
                      <Button asChild size="sm" variant="outline">
                        <Link href={`/admin/support/${it.id}`}>{t("open")}</Link>
                      </Button>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Pagination page={inbox.data.page} pageSize={inbox.data.page_size} total={inbox.data.total} onChange={setPage} />
        </>
      )}
    </div>
  );
}
