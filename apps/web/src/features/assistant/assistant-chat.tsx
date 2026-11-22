"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Bot, ExternalLink, FileText, Send, User } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { ErrorState } from "@/components/shared/states";
import { ScopeBadge, ExactMatchBadge, StaleBadge } from "@/components/shared/badges";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { cn, formatDate } from "@/lib/utils";
import type { AssistantStatus, LanguageCode, SearchResponse, SearchResult } from "@/types/api";

type ChatMessage =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; pending: true }
  | { id: number; role: "assistant"; pending?: false; response: SearchResponse }
  | { id: number; role: "assistant"; pending?: false; error: ApiError };

const SUGGESTION_KEYS = ["s1", "s2", "s3", "s4"] as const;

export function AssistantChat({ initialQuestion = "" }: { initialQuestion?: string }) {
  const t = useTranslations("assistant");
  const locale = useLocale() as LanguageCode;
  const status = useApi<AssistantStatus>("assistant-status", () =>
    api.get<AssistantStatus>("/api/v1/assistant/status"),
  );

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const idRef = useRef(1);
  const endRef = useRef<HTMLDivElement>(null);
  const autoSent = useRef(false);

  const busy = messages.some((m) => m.role === "assistant" && m.pending);
  const retrievalDown = status.data?.retrieval === "unavailable";

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    const userId = idRef.current++;
    const botId = idRef.current++;
    setMessages((m) => [...m, { id: userId, role: "user", text: q }, { id: botId, role: "assistant", pending: true }]);
    setInput("");
    try {
      const response = await api.post<SearchResponse>("/api/v1/knowledge/search", {
        query: q,
        language: locale,
        top_k: 5,
      });
      setMessages((m) => m.map((x) => (x.id === botId ? { id: botId, role: "assistant", response } : x)));
      setSelectedId(botId);
    } catch (e) {
      const error =
        e instanceof ApiError
          ? e
          : new ApiError({ status: 0, code: "unexpected_error", message: e instanceof Error ? e.message : "Error" });
      setMessages((m) => m.map((x) => (x.id === botId ? { id: botId, role: "assistant", error } : x)));
    }
  }

  useEffect(() => {
    if (initialQuestion && !autoSent.current) {
      autoSent.current = true;
      void ask(initialQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);

  const selected = messages.find(
    (m): m is Extract<ChatMessage, { response: SearchResponse }> =>
      m.id === selectedId && "response" in m,
  );
  const citations: SearchResult[] = selected?.response.results ?? [];

  return (
    <div className="space-y-4">
      {status.error ? (
        <ErrorState error={status.error} onRetry={status.reload} />
      ) : (
        status.data?.answer_generation !== "enabled" && (
          <Alert variant="info" data-testid="setup-banner">
            <Bot className="size-4" aria-hidden />
            <AlertTitle>{t("setupTitle")}</AlertTitle>
            <AlertDescription>
              <p>{t("setupBody")}</p>
              {status.data?.reason && <p className="mt-1 text-xs">{status.data.reason}</p>}
            </AlertDescription>
          </Alert>
        )
      )}
      {retrievalDown && (
        <Alert variant="warning">
          <AlertTitle>{t("retrievalUnavailableTitle")}</AlertTitle>
          <AlertDescription>{t("retrievalUnavailableBody")}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <Card className="flex min-h-[28rem] flex-col">
          <CardContent className="flex flex-1 flex-col gap-4 p-4">
            <div className="flex-1 space-y-4 overflow-y-auto" aria-live="polite" aria-label={t("conversation")} role="log">
              {messages.length === 0 && (
                <div className="space-y-3 py-6 text-center">
                  <Bot className="mx-auto size-10 text-primary" aria-hidden />
                  <p className="font-medium">{t("welcome")}</p>
                  <p className="mx-auto max-w-md text-sm text-muted-foreground">{t("welcomeBody")}</p>
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {t("suggested")}
                    </p>
                    <div className="flex flex-wrap justify-center gap-2">
                      {SUGGESTION_KEYS.map((k) => (
                        <Button
                          key={k}
                          variant="outline"
                          size="sm"
                          disabled={busy || retrievalDown}
                          onClick={() => ask(t(`suggestions.${k}`))}
                        >
                          {t(`suggestions.${k}`)}
                        </Button>
                      ))}
                    </div>
                  </div>
                </div>
              )}
              {messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  selected={m.id === selectedId}
                  onSelect={() => setSelectedId(m.id)}
                  onRetry={() => {
                    const idx = messages.findIndex((x) => x.id === m.id);
                    const prev = messages[idx - 1];
                    if (prev && prev.role === "user") {
                      setMessages((all) => all.filter((x) => x.id !== m.id && x.id !== prev.id));
                      void ask(prev.text);
                    }
                  }}
                />
              ))}
              <div ref={endRef} />
            </div>

            <form
              className="flex gap-2 border-t border-border pt-4"
              onSubmit={(e) => {
                e.preventDefault();
                void ask(input);
              }}
            >
              <div className="flex-1">
                <Label htmlFor="chat-input" className="sr-only">
                  {t("inputLabel")}
                </Label>
                <Input
                  id="chat-input"
                  value={input}
                  maxLength={500}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={t("placeholder")}
                  disabled={busy || retrievalDown}
                />
              </div>
              <Button type="submit" disabled={busy || retrievalDown || !input.trim()}>
                <Send /> <span className="hidden sm:inline">{t("send")}</span>
                <span className="sr-only sm:hidden">{t("send")}</span>
              </Button>
            </form>
          </CardContent>
        </Card>

        <aside aria-label={t("sources")}>
          <Card className="lg:sticky lg:top-20">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileText className="size-4 text-primary" aria-hidden /> {t("sources")}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {citations.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("noSources")}</p>
              ) : (
                citations.map((r, i) => <Citation key={r.chunk_id} index={i + 1} result={r} />)
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}

function MessageBubble({
  message: m,
  selected,
  onSelect,
  onRetry,
}: {
  message: ChatMessage;
  selected: boolean;
  onSelect: () => void;
  onRetry: () => void;
}) {
  const t = useTranslations("assistant");
  if (m.role === "user") {
    return (
      <div className="flex justify-end gap-2">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-sm text-primary-foreground">
          {m.text}
        </div>
        <User className="mt-1 size-5 shrink-0 text-muted-foreground" aria-hidden />
      </div>
    );
  }
  return (
    <div className="flex gap-2">
      <Bot className="mt-1 size-5 shrink-0 text-primary" aria-hidden />
      <div
        className={cn(
          "max-w-[90%] space-y-2 rounded-2xl rounded-bl-sm border border-border bg-muted/50 px-4 py-3 text-sm",
          selected && "ring-2 ring-ring",
        )}
      >
        {m.pending && (
          <p role="status" className="animate-pulse text-muted-foreground">
            {t("searching")}
          </p>
        )}
        {"error" in m && <ErrorState error={m.error} onRetry={onRetry} />}
        {"response" in m && (
          <>
            <Badge variant="warning">{t("retrievedLabel")}</Badge>
            {m.response.retrieval.warning && (
              <p className="text-xs text-amber-900">{m.response.retrieval.warning}</p>
            )}
            {m.response.results.length === 0 ? (
              <p>{t("noEvidence")}</p>
            ) : (
              <>
                <p className="text-muted-foreground">
                  {t("foundPassages", { count: m.response.results.length })}
                </p>
                <ol className="space-y-2">
                  {m.response.results.map((r, i) => (
                    <li key={r.chunk_id} className="rounded-md border border-border bg-background p-2">
                      <p className="text-xs font-semibold text-primary">
                        [{i + 1}] {r.document_title}
                        {r.heading ? ` — ${r.heading}` : ""}
                      </p>
                      <p className="mt-1 line-clamp-4 whitespace-pre-wrap">{r.passage}</p>
                    </li>
                  ))}
                </ol>
                {!selected && (
                  <Button variant="link" size="sm" className="h-auto p-0" onClick={onSelect}>
                    {t("showSources")}
                  </Button>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Citation({ index, result: r }: { index: number; result: SearchResult }) {
  const t = useTranslations("assistant");
  const locale = useLocale();
  return (
    <div className="rounded-lg border border-border p-3 text-sm">
      <p className="font-medium">
        [{index}] {r.document_title}
      </p>
      {r.heading && <p className="text-xs text-muted-foreground">{r.heading}</p>}
      <div className="mt-1 flex flex-wrap gap-1">
        <ScopeBadge scope={r.scope} />
        {r.page != null && <Badge variant="outline">{t("page", { page: r.page })}</Badge>}
        {r.exact_match && <ExactMatchBadge />}
        {r.is_stale && <StaleBadge days={r.verification_age_days} />}
      </div>
      <dl className="mt-2 space-y-0.5 text-xs text-muted-foreground">
        <div>{r.organization}</div>
        <div>
          {t("sourcePublished")}: {formatDate(r.source_published_at, locale)}
        </div>
        <div>
          {t("verifiedAt")}: {formatDate(r.verified_at, locale)}
        </div>
        <div>
          {t("score")}: {r.score.toFixed(3)}
          {r.similarity != null && ` · ${t("similarity")}: ${r.similarity.toFixed(3)}`}
        </div>
      </dl>
      {r.source_url ? (
        <a
          href={r.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex items-center gap-1 break-all text-xs font-medium text-primary hover:underline"
        >
          <ExternalLink className="size-3.5 shrink-0" aria-hidden /> {t("openSource")}
        </a>
      ) : null}
    </div>
  );
}
