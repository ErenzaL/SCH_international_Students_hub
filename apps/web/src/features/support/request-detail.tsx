"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ArrowLeft, CheckCircle2, RotateCcw, Send, Star, Undo2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label, Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { RequireSession } from "@/features/account/require-session";
import { onUserNotification } from "@/features/notifications/user-notifications";
import { TicketStatusBadge } from "@/features/support/ticket-badges";
import { SharedContext, TicketThread } from "@/features/support/ticket-thread";
import { api, errorMessage } from "@/lib/api";
import { LOCALE_LABELS } from "@/lib/constants";
import { shouldPollTicket, studentCanReply } from "@/lib/support";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { cn, formatDateTime } from "@/lib/utils";
import type { SupportTicket } from "@/types/api";

const POLL_MS = 10_000;

export function RequestDetail({ id }: { id: string }) {
  return <RequireSession next={`/support/requests/${id}`}>{() => <Detail id={id} />}</RequireSession>;
}

function Detail({ id }: { id: string }) {
  const t = useTranslations("requests");
  const locale = useLocale();
  const { data, error, loading, reload } = useApi<SupportTicket>(`ticket:${id}`, () => api.get<SupportTicket>(`/api/v1/support/tickets/${id}`));
  const [ticket, setTicket] = useState<SupportTicket | null>(null);
  const [reply, setReply] = useState("");
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const action = useAction();
  const current = ticket ?? data;

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the loaded value replaces the local copy
    if (data) setTicket(data);
  }, [data]);

  // keep the thread fresh: poll while open, and refresh on a notification about this request
  useEffect(() => {
    const status = current?.status;
    const timer = setInterval(() => {
      if (shouldPollTicket(status, document.visibilityState === "visible")) reload();
    }, POLL_MS);
    const off = onUserNotification((n) => {
      if (n.entity_id === id) reload();
    });
    return () => {
      clearInterval(timer);
      off();
    };
  }, [current?.status, id, reload]);

  if (loading && !current) return <LoadingState rows={4} />;
  if (error && !current) return <ErrorState error={error} onRetry={reload} />;
  if (!current) return null;
  const tk = current;

  async function run(path: string, body?: unknown) {
    const res = await action.run(() => api.post<SupportTicket>(`/api/v1/support/tickets/${id}${path}`, body));
    if (res) setTicket(res);
    return res;
  }

  return (
    <div className="space-y-5">
      <Button asChild variant="ghost" size="sm">
        <Link href="/support/requests">
          <ArrowLeft /> {t("back")}
        </Link>
      </Button>
      <PageHeader
        title={`#${tk.ticket_number} · ${tk.subject}`}
        description={`${LOCALE_LABELS[tk.language]} · ${tk.assigned_supporter?.display_name ?? tk.team}`}
        actions={<TicketStatusBadge status={tk.status} />}
      />
      <Alert variant={tk.status === "waiting" ? "warning" : tk.status === "resolved" ? "success" : "info"}>
        <AlertDescription>{tk.status_message}</AlertDescription>
      </Alert>
      {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("conversation")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <TicketThread messages={tk.messages ?? []} viewer="student" />
          {studentCanReply(tk.status) ? (
            <form
              className="space-y-2"
              onSubmit={async (e) => {
                e.preventDefault();
                if (reply.trim() && (await run("/messages", { body: reply.trim() }))) setReply("");
              }}
            >
              <Label htmlFor="req-reply">{t("replyLabel")}</Label>
              <Textarea id="req-reply" rows={3} maxLength={8000} value={reply} onChange={(e) => setReply(e.target.value)} />
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={action.busy || !reply.trim()}>
                  <Send /> {t("send")}
                </Button>
                <Button type="button" variant="outline" disabled={action.busy} onClick={() => run("/resolve")}>
                  <CheckCircle2 /> {t("markResolved")}
                </Button>
              </div>
            </form>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" disabled={action.busy} onClick={() => run("/reopen")}>
                <RotateCcw /> {t("reopen")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {tk.status === "resolved" && <Feedback ticket={tk} onSaved={setTicket} />}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("sharedTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div>
            <p className="text-xs font-semibold text-muted-foreground">{t("summary")}</p>
            <p className="whitespace-pre-wrap">{tk.summary}</p>
          </div>
          <SharedContext items={tk.shared_context} withdrawnAt={tk.context_withdrawn_at} />
          <p className="text-xs text-muted-foreground">{t("consentGiven", { date: formatDateTime(tk.consent_at, locale) })}</p>
          {tk.shared_context.length > 0 && !tk.context_withdrawn_at && (
            <Button variant="outline" size="sm" onClick={() => setWithdrawOpen(true)}>
              <Undo2 /> {t("withdraw")}
            </Button>
          )}
        </CardContent>
      </Card>

      <Dialog open={withdrawOpen} onOpenChange={setWithdrawOpen}>
        <DialogContent closeLabel={t("cancel")}>
          <DialogHeader>
            <DialogTitle>{t("withdrawTitle")}</DialogTitle>
            <DialogDescription>{t("withdrawBody")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setWithdrawOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={action.busy}
              onClick={async () => {
                if (await run("/withdraw-context")) setWithdrawOpen(false);
              }}
            >
              {t("withdraw")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Feedback({ ticket, onSaved }: { ticket: SupportTicket; onSaved: (t: SupportTicket) => void }) {
  const t = useTranslations("requests");
  const [rating, setRating] = useState(ticket.satisfaction ?? 0);
  const [comment, setComment] = useState(ticket.satisfaction_comment ?? "");
  const action = useAction();
  const [done, setDone] = useState(false);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("feedbackTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div role="radiogroup" aria-label={t("rating")} className="flex gap-1">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              role="radio"
              aria-checked={rating === n}
              aria-label={t("stars", { count: n })}
              onClick={() => setRating(n)}
              className="rounded p-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Star className={cn("size-6", n <= rating ? "fill-amber-400 text-amber-500" : "text-muted-foreground")} aria-hidden />
            </button>
          ))}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="fb-comment">{t("comment")}</Label>
          <Textarea id="fb-comment" rows={2} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} />
        </div>
        {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
        {done && (
          <Alert variant="success">
            <AlertTitle>{t("feedbackThanks")}</AlertTitle>
          </Alert>
        )}
        <Button
          disabled={!rating || action.busy}
          onClick={async () => {
            const res = await action.run(() =>
              api.post<SupportTicket>(`/api/v1/support/tickets/${ticket.id}/feedback`, {
                rating,
                comment: comment.trim() || undefined,
              }),
            );
            if (res) {
              setDone(true);
              onSaved(res);
            }
          }}
        >
          {t("sendFeedback")}
        </Button>
      </CardContent>
    </Card>
  );
}
