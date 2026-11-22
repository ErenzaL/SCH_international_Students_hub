"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Bot } from "lucide-react";
import { OpenChatButton } from "@/features/chatbot/open-chat";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState, Pagination } from "@/components/shared/states";
import { RequireSession } from "@/features/account/require-session";
import { TicketStatusBadge } from "@/features/support/ticket-badges";
import { api } from "@/lib/api";
import { LOCALE_LABELS } from "@/lib/constants";
import { useApi } from "@/lib/use-api";
import { relativeTime } from "@/lib/version-state";
import type { Page, SupportTicket } from "@/types/api";

export function MyRequests() {
  return <RequireSession next="/support/requests">{(uid) => <List userId={uid} />}</RequireSession>;
}

function List({ userId }: { userId: string }) {
  const t = useTranslations("requests");
  const locale = useLocale();
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useApi<Page<SupportTicket>>(`my-tickets:${userId}:${page}`, () =>
    api.get<Page<SupportTicket>>("/api/v1/support/tickets", { page, page_size: 20 }),
  );
  if (loading) return <LoadingState rows={3} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data || data.items.length === 0) {
    return (
      <EmptyState
        title={t("empty")}
        description={t("emptyBody")}
        action={
          <OpenChatButton variant="outline">
            <Bot /> {t("goAssistant")}
          </OpenChatButton>
        }
      />
    );
  }
  return (
    <>
      <ul className="space-y-3">
        {data.items.map((tk) => (
          <li key={tk.id}>
            <Card>
              <CardContent className="flex flex-wrap items-start justify-between gap-3 p-4">
                <div className="min-w-0">
                  <Link href={`/support/requests/${tk.id}`} className="font-semibold text-primary hover:underline">
                    #{tk.ticket_number} · {tk.subject}
                  </Link>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {LOCALE_LABELS[tk.language]} · {tk.assigned_supporter?.display_name ?? tk.team} ·{" "}
                    {t("lastActivity", { when: relativeTime(tk.last_message_at ?? tk.created_at, locale) })}
                  </p>
                </div>
                <TicketStatusBadge status={tk.status} />
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
      <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
    </>
  );
}
