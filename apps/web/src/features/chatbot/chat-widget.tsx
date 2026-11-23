"use client";

/**
 * Floating RAG assistant on student-facing pages. Signed in: persistent conversations (history, streaming, consented
 * Global Supporter handoff). Not signed in: a session-only chat (nothing stored on the server) - supporter help asks
 * the visitor to sign in. The answer language follows the site language (or the language the student writes in).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { History, LifeBuoy, MessageCircle, Minus, Plus, Send, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatMessageView, type ChatMsg } from "@/features/chatbot/chat-message";
import { HandoffReview } from "@/features/chatbot/handoff-review";
import { OPEN_CHAT_EVENT, type OpenChatDetail } from "@/features/chatbot/open-chat";
import { api, ApiError, errorMessage } from "@/lib/api";
import { postStream } from "@/lib/chat-stream";
import { cn } from "@/lib/utils";
import { useSession } from "@/lib/use-session";
import type { AnonymousChatResponse, AskResponse, Conversation, ConversationDetail, Page } from "@/types/api";

const HIDDEN_PREFIXES = ["/admin", "/login"];
const ANON_KEY = "sch-chat-visitor";

export function shouldShowChat(pathname: string | null): boolean {
  return !HIDDEN_PREFIXES.some((p) => pathname === p || pathname?.startsWith(p + "/"));
}

function read<T>(key: string, storage: "local" | "session"): T | null {
  try {
    const raw = (storage === "local" ? localStorage : sessionStorage).getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}
function write(key: string, value: unknown, storage: "local" | "session"): void {
  try {
    const s = storage === "local" ? localStorage : sessionStorage;
    if (value === null) s.removeItem(key);
    else s.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable (private mode): the chat still works for this page view */
  }
}

export function ChatWidget() {
  const pathname = usePathname();
  if (!shouldShowChat(pathname)) return null;
  return <ChatWidgetInner />;
}

function ChatWidgetInner() {
  const t = useTranslations("chatbot");
  const locale = useLocale();
  const session = useSession();
  const signedIn = Boolean(session.userId);
  const [open, setOpen] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [view, setView] = useState<"chat" | "history" | "handoff">("chat");
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<"searching" | "writing" | null>(null);
  const [dismissedOffer, setDismissedOffer] = useState<string | null>(null);
  const [history, setHistory] = useState<Conversation[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const convKey = session.userId ? `sch-chat-conv:${session.userId}` : null;

  // open from anywhere: openChat(question) events, links ending in #chat, and ?ask=… (e.g. the old /assistant?q=)
  useEffect(() => {
    const show = (question?: string) => {
      setOpen(true);
      setMinimized(false);
      setView("chat");
      if (question) setDraft(question);
    };
    const fromUrl = () => {
      const url = new URL(window.location.href);
      const ask = url.searchParams.get("ask");
      if (url.hash === "#chat" || ask) {
        show(ask ?? undefined);
        if (ask) {   // do not keep the question in the address bar / history
          url.searchParams.delete("ask");
          window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
        }
      }
    };
    const onOpen = (e: Event) => show((e as CustomEvent<OpenChatDetail>).detail?.question);
    fromUrl();
    window.addEventListener("hashchange", fromUrl);
    window.addEventListener(OPEN_CHAT_EVENT, onOpen);
    return () => {
      window.removeEventListener("hashchange", fromUrl);
      window.removeEventListener(OPEN_CHAT_EVENT, onOpen);
    };
  }, []);

  // restore: signed-in -> last conversation; visitor -> this browser session's messages
  useEffect(() => {
    if (!session.ready) return;
    if (signedIn && convKey) {
       
      setConvId(read<string>(convKey, "local"));
      setMessages([]);
    } else {
      setConvId(null);
      setMessages(read<ChatMsg[]>(ANON_KEY, "session") ?? []);
    }
  }, [session.ready, signedIn, convKey]);

  const loadConversation = useCallback(async (id: string) => {
    setLoadError(null);
    try {
      const d = await api.get<ConversationDetail>(`/api/v1/conversations/${encodeURIComponent(id)}`);
      setMessages(d.messages.map((m) => ({ ...m })));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setConvId(null);
        if (convKey) write(convKey, null, "local");
        setMessages([]);
      } else {
        setLoadError(errorMessage(err));
      }
    }
  }, [convKey]);

  useEffect(() => {
     
    if (open && signedIn && convId && messages.length === 0) void loadConversation(convId);
  }, [open, signedIn, convId, messages.length, loadConversation]);

  useEffect(() => {
    if (!signedIn) write(ANON_KEY, messages.filter((m) => !m.streaming).slice(-20), "session");
  }, [messages, signedIn]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, view]);

  useEffect(() => {
    if (open && !minimized && view === "chat") inputRef.current?.focus();
  }, [open, minimized, view]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  async function send(text: string) {
    const content = text.trim();
    if (!content || busy) return;
    setDraft("");
    setBusy(true);
    setStage("searching");
    const tmpUser = `u-${Date.now()}`;
    const priorTurns = messages.filter((m) => !m.streaming && !m.failed && m.metadata?.kind !== "handoff_created");
    setMessages((m) => [...m.filter((x) => !x.failed), { id: tmpUser, role: "user", content, citations: [], metadata: {} },
      { id: "streaming", role: "assistant", content: "", citations: [], metadata: {}, streaming: true }]);
    const ctl = new AbortController();
    abortRef.current = ctl;
    const onEvent = (e: { event: string; data: unknown }) => {
      if (e.event === "status") setStage((e.data as { stage: "searching" | "writing" }).stage);
      if (e.event === "delta") {
        const piece = (e.data as { text: string }).text;
        setMessages((m) => m.map((x) => (x.id === "streaming" ? { ...x, content: x.content + piece } : x)));
      }
    };
    try {
      if (signedIn) {
        let id = convId;
        if (!id) {
          id = (await api.post<Conversation>("/api/v1/conversations", { language: locale })).id;
          setConvId(id);
          if (convKey) write(convKey, id, "local");
        }
        const res = await postStream<AskResponse>(`/api/v1/conversations/${id}/messages/stream`,
          { content, language: locale }, { auth: true, signal: ctl.signal, onEvent });
        setMessages((m) => [...m.filter((x) => x.id !== tmpUser && x.id !== "streaming"), res.user_message, res.assistant_message]);
      } else {
        const res = await postStream<AnonymousChatResponse>("/api/v1/assistant/chat/stream", {
          message: content, language: locale,
          // only the visitor's own earlier questions: the server never trusts assistant turns sent by a browser
          history: priorTurns.filter((m) => m.role === "user").slice(-4)
            .map(({ role, content: c }) => ({ role, content: c.slice(0, 2000) })),
        }, { signal: ctl.signal, onEvent });
        setMessages((m) => m.map((x) => (x.id === "streaming" ? {
          id: `a-${Date.now()}`, role: "assistant", content: res.answer, citations: res.citations,
          metadata: res.metadata, language: res.language,
        } : x)));
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setMessages((m) => m.map((x) => (x.id === "streaming"
        ? { ...x, id: `e-${Date.now()}`, streaming: false, failed: true, content: chatError(err, t) } : x)));
      setDraft(content);
    } finally {
      setBusy(false);
      setStage(null);
      abortRef.current = null;
    }
  }

  function newChat() {
    abortRef.current?.abort();
    setConvId(null);
    if (convKey) write(convKey, null, "local");
    if (!signedIn) write(ANON_KEY, null, "session");
    setMessages([]);
    setView("chat");
  }

  // a source opened from the chat on a phone: the full-screen widget closes so the page is visible (the conversation
  // stays in memory and comes back with the chat button); on wider screens the widget stays open beside the page
  function closeOnPhone() {
    if (isPhoneLayout()) setOpen(false);
  }

  async function openHistory() {
    setView("history");
    try {
      setHistory((await api.get<Page<Conversation>>("/api/v1/conversations", { page_size: 20 })).items);
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }

  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant" && !m.streaming);
  const handoffSent = lastAssistant?.metadata?.kind === "handoff_created";
  const showOffer = Boolean(lastAssistant?.metadata?.offer_handoff) && !handoffSent && dismissedOffer !== lastAssistant?.id;
  const followUps = !busy && lastAssistant?.metadata?.follow_ups?.length ? lastAssistant.metadata.follow_ups : [];
  const examples = [t("example1"), t("example2"), t("example3")];

  if (!open || minimized) {
    return (
      <div className="fixed bottom-[calc(1.25rem+env(safe-area-inset-bottom))] right-[calc(1.25rem+env(safe-area-inset-right))] z-40 flex items-center gap-2">
        {minimized && open && (
          <button type="button" onClick={() => setMinimized(false)}
            className="rounded-full border border-border bg-card px-3 py-2 text-sm font-medium shadow-lg hover:bg-muted">
            {busy ? t("answering") : t("minimizedLabel")}
          </button>
        )}
        <button
          type="button"
          aria-label={t("open")}
          aria-expanded={false}
          onClick={() => { setOpen(true); setMinimized(false); }}
          className="flex size-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-xl transition hover:scale-105 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/40"
          data-testid="chat-launcher"
        >
          <MessageCircle className="size-6" aria-hidden />
        </button>
      </div>
    );
  }

  return (
    <section
      role="dialog"
      aria-modal="false"
      aria-label={t("title")}
      data-testid="chat-panel"
      className="fixed inset-0 z-50 flex h-[100dvh] flex-col bg-card text-card-foreground sm:inset-auto sm:bottom-[calc(1.25rem+env(safe-area-inset-bottom))] sm:right-5 sm:h-[min(680px,calc(100dvh-2.5rem))] sm:w-[420px] sm:rounded-2xl sm:border sm:border-border sm:shadow-2xl"
    >
      <header className="flex items-center gap-2 border-b border-border px-3 py-2.5 pt-[max(0.625rem,env(safe-area-inset-top))] sm:pt-2.5">
        <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-xs font-bold text-primary-foreground" aria-hidden>SCH</span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{t("title")}</p>
          <p className="truncate text-xs text-muted-foreground">{stage ? t(`stage.${stage}`) : t("subtitle")}</p>
        </div>
        {signedIn && (
          <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("history")} onClick={openHistory}><History /></Button>
        )}
        <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("newChat")} onClick={newChat}><Plus /></Button>
        <Button size="sm" variant="ghost" className="hidden size-8 p-0 sm:inline-flex" aria-label={t("minimize")} onClick={() => setMinimized(true)}><Minus /></Button>
        <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("close")} onClick={() => setOpen(false)}><X /></Button>
      </header>

      {view === "handoff" && convId ? (
        <HandoffReview
          conversationId={convId}
          onCancel={() => setView("chat")}
          onSent={() => {
            setView("chat");
            void loadConversation(convId);
          }}
        />
      ) : view === "history" ? (
        <div className="flex-1 overflow-y-auto p-3 text-sm" data-testid="chat-history">
          <Button variant="ghost" size="sm" onClick={() => setView("chat")}>{t("backToChat")}</Button>
          {!history && <p className="p-3 text-muted-foreground">{t("loading")}</p>}
          {history?.length === 0 && <p className="p-3 text-muted-foreground">{t("noHistory")}</p>}
          <ul className="mt-2 space-y-1">
            {history?.map((c) => (
              <li key={c.id}>
                <button type="button" className={cn("w-full rounded-lg px-3 py-2 text-left hover:bg-muted", c.id === convId && "bg-muted")}
                  onClick={() => {
                    setConvId(c.id);
                    if (convKey) write(convKey, c.id, "local");
                    setMessages([]);
                    setView("chat");
                  }}>
                  <span className="block truncate font-medium">{c.title}</span>
                  {c.last_message_preview && <span className="block truncate text-xs text-muted-foreground">{c.last_message_preview}</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <>
          <div ref={listRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-4" aria-live="polite" data-testid="chat-messages">
            {loadError && <p className="text-sm text-destructive">{loadError}</p>}
            {messages.length === 0 && (
              <div className="space-y-3">
                <div className="max-w-[85%] rounded-2xl rounded-bl-md bg-muted px-3.5 py-2.5 text-sm">{t("welcome")}</div>
                <div className="flex flex-wrap gap-2">
                  {examples.map((q) => (
                    <button key={q} type="button" onClick={() => void send(q)}
                      className="rounded-full border border-border px-3 py-1.5 text-left text-xs hover:bg-muted">{q}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) => (
              <ChatMessageView key={m.id} m={m} onRetry={m.failed ? () => void send(draft || "") : undefined}
                onNavigate={closeOnPhone} />
            ))}
            {showOffer && lastAssistant && (
              <div className="rounded-xl border border-border bg-background p-3 text-sm" data-testid="handoff-offer">
                <p className="flex items-center gap-2 font-medium"><LifeBuoy className="size-4 text-primary" aria-hidden /> {t("offerTitle")}</p>
                {signedIn ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button size="sm" onClick={() => setView("handoff")}>{t("offerYes")}</Button>
                    <Button size="sm" variant="ghost" onClick={() => setDismissedOffer(lastAssistant.id)}>{t("offerNo")}</Button>
                  </div>
                ) : (
                  <p className="mt-1 text-muted-foreground">
                    {t("offerSignIn")}{" "}
                    <Link href={`/login?next=${encodeURIComponent(pathname())}`} className="font-medium text-primary underline">{t("signIn")}</Link>
                  </p>
                )}
              </div>
            )}
            {followUps.length > 0 && (
              <div className="flex flex-wrap gap-2" aria-label={t("suggestions")}>
                {followUps.map((q) => (
                  <button key={q} type="button" onClick={() => void send(q)}
                    className="rounded-full border border-primary/30 px-3 py-1.5 text-left text-xs text-primary hover:bg-primary/5">{q}</button>
                ))}
              </div>
            )}
          </div>
          <form
            className="border-t border-border p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
            onSubmit={(e) => {
              e.preventDefault();
              void send(draft);
            }}
          >
            <div className="flex items-end gap-2">
              <label htmlFor="chat-input" className="sr-only">{t("inputLabel")}</label>
              <textarea
                id="chat-input"
                ref={inputRef}
                rows={1}
                value={draft}
                maxLength={2000}
                placeholder={t("placeholder")}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    void send(draft);
                  }
                }}
                className="max-h-32 min-h-10 flex-1 resize-none rounded-xl border border-input bg-background px-3 py-2 text-base sm:text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <Button type="submit" size="sm" className="size-10 shrink-0 rounded-xl p-0" disabled={busy || !draft.trim()} aria-label={t("send")}>
                <Send />
              </Button>
            </div>
            <p className="mt-1.5 text-[11px] text-muted-foreground">{signedIn ? t("disclaimer") : t("disclaimerVisitor")}</p>
          </form>
        </>
      )}
    </section>
  );
}

/** The widget is full-screen below Tailwind's `sm` breakpoint (640px). */
export function isPhoneLayout(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(max-width: 639.98px)").matches;
}

function pathname(): string {
  return typeof window === "undefined" ? "/" : window.location.pathname + window.location.search;
}


/** Friendly, localized error text for a failed assistant turn (stable error codes from the API). */
export function chatError(err: unknown, t: (key: string) => string): string {
  const code = err instanceof ApiError ? err.code : "";
  if (code === "daily_limit") return t("errors.dailyLimit");
  if (code === "rate_limited") return t("errors.rateLimited");
  if (code === "network_error" || code === "stream_interrupted") return t("errors.network");
  if (code === "internal_error" || (err instanceof ApiError && err.status >= 500)) return t("errors.generic");
  return errorMessage(err);
}
