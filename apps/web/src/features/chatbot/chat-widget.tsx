"use client";

/**
 * Floating RAG assistant on student-facing pages. Signed in: persistent conversations (history, streaming, consented
 * Global Supporter handoff). Not signed in: a session-only chat (nothing stored on the server) - supporter help asks
 * the visitor to sign in. The answer language follows the site language (or the language the student writes in).
 * The conversation itself (state + view) is shared with the AI Office: `useAssistantChat` + `ChatBody`.
 */
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { History, MessageCircle, Minus, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatBody } from "@/features/chatbot/chat-body";
import { OPEN_CHAT_EVENT, type OpenChatDetail } from "@/features/chatbot/open-chat";
import { useAssistantChat } from "@/features/chatbot/use-assistant-chat";
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
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open || minimized) {
    return (
      <div className="fixed bottom-[calc(1.25rem+env(safe-area-inset-bottom))] right-[calc(1.25rem+env(safe-area-inset-right))] z-40 flex items-center gap-2">
        {minimized && open && (
          <button type="button" onClick={() => setMinimized(false)}
            className="rounded-full border border-border bg-card px-3 py-2 text-sm font-medium shadow-lg hover:bg-muted">
            {chat.busy ? t("answering") : t("minimizedLabel")}
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
          <p className="truncate text-xs text-muted-foreground">{chat.stage ? t(`stage.${chat.stage}`) : t("subtitle")}</p>
        </div>
        {chat.signedIn && (
          <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("history")} onClick={() => void chat.openHistory()}><History /></Button>
        )}
        <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("newChat")} onClick={chat.newChat}><Plus /></Button>
        <Button size="sm" variant="ghost" className="hidden size-8 p-0 sm:inline-flex" aria-label={t("minimize")} onClick={() => setMinimized(true)}><Minus /></Button>
        <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("close")} onClick={() => setOpen(false)}><X /></Button>
      </header>
      <ChatBody chat={chat} welcome={t("welcome")} examples={[t("example1"), t("example2"), t("example3")]}
        onNavigate={closeOnPhone} />
    </section>
  );
}

/** The widget is full-screen below Tailwind's `sm` breakpoint (640px). */
export function isPhoneLayout(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(max-width: 639.98px)").matches;
}
