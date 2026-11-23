"use client";

/** The conversation itself (messages, suggestions, supporter offer, history, handoff review, input) - shared by the
 * floating chat widget and the AI Office dialogue panel. State lives in `useAssistantChat`. */
import { useEffect, useRef } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { LifeBuoy, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatMessageView } from "@/features/chatbot/chat-message";
import { HandoffReview } from "@/features/chatbot/handoff-review";
import type { AssistantChat } from "@/features/chatbot/use-assistant-chat";
import { cn } from "@/lib/utils";

export function ChatBody({ chat, welcome, examples, autoFocus = true, inputId = "chat-input", lang, onNavigate }: {
  chat: AssistantChat;
  welcome: string;
  examples: string[];
  autoFocus?: boolean;
  inputId?: string;
  /** language of the welcome / example text (for screen readers and fonts) */
  lang?: string;
  /** a citation link to a page of this site was followed (the floating widget closes on phones) */
  onNavigate?: () => void;
}) {
  const t = useTranslations("chatbot");
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const { messages, view, busy, draft, setDraft, send, signedIn, convId, history, loadError } = chat;

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, view]);

  useEffect(() => {
    if (autoFocus && view === "chat") inputRef.current?.focus();
  }, [autoFocus, view]);

  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant" && !m.streaming);
  const handoffSent = lastAssistant?.metadata?.kind === "handoff_created";
  const showOffer = Boolean(lastAssistant?.metadata?.offer_handoff) && !handoffSent && chat.dismissedOffer !== lastAssistant?.id;
  const followUps = !busy && lastAssistant?.metadata?.follow_ups?.length ? lastAssistant.metadata.follow_ups : [];

  if (view === "handoff" && convId) {
    return (
      <HandoffReview
        conversationId={convId}
        onCancel={() => chat.setView("chat")}
        onSent={() => {
          chat.setView("chat");
          chat.reloadConversation();
        }}
      />
    );
  }
  if (view === "history") {
    return (
      <div className="flex-1 overflow-y-auto p-3 text-sm" data-testid="chat-history">
        <Button variant="ghost" size="sm" onClick={() => chat.setView("chat")}>{t("backToChat")}</Button>
        {!history && <p className="p-3 text-muted-foreground">{t("loading")}</p>}
        {history?.length === 0 && <p className="p-3 text-muted-foreground">{t("noHistory")}</p>}
        <ul className="mt-2 space-y-1">
          {history?.map((c) => (
            <li key={c.id}>
              <button type="button" className={cn("w-full rounded-lg px-3 py-2 text-left hover:bg-muted", c.id === convId && "bg-muted")}
                onClick={() => chat.selectConversation(c.id)}>
                <span className="block truncate font-medium">{c.title}</span>
                {c.last_message_preview && <span className="block truncate text-xs text-muted-foreground">{c.last_message_preview}</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <>
      <div ref={listRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-4" aria-live="polite" data-testid="chat-messages">
        {loadError && <p className="text-sm text-destructive">{loadError}</p>}
        {messages.length === 0 && (
          <div className="space-y-3" lang={lang}>
            <div className="max-w-[85%] rounded-2xl rounded-bl-md bg-muted px-3.5 py-2.5 text-sm" data-testid="chat-welcome">{welcome}</div>
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
            onNavigate={onNavigate} />
        ))}
        {showOffer && lastAssistant && (
          <div className="rounded-xl border border-border bg-background p-3 text-sm" data-testid="handoff-offer">
            <p className="flex items-center gap-2 font-medium"><LifeBuoy className="size-4 text-primary" aria-hidden /> {t("offerTitle")}</p>
            {signedIn ? (
              <div className="mt-2 flex flex-wrap gap-2">
                <Button size="sm" onClick={() => chat.setView("handoff")}>{t("offerYes")}</Button>
                <Button size="sm" variant="ghost" onClick={() => chat.setDismissedOffer(lastAssistant.id)}>{t("offerNo")}</Button>
              </div>
            ) : (
              <p className="mt-1 text-muted-foreground">
                {t("offerSignIn")}{" "}
                <Link href={`/login?next=${encodeURIComponent(currentPath())}`} className="font-medium text-primary underline">{t("signIn")}</Link>
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
          <label htmlFor={inputId} className="sr-only">{t("inputLabel")}</label>
          <textarea
            id={inputId}
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
  );
}

function currentPath(): string {
  return typeof window === "undefined" ? "/" : window.location.pathname + window.location.search;
}
