"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { AlertOctagon, ArrowLeft, CheckCircle2, Clock, Hand, HelpCircle, Lock, RotateCcw, Send, Shuffle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { onUserNotification } from "@/features/notifications/user-notifications";
import { PriorityBadge, TicketStatusBadge } from "@/features/support/ticket-badges";
import { SharedContext, TicketThread } from "@/features/support/ticket-thread";
import { api, ApiError, errorMessage } from "@/lib/api";
import { LOCALE_LABELS } from "@/lib/constants";
import { shouldPollTicket } from "@/lib/support";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import type { SupportTicket, TicketPriority, TransferTarget } from "@/types/api";

const PRIORITIES: TicketPriority[] = ["low", "normal", "high", "urgent"];

export function StaffTicket({ id }: { id: string }) {
  const t = useTranslations("admin.support");
  const locale = useLocale();
  const { data, error, loading, reload } = useApi<SupportTicket>(`staff-ticket:${id}`, () =>
    api.get<SupportTicket>(`/api/v1/support/tickets/${id}`),
  );
  const [ticket, setTicket] = useState<SupportTicket | null>(null);
  const [reply, setReply] = useState("");
  const [escalateOpen, setEscalateOpen] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);
  const action = useAction();
  const current = ticket ?? data;

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the loaded value replaces the local copy
    if (data) setTicket(data);
  }, [data]);
  useEffect(() => {
    const status = current?.status;
    const timer = setInterval(() => {
      if (shouldPollTicket(status, document.visibilityState === "visible")) reload();
    }, 10_000);
    const off = onUserNotification((n) => n.entity_id === id && reload());
    return () => {
      clearInterval(timer);
      off();
    };
  }, [current?.status, id, reload]);

  if (loading && !current) return <LoadingState rows={4} />;
  if (error && !current) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 403)) {
      return (
        <Alert variant="destructive">
          <Lock className="size-4" aria-hidden />
          <AlertTitle>{t("noAccessTitle")}</AlertTitle>
          <AlertDescription>
            <p>{t("noAccessBody")}</p>
            <Button asChild size="sm" variant="outline" className="mt-3">
              <Link href="/admin/support">{t("backToInbox")}</Link>
            </Button>
          </AlertDescription>
        </Alert>
      );
    }
    return <ErrorState error={error} onRetry={reload} />;
  }
  if (!current) return null;
  const tk = current;
  const handler = Boolean(tk.is_mine || tk.can_manage);

  async function run(path: string, body?: unknown) {
    const res = await action.run(() => api.post<SupportTicket>(`/api/v1/support/tickets/${id}${path}`, body));
    if (res && "messages" in res) setTicket(res);
    else if (res) reload();
    return res;
  }

  return (
    <div className="space-y-5">
      <Button asChild variant="ghost" size="sm">
        <Link href="/admin/support">
          <ArrowLeft /> {t("backToInbox")}
        </Link>
      </Button>
      <PageHeader
        title={`#${tk.ticket_number} · ${tk.subject}`}
        description={t("ticketMeta", {
          language: LOCALE_LABELS[tk.language],
          student: tk.student_display_name ?? "—",
          date: formatDateTime(tk.created_at, locale),
        })}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <TicketStatusBadge status={tk.status} />
            <PriorityBadge priority={tk.priority} />
            {tk.escalated && <Badge variant="danger">{t("escalated")}</Badge>}
          </div>
        }
      />
      {tk.escalation_reason && (
        <Alert variant="warning">
          <AlertTitle>{t("escalationReason")}</AlertTitle>
          <AlertDescription>{tk.escalation_reason}</AlertDescription>
        </Alert>
      )}
      {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}

      <div className="grid gap-5 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("thread")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <TicketThread messages={tk.messages ?? []} viewer="staff" />
              {tk.status !== "resolved" && handler && (
                <div className="space-y-2">
                  <Label htmlFor="st-reply">{t("replyLabel")}</Label>
                  <Textarea id="st-reply" rows={4} maxLength={8000} value={reply} onChange={(e) => setReply(e.target.value)} />
                  <div className="flex flex-wrap gap-2">
                    <Button
                      disabled={action.busy || !reply.trim()}
                      onClick={async () => {
                        if (await run("/messages", { body: reply.trim() })) setReply("");
                      }}
                    >
                      <Send /> {t("reply")}
                    </Button>
                    <Button
                      variant="outline"
                      disabled={action.busy || !reply.trim()}
                      onClick={async () => {
                        if (await run("/request-info", { body: reply.trim() })) setReply("");
                      }}
                    >
                      <HelpCircle /> {t("requestInfo")}
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("sharedTitle")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <Alert variant="info">
                <AlertDescription>{t("sharedNote", { date: formatDateTime(tk.consent_at, locale) })}</AlertDescription>
              </Alert>
              <div>
                <p className="text-xs font-semibold text-muted-foreground">{t("summary")}</p>
                <p className="whitespace-pre-wrap">{tk.summary}</p>
              </div>
              <SharedContext items={tk.shared_context} withdrawnAt={tk.context_withdrawn_at} />
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-3">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("actions")}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {(tk.status === "assigned" || tk.status === "waiting") && (
                <Button disabled={action.busy} onClick={() => run("/accept")}>
                  <Hand /> {t("accept")}
                </Button>
              )}
              {handler && (tk.status === "open" || tk.status === "assigned") && (
                <Button variant="outline" disabled={action.busy} onClick={() => run("/waiting")}>
                  <Clock /> {t("markWaiting")}
                </Button>
              )}
              {handler && tk.status !== "resolved" && tk.status !== "waiting" && (
                <Button variant="outline" disabled={action.busy} onClick={() => run("/resolve")}>
                  <CheckCircle2 /> {t("resolve")}
                </Button>
              )}
              {tk.status === "resolved" && (
                <Button variant="outline" disabled={action.busy} onClick={() => run("/reopen")}>
                  <RotateCcw /> {t("reopen")}
                </Button>
              )}
              {handler && tk.status !== "resolved" && (
                <>
                  <Button variant="outline" disabled={action.busy} onClick={() => setTransferOpen(true)}>
                    <Shuffle /> {t("transfer")}
                  </Button>
                  <Button variant="outline" disabled={action.busy} onClick={() => setEscalateOpen(true)}>
                    <AlertOctagon /> {t("escalate")}
                  </Button>
                  <div className="space-y-1">
                    <Label htmlFor="st-priority">{t("priority")}</Label>
                    <Select
                      id="st-priority"
                      value={tk.priority}
                      disabled={action.busy}
                      onChange={(e) => void run("/priority", { priority: e.target.value })}
                    >
                      {PRIORITIES.map((p) => (
                        <option key={p} value={p}>
                          {p}
                        </option>
                      ))}
                    </Select>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-1 p-4 text-xs text-muted-foreground">
              <p>
                {t("studentLanguage")}: {tk.student_preferred_language ? LOCALE_LABELS[tk.student_preferred_language] : "—"}
              </p>
              <p>
                {t("assignedAt")}: {formatDateTime(tk.assigned_at, locale)}
              </p>
              <p>
                {t("acceptedAt")}: {formatDateTime(tk.accepted_at, locale)}
              </p>
              <p>{t("auditNote")}</p>
            </CardContent>
          </Card>
        </aside>
      </div>

      <ReasonDialog
        open={escalateOpen}
        onOpenChange={setEscalateOpen}
        title={t("escalateTitle")}
        description={t("escalateBody")}
        confirm={t("escalate")}
        busy={action.busy}
        onConfirm={async (reason) => {
          if (await run("/escalate", { reason })) setEscalateOpen(false);
        }}
      />
      {transferOpen && (
        <TransferDialog
          ticketId={id}
          open={transferOpen}
          onOpenChange={setTransferOpen}
          onDone={() => {
            setTransferOpen(false);
            setTicket(null);
            reload();
          }}
        />
      )}
    </div>
  );
}

function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  confirm,
  busy,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: string;
  confirm: string;
  busy: boolean;
  onConfirm: (reason: string) => void;
}) {
  const t = useTranslations("admin.support");
  const [reason, setReason] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent closeLabel={t("cancel")}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <Label htmlFor="reason-input">{t("reason")}</Label>
        <Textarea id="reason-input" rows={3} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={busy || reason.trim().length < 3} onClick={() => onConfirm(reason.trim())}>
            {confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TransferDialog({
  ticketId,
  open,
  onOpenChange,
  onDone,
}: {
  ticketId: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onDone: () => void;
}) {
  const t = useTranslations("admin.support");
  const targets = useApi<{ items: TransferTarget[] }>(`transfer-targets:${ticketId}`, () =>
    api.get<{ items: TransferTarget[] }>(`/api/v1/support/tickets/${ticketId}/transfer-targets`),
  );
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const action = useAction();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent closeLabel={t("cancel")}>
        <DialogHeader>
          <DialogTitle>{t("transferTitle")}</DialogTitle>
          <DialogDescription>{t("transferBody")}</DialogDescription>
        </DialogHeader>
        {targets.loading && <LoadingState rows={1} />}
        {targets.error && <ErrorState error={targets.error} onRetry={targets.reload} />}
        {targets.data && (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="tr-target">{t("transferTo")}</Label>
              <Select id="tr-target" value={to} onChange={(e) => setTo(e.target.value)}>
                <option value="">{t("backToQueue")}</option>
                {targets.data.items.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.display_name ?? x.id}
                    {x.is_available ? "" : ` (${t("unavailable")})`}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tr-reason">{t("reason")}</Label>
              <Input id="tr-reason" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
          </div>
        )}
        {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={action.busy || !targets.data}
            onClick={async () => {
              const res = await action.run(() =>
                api.post(`/api/v1/support/tickets/${ticketId}/transfer`, {
                  to_supporter_id: to || null,
                  reason: reason.trim() || undefined,
                }),
              );
              if (res !== undefined) onDone();
            }}
          >
            <Shuffle /> {t("transfer")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
