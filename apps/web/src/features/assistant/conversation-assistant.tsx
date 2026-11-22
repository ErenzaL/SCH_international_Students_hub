"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Bot, Check, ExternalLink, Lock, MessageSquarePlus, Pencil, Search, Send, Trash2, User, UserRoundCheck, X } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/shared/states";
import { LanguageSelect } from "@/features/account/language-select";
import { HandoffDialog } from "@/features/support/handoff-dialog";
import { api, errorMessage } from "@/lib/api";
import { LOCALE_LABELS } from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import { relativeTime } from "@/lib/version-state";
import type { AskResponse, Conversation, ConversationDetail, ConversationMessage, LanguageCode, Me, Page } from "@/types/api";

export function ConversationAssistant({ userId, initialQuestion = "" }: { userId: string; initialQuestion?: string }) {
  const t = useTranslations("chat");
  const me = useApi<Me>(`me:${userId}`, () => api.get<Me>("/api/v1/me"));
  const [q, setQ] = useState("");
  const [listTick, setListTick] = useState(0);
  const list = useApi<Page<Conversation>>(`convs:${userId}:${q}:${listTick}`, () =>
    api.get<Page<Conversation>>("/api/v1/conversations", { q, page_size: 50 }),
  );
  const [activeId, setActiveId] = useState<string | null>(null);
  const action = useAction();
  const autoStarted = useRef(false);

  const preferred = me.data?.preferred_language ?? "en";

  async function newConversation(): Promise<Conversation | undefined> {
    const c = await action.run(() => api.post<Conversation>("/api/v1/conversations", { language: preferred }));
    if (c) {
      setActiveId(c.id);
      setListTick((x) => x + 1);
    }
    return c;
  }

  // ?q=... from the home page: start a conversation with that question once
  const [pendingQuestion, setPendingQuestion] = useState(initialQuestion);
  useEffect(() => {
    if (!initialQuestion || autoStarted.current || !me.data) return;
    autoStarted.current = true;
    void newConversation();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me.data]);

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
      <aside aria-label={t("historyTitle")}>
        <Card>
          <CardContent className="space-y-3 p-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">{t("historyTitle")}</h2>
              <Button size="sm" onClick={() => void newConversation()} disabled={action.busy || !me.data}>
                <MessageSquarePlus /> {t("new")}
              </Button>
            </div>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
              <Label htmlFor="conv-search" className="sr-only">
                {t("search")}
              </Label>
              <Input id="conv-search" className="pl-8" placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            {list.loading && <LoadingState rows={3} />}
            {list.error && <ErrorState error={list.error} onRetry={list.reload} />}
            {list.data && list.data.items.length === 0 && <p className="text-sm text-muted-foreground">{t("noConversations")}</p>}
            {list.data && list.data.items.length > 0 && (
              <ul className="max-h-[60vh] space-y-1 overflow-y-auto">
                {list.data.items.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => setActiveId(c.id)}
                      aria-current={c.id === activeId ? "true" : undefined}
                      className={cn(
                        "w-full rounded-md px-2 py-2 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        c.id === activeId && "bg-secondary",
                      )}
                    >
                      <span className="flex items-center gap-1 font-medium">
                        {c.is_private && <Lock className="size-3 shrink-0" aria-label={t("private")} />}
                        <span className="truncate">{c.title}</span>
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">{c.last_message_preview ?? "—"}</span>
                      <span className="block text-xs text-muted-foreground">
                        {LOCALE_LABELS[c.language]} · {relativeTime(c.last_message_at ?? c.created_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
          </CardContent>
        </Card>
      </aside>
      <div className="min-w-0">
        {activeId ? (
          <ConversationView
            key={activeId}
            id={activeId}
            preferred={preferred}
            initialQuestion={pendingQuestion}
            onConsumedInitial={() => setPendingQuestion("")}
            onChanged={() => setListTick((x) => x + 1)}
            onDeleted={() => {
              setActiveId(null);
              setListTick((x) => x + 1);
            }}
          />
        ) : (
          <EmptyState
            title={t("emptyTitle")}
            description={t("emptyBody")}
            action={
              <Button onClick={() => void newConversation()} disabled={action.busy || !me.data}>
                <MessageSquarePlus /> {t("new")}
              </Button>
            }
          />
        )}
        <p className="mt-3 text-xs text-muted-foreground">{t("privacyNote")}</p>
      </div>
    </div>
  );
}

function ConversationView({
  id,
  preferred,
  initialQuestion,
  onConsumedInitial,
  onChanged,
  onDeleted,
}: {
  id: string;
  preferred: LanguageCode;
  initialQuestion: string;
  onConsumedInitial: () => void;
  onChanged: () => void;
  onDeleted: () => void;
}) {
  const t = useTranslations("chat");
  const detail = useApi<ConversationDetail>(`conv:${id}`, () => api.get<ConversationDetail>(`/api/v1/conversations/${id}`));
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [input, setInput] = useState("");
  const [msgLang, setMsgLang] = useState<LanguageCode | "">("");
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [handoff, setHandoff] = useState(false);
  const action = useAction();
  const ask = useAction();
  const endRef = useRef<HTMLDivElement>(null);
  const sentInitial = useRef(false);

  useEffect(() => {
    if (detail.data) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- sync local list with the loaded conversation
      setMessages(detail.data.messages);
      setTitle(detail.data.title);
      setMsgLang(detail.data.language);
    }
  }, [detail.data]);
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);

  async function send(text: string) {
    const content = text.trim();
    if (!content || ask.busy) return;
    const res = await ask.run(() =>
      api.post<AskResponse>(`/api/v1/conversations/${id}/messages`, { content, language: msgLang || undefined }),
    );
    if (res) {
      setMessages((m) => [...m, res.user_message, res.assistant_message]);
      setInput("");
      onChanged();
    }
  }
  useEffect(() => {
    if (initialQuestion && detail.data && !sentInitial.current && detail.data.messages.length === 0) {
      sentInitial.current = true;
      onConsumedInitial();
      void send(initialQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.data]);

  if (detail.loading) return <LoadingState rows={4} />;
  if (detail.error) return <ErrorState error={detail.error} onRetry={detail.reload} />;
  const c = detail.data;
  if (!c) return null;

  async function patch(body: Record<string, unknown>) {
    const res = await action.run(() => api.patch<Conversation>(`/api/v1/conversations/${id}`, body));
    if (res) {
      detail.reload();
      onChanged();
    }
    return res;
  }
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const offer = Boolean(lastAssistant?.metadata?.offer_handoff);

  return (
    <Card className="flex min-h-[32rem] flex-col">
      <CardContent className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3">
          {editing ? (
            <form
              className="flex flex-1 items-center gap-2"
              onSubmit={async (e) => {
                e.preventDefault();
                if (title.trim() && (await patch({ title: title.trim() }))) setEditing(false);
              }}
            >
              <Label htmlFor="conv-title" className="sr-only">
                {t("rename")}
              </Label>
              <Input id="conv-title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} autoFocus />
              <Button size="sm" type="submit" disabled={!title.trim() || action.busy} aria-label={t("save")}>
                <Check />
              </Button>
              <Button size="sm" type="button" variant="ghost" onClick={() => setEditing(false)} aria-label={t("cancel")}>
                <X />
              </Button>
            </form>
          ) : (
            <>
              <h2 className="min-w-0 flex-1 truncate font-semibold">{c.title}</h2>
              <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
                <Pencil /> <span className="hidden sm:inline">{t("rename")}</span>
              </Button>
            </>
          )}
          <label className="flex items-center gap-1.5 text-xs">
            <input type="checkbox" checked={c.is_private} disabled={action.busy} onChange={(e) => void patch({ is_private: e.target.checked })} />
            {t("privateToggle")}
          </label>
          <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(true)}>
            <Trash2 /> <span className="hidden sm:inline">{t("delete")}</span>
          </Button>
        </div>
        {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}

        <div className="flex-1 space-y-4 overflow-y-auto" role="log" aria-live="polite" aria-label={t("messages")}>
          {messages.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">{t("startHint")}</p>}
          {messages.map((m) => (
            <MessageItem key={m.id} message={m} onHandoff={() => setHandoff(true)} />
          ))}
          {ask.busy && (
            <p role="status" className="animate-pulse text-sm text-muted-foreground">
              {t("searching")}
            </p>
          )}
          <div ref={endRef} />
        </div>
        {ask.error && <ErrorState error={ask.error} />}

        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed border-border p-2">
          <p className="text-xs text-muted-foreground">{offer ? t("handoffSuggested") : t("handoffAlways")}</p>
          <Button size="sm" variant={offer ? "default" : "outline"} onClick={() => setHandoff(true)}>
            <UserRoundCheck /> {t("talkToSupporter")}
          </Button>
        </div>

        <form
          className="flex flex-wrap gap-2 border-t border-border pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
        >
          <div className="min-w-0 flex-1">
            <Label htmlFor="conv-input" className="sr-only">
              {t("inputLabel")}
            </Label>
            <Input
              id="conv-input"
              value={input}
              maxLength={2000}
              placeholder={t("placeholder")}
              onChange={(e) => setInput(e.target.value)}
              disabled={ask.busy}
            />
          </div>
          <div className="w-40">
            <Label htmlFor="conv-lang" className="sr-only">
              {t("answerLanguage")}
            </Label>
            <LanguageSelect id="conv-lang" value={msgLang} onChange={setMsgLang} />
          </div>
          <Button type="submit" disabled={ask.busy || !input.trim()}>
            <Send /> <span className="sr-only sm:not-sr-only">{t("send")}</span>
          </Button>
        </form>
        <p className="text-xs text-muted-foreground">{t("languageNote", { language: LOCALE_LABELS[preferred] })}</p>
      </CardContent>

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent closeLabel={t("cancel")}>
          <DialogHeader>
            <DialogTitle>{t("deleteTitle")}</DialogTitle>
            <DialogDescription>{t("deleteBody")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(false)}>
              {t("cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={action.busy}
              onClick={async () => {
                const ok = await action.run(() => api.delete(`/api/v1/conversations/${id}`));
                if (ok !== undefined) {
                  setConfirmDelete(false);
                  onDeleted();
                }
              }}
            >
              <Trash2 /> {t("delete")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {handoff && (
        <HandoffDialog
          open={handoff}
          onOpenChange={setHandoff}
          conversation={{ ...c, messages }}
          defaultLanguage={preferred}
        />
      )}
    </Card>
  );
}

function MessageItem({ message: m, onHandoff }: { message: ConversationMessage; onHandoff: () => void }) {
  const t = useTranslations("chat");
  const locale = useLocale();
  if (m.role === "user") {
    return (
      <div className="flex justify-end gap-2">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-sm text-primary-foreground" lang={m.language}>
          {m.content}
        </div>
        <User className="mt-1 size-5 shrink-0 text-muted-foreground" aria-hidden />
      </div>
    );
  }
  return (
    <div className="flex gap-2">
      <Bot className="mt-1 size-5 shrink-0 text-primary" aria-hidden />
      <div className="max-w-[90%] space-y-2 rounded-2xl rounded-bl-sm border border-border bg-muted/50 px-4 py-3 text-sm">
        <Badge variant="warning">{t("retrievedOnly")}</Badge>
        <p className="whitespace-pre-wrap" lang={m.language}>
          {m.content}
        </p>
        {m.citations.length > 0 && (
          <ol className="space-y-1 border-t border-border pt-2 text-xs">
            {m.citations.map((ct) => (
              <li key={`${m.id}-${ct.n}`} className="flex flex-wrap items-center gap-1">
                <span className="font-semibold">[{ct.n}]</span>
                {ct.document_id ? (
                  <Link href={`/knowledge/${ct.document_id}`} className="text-primary hover:underline">
                    {ct.document_title}
                  </Link>
                ) : (
                  <span>{ct.document_title}</span>
                )}
                {ct.organization && <span className="text-muted-foreground">· {ct.organization}</span>}
                {ct.is_stale && <Badge variant="warning">{t("stale")}</Badge>}
                {ct.source_url && (
                  <a href={ct.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline">
                    <ExternalLink className="size-3" aria-hidden /> {t("officialSource")}
                  </a>
                )}
              </li>
            ))}
          </ol>
        )}
        {m.metadata?.offer_handoff && (
          <Alert variant="info">
            <AlertTitle>{t("handoffOfferTitle")}</AlertTitle>
            <AlertDescription className="space-y-2">
              <p>{t("handoffOfferBody")}</p>
              <Button size="sm" onClick={onHandoff}>
                <UserRoundCheck /> {t("talkToSupporter")}
              </Button>
            </AlertDescription>
          </Alert>
        )}
        <p className="text-[11px] text-muted-foreground">
          <time dateTime={m.created_at}>{relativeTime(m.created_at, locale)}</time>
        </p>
      </div>
    </div>
  );
}
