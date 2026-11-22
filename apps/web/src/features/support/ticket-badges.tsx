"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { PRIORITY_VARIANT, TICKET_STATUS_VARIANT } from "@/lib/support";
import type { TicketPriority, TicketStatus } from "@/types/api";

export function TicketStatusBadge({ status }: { status: TicketStatus }) {
  const t = useTranslations("requests.status");
  return <Badge variant={TICKET_STATUS_VARIANT[status]}>{t(status)}</Badge>;
}

export function PriorityBadge({ priority }: { priority: TicketPriority }) {
  const t = useTranslations("requests.priority");
  return <Badge variant={PRIORITY_VARIANT[priority]}>{t(priority)}</Badge>;
}
