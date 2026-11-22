"use client";

import { useLocale, useTranslations } from "next-intl";
import { Bot, Info, ShieldCheck, User } from "lucide-react";
import { cn, formatDateTime } from "@/lib/utils";
import type { SharedContextItem, TicketMessage } from "@/types/api";

/** Conversation thread of a support request (same rendering for student and supporter). */
export function TicketThread({ messages, viewer }: { messages: TicketMessage[]; viewer: "student" | "staff" }) {
  const t = useTranslations("requests");
  const locale = useLocale();
  if (messages.length === 0) return <p className="text-sm text-muted-foreground">{t("noMessages")}</p>;
  return (
    <ol className="space-y-3" aria-label={t("thread")}>
      {messages.map((m) => {
        if (m.author_role === "system" || m.kind === "status") {
          return (
            <li key={m.id} className="flex items-center justify-center gap-1 text-xs text-muted-foreground">
              <Info className="size-3" aria-hidden /> {m.body} · {formatDateTime(m.created_at, locale)}
            </li>
          );
        }
        const mine = viewer === "student" ? m.author_role === "student" : m.author_role !== "student";
        return (
          <li key={m.id} className={cn("flex gap-2", mine && "flex-row-reverse")}>
            {m.author_role === "student" ? (
              <User className="mt-1 size-5 shrink-0 text-muted-foreground" aria-hidden />
            ) : (
              <ShieldCheck className="mt-1 size-5 shrink-0 text-primary" aria-hidden />
            )}
            <div
              className={cn(
                "max-w-[85%] rounded-2xl px-4 py-2 text-sm",
                mine ? "bg-primary text-primary-foreground" : "border border-border bg-muted/50",
              )}
            >
              <p className="mb-0.5 text-xs font-semibold opacity-80">
                {m.author_role === "student" ? t("student") : m.author_name ?? t("globalSupporter")}
                {m.kind === "info_request" && ` · ${t("infoRequested")}`}
              </p>
              <p className="whitespace-pre-wrap">{m.body}</p>
              <p className="mt-1 text-[11px] opacity-70">{formatDateTime(m.created_at, locale)}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** The excerpt of an AI conversation the student chose to share (copied at consent time). */
export function SharedContext({ items, withdrawnAt }: { items: SharedContextItem[]; withdrawnAt: string | null }) {
  const t = useTranslations("requests");
  const locale = useLocale();
  if (withdrawnAt) return <p className="text-sm text-muted-foreground">{t("contextWithdrawn", { date: formatDateTime(withdrawnAt, locale) })}</p>;
  if (items.length === 0) return <p className="text-sm text-muted-foreground">{t("noSharedContext")}</p>;
  return (
    <ol className="space-y-2">
      {items.map((m, i) => (
        <li key={`${m.created_at}-${i}`} className="rounded-md border border-border p-2 text-sm">
          <p className="mb-0.5 flex items-center gap-1 text-xs font-semibold text-muted-foreground">
            {m.role === "user" ? <User className="size-3" aria-hidden /> : <Bot className="size-3" aria-hidden />}
            {m.role === "user" ? t("student") : t("aiAssistant")} · {formatDateTime(m.created_at, locale)}
          </p>
          <p className="whitespace-pre-wrap">{m.content}</p>
        </li>
      ))}
    </ol>
  );
}
