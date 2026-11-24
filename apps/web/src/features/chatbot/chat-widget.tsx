"use client";

/**
 * Floating RAG assistant on student-facing pages. Signed in: persistent conversations (history, streaming, consented
 * Global Supporter handoff). Not signed in: a session-only chat (nothing stored on the server) - supporter help asks
 * the visitor to sign in. The answer language follows the site language (or the language the student writes in).
 * The conversation itself (state + view) is shared with the AI Office: `useAssistantChat` + `ChatBody`.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { History, Maximize2, Minimize2, Minus, Plus, Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatBody } from "@/features/chatbot/chat-body";
import { OPEN_CHAT_EVENT, type OpenChatDetail } from "@/features/chatbot/open-chat";
import { useAssistantChat } from "@/features/chatbot/use-assistant-chat";
import { cn } from "@/lib/utils";
import type { LanguageCode } from "@/types/api";

export { chatError } from "@/features/chatbot/use-assistant-chat";

// the AI Office has its own conversation panels (one per character), so the floating widget is not shown there
const HIDDEN_PREFIXES = ["/admin", "/login", "/ai-office"];

export function shouldShowChat(pathname: string | null): boolean {
  return !HIDDEN_PREFIXES.some((p) => pathname === p || pathname?.startsWith(p + "/"));
}

export function ChatWidget() {
  const pathname = usePathname();
  if (!shouldShowChat(pathname)) return null;
  return <ChatWidgetInner />;
}

function ChatWidgetInner() {
  const t = useTranslations("chatbot");
  const locale = useLocale() as LanguageCode;
  const [open, setOpen] = useState(false);
  const [minimized, setMinimized] = useState(false);
  // full screen is offered on the home page only (elsewhere the chat stays beside the page)
  const pathname = usePathname();
  const canFull = pathname === "/";
  const [fullRequested, setFull] = useState(false);
  const full = fullRequested && canFull;
  const chat = useAssistantChat({ language: locale, active: open });
  const { setView, setDraft } = chat;

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
  }, [setView, setDraft]);

  // a source opened from the chat on a phone: the full-screen widget closes so the page is visible (the conversation
  // stays in memory and comes back with the chat button); on wider screens the widget stays open beside the page
  function closeOnPhone() {
    if (isPhoneLayout()) setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    // Escape leaves full screen first, then closes the chat
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (full) setFull(false);
      else setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, full]);

  if (!open || minimized) {
    return (
      <div className="fixed bottom-[calc(1.25rem+env(safe-area-inset-bottom))] right-[calc(1.25rem+env(safe-area-inset-right))] z-40 flex items-center gap-2">
        {minimized && open && (
          <button type="button" onClick={() => setMinimized(false)}
            className="rounded-full border border-border bg-card px-3 py-2 text-sm font-medium shadow-lg hover:bg-muted">
            {chat.busy ? t("answering") : t("minimizedLabel")}
          </button>
        )}
        {!minimized && <AssistantNudge onOpen={() => { setOpen(true); setMinimized(false); }} />}
        <button
          type="button"
          aria-label={t("open")}
          aria-expanded={false}
          onClick={() => { setOpen(true); setMinimized(false); }}
          className="group relative flex h-16 items-center gap-2 rounded-full bg-primary py-1 pl-1 pr-4 text-primary-foreground shadow-xl transition hover:scale-105 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/40"
          data-testid="chat-launcher"
        >
          <AssistantAvatar size={56} online />
          {/* says what it is: an AI assistant (not a person) */}
          <span className="flex items-center gap-1 text-sm font-bold" aria-hidden>
            <Sparkles className="size-4" />
            <span className="sm:hidden">AI</span>
            <span className="hidden sm:inline">{t("launcherLabel")}</span>
          </span>
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
      data-fullscreen={full ? "true" : "false"}
      className={cn("fixed inset-0 z-50 flex h-[100dvh] flex-col bg-card text-card-foreground sm:rounded-2xl sm:border sm:border-border sm:shadow-2xl",
        full ? "sm:inset-4 sm:h-auto"
          : "sm:inset-auto sm:bottom-[calc(1.25rem+env(safe-area-inset-bottom))] sm:right-5 sm:h-[min(680px,calc(100dvh-2.5rem))] sm:w-[420px]")}
    >
      <header className="flex items-center gap-2 border-b border-border px-3 py-2.5 pt-[max(0.625rem,env(safe-area-inset-top))] sm:pt-2.5">
        <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-xs font-bold text-primary-foreground" aria-hidden>SCH</span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{t("title")}</p>
          <p className="truncate text-xs text-muted-foreground">{chat.stage ? t(`stage.${chat.stage}`) : t("subtitle")}</p>
        </div>
        {chat.signedIn && (
          <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("history")} onClick={() => void chat.openHistory()}><History /></Button>
        )}
        <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("newChat")} onClick={chat.newChat}><Plus /></Button>
        {canFull && (
          <Button size="sm" variant="ghost" className="hidden size-8 p-0 sm:inline-flex" data-testid="chat-fullscreen"
            aria-label={full ? t("exitFullScreen") : t("fullScreen")} aria-pressed={full} onClick={() => setFull(!full)}>
            {full ? <Minimize2 /> : <Maximize2 />}
          </Button>
        )}
        <Button size="sm" variant="ghost" className="hidden size-8 p-0 sm:inline-flex" aria-label={t("minimize")} onClick={() => setMinimized(true)}><Minus /></Button>
        <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("close")} onClick={() => setOpen(false)}><X /></Button>
      </header>
      {/* full screen: the conversation stays in a readable column in the middle */}
      <div className={full ? "mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col" : "contents"}>
        <ChatBody chat={chat} welcome={t("welcome")} examples={[t("example1"), t("example2"), t("example3")]}
          onNavigate={closeOnPhone} />
      </div>
    </section>
  );
}

/**
 * The AI assistant's face: Hana from the office artwork (assets/characters/Agent_General_AI.png), cropped from the
 * face to the chest (public/assistant/hana-avatar.*). Decorative: the button's label says what it is.
 */
export function AssistantAvatar({ size, online = false }: { size: number; online?: boolean }) {
  return (
    <span aria-hidden className="relative inline-flex shrink-0" style={{ width: size, height: size }}>
      <span className="office-bob flex size-full overflow-hidden rounded-full bg-[#E8F2FB] ring-2 ring-white">
        <picture className="contents">
          <source type="image/webp" srcSet="/assistant/hana-avatar.webp" />
          <img src="/assistant/hana-avatar.png" alt="" width={size} height={size} className="size-full object-cover" />
        </picture>
      </span>
      {online && <span className="absolute bottom-0.5 right-0.5 size-3 rounded-full bg-emerald-400 ring-2 ring-primary" />}
    </span>
  );
}

/** When the introduction bubble appears: first after a short pause, then again at intervals, a few times per visit. */
export const NUDGE = { firstMs: 3000, showMs: 8000, everyMs: 45000, maxPerSession: 4 } as const;
const NUDGE_KEY = "sch-assistant-nudge";
const NUDGE_MESSAGES = ["nudge1", "nudge2", "nudge3"] as const;

/**
 * A speech bubble next to the launcher that introduces the AI assistant ("Hi! I'm the SCH AI assistant ..."),
 * rotating a few short messages. It stops for good once the student opens the chat or closes a bubble, and
 * appears at most NUDGE.maxPerSession times per browser session (sessionStorage).
 */
function AssistantNudge({ onOpen }: { onOpen: () => void }) {
  const t = useTranslations("chatbot");
  const [shown, setShown] = useState<number | null>(null);      // index of the message on screen
  const count = useRef(0);

  const stopForGood = useCallback(() => {
    try {
      sessionStorage.setItem(NUDGE_KEY, "done");
    } catch {
      /* storage unavailable: the bubble simply stops for this page */
    }
    count.current = NUDGE.maxPerSession;
    setShown(null);
  }, []);

  useEffect(() => {
    let state: { count?: number; done?: boolean } = {};
    try {
      const raw = sessionStorage.getItem(NUDGE_KEY);
      state = raw === "done" ? { done: true } : { count: Number(raw) || 0 };
    } catch {
      /* no storage: count in memory only */
    }
    if (state.done) return;
    count.current = state.count ?? 0;
    const timers: number[] = [];
    const showNext = () => {
      if (count.current >= NUDGE.maxPerSession) return;
      const i = count.current % NUDGE_MESSAGES.length;
      count.current += 1;
      try {
        sessionStorage.setItem(NUDGE_KEY, String(count.current));
      } catch {
        /* ignore */
      }
      setShown(i);
      timers.push(window.setTimeout(() => setShown(null), NUDGE.showMs));
      timers.push(window.setTimeout(showNext, NUDGE.everyMs));
    };
    timers.push(window.setTimeout(showNext, NUDGE.firstMs));
    return () => timers.forEach((id) => window.clearTimeout(id));
  }, []);

  if (shown === null) return null;
  return (
    <div className="chat-nudge relative mr-1 max-w-[min(280px,calc(100vw-10rem))]" data-testid="assistant-nudge">
      <button type="button" onClick={() => { stopForGood(); onOpen(); }}
        className="block rounded-2xl rounded-br-sm bg-card px-4 py-3 pr-8 text-left text-sm leading-snug text-card-foreground shadow-xl ring-1 ring-border hover:bg-muted">
        <span className="flex items-start gap-2.5">
          {/* phones: the launcher right beside it already shows her face, the message gets the room */}
          <span className="hidden sm:inline-flex"><AssistantAvatar size={40} /></span>
          <span className="min-w-0">
            <span className="mb-0.5 flex items-center gap-1 text-xs font-bold text-primary">
              <Sparkles className="size-3.5" aria-hidden /> {t("launcherLabel")}
            </span>
            {t(NUDGE_MESSAGES[shown])}
          </span>
        </span>
      </button>
      <button type="button" aria-label={t("nudgeDismiss")} onClick={stopForGood} data-testid="assistant-nudge-close"
        className="absolute right-1.5 top-1.5 rounded-full p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
        <X className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}

/** The widget is full-screen below Tailwind's `sm` breakpoint (640px). */
export function isPhoneLayout(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(max-width: 639.98px)").matches;
}
