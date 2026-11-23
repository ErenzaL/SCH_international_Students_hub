"use client";

/**
 * One conversation with the existing RAG assistant (shared by the floating chat widget and the AI Office).
 *
 * Signed in: persistent conversations through /api/v1/conversations (history, streaming, consented Global Supporter
 * handoff). Not signed in: a session-only chat through /api/v1/assistant/chat/stream (nothing stored on the server).
 * `language` is the answer language sent to the backend (it answers in it unless the student explicitly asks for
 * another language). `scope` keeps separate conversations apart (e.g. one per AI Office character); the default
 * scope is the floating widget's conversation.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { ChatMsg } from "@/features/chatbot/chat-message";
import { api, ApiError, errorMessage } from "@/lib/api";
import { postStream } from "@/lib/chat-stream";
import { useSession } from "@/lib/use-session";
import type { AnonymousChatResponse, AskResponse, Conversation, ConversationDetail, LanguageCode, Page } from "@/types/api";

const ANON_KEY = "sch-chat-visitor";

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

export type ChatView = "chat" | "history" | "handoff";

export interface AssistantChat {
  signedIn: boolean;
  messages: ChatMsg[];
  draft: string;
  setDraft: (v: string) => void;
  busy: boolean;
  stage: "searching" | "writing" | null;
  view: ChatView;
  setView: (v: ChatView) => void;
  convId: string | null;
  history: Conversation[] | null;
  loadError: string | null;
  dismissedOffer: string | null;
  setDismissedOffer: (id: string | null) => void;
  send: (text: string) => Promise<void>;
  newChat: () => void;
  openHistory: () => Promise<void>;
  selectConversation: (id: string) => void;
  reloadConversation: () => void;
  /** stop a running answer (closing a panel) */
  abort: () => void;
}

export function useAssistantChat({ language, scope, active = true }: {
  language: LanguageCode;
  scope?: string;
  /** the conversation is visible: load a signed-in conversation's messages */
  active?: boolean;
}): AssistantChat {
  const t = useTranslations("chatbot");
  const session = useSession();
  const signedIn = Boolean(session.userId);
  const [view, setView] = useState<ChatView>("chat");
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<"searching" | "writing" | null>(null);
  const [dismissedOffer, setDismissedOffer] = useState<string | null>(null);
  const [history, setHistory] = useState<Conversation[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const suffix = scope ? `:${scope}` : "";
  const convKey = session.userId ? `sch-chat-conv:${session.userId}${suffix}` : null;
  const anonKey = `${ANON_KEY}${suffix}`;

  // restore: signed-in -> last conversation; visitor -> this browser session's messages
  useEffect(() => {
    if (!session.ready) return;
    if (signedIn && convKey) {
       
      setConvId(read<string>(convKey, "local"));
      setMessages([]);
    } else {
      setConvId(null);
      setMessages(read<ChatMsg[]>(anonKey, "session") ?? []);
    }
  }, [session.ready, signedIn, convKey, anonKey]);

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
     
    if (active && signedIn && convId && messages.length === 0) void loadConversation(convId);
  }, [active, signedIn, convId, messages.length, loadConversation]);

  useEffect(() => {
    if (!signedIn) write(anonKey, messages.filter((m) => !m.streaming).slice(-20), "session");
  }, [messages, signedIn, anonKey]);

  // a running answer is stopped when the conversation goes away (no stream keeps writing into an unmounted panel)
  useEffect(() => () => abortRef.current?.abort(), []);

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
          id = (await api.post<Conversation>("/api/v1/conversations", { language })).id;
          setConvId(id);
          if (convKey) write(convKey, id, "local");
        }
        const res = await postStream<AskResponse>(`/api/v1/conversations/${id}/messages/stream`,
          { content, language }, { auth: true, signal: ctl.signal, onEvent });
        setMessages((m) => [...m.filter((x) => x.id !== tmpUser && x.id !== "streaming"), res.user_message, res.assistant_message]);
      } else {
        const res = await postStream<AnonymousChatResponse>("/api/v1/assistant/chat/stream", {
          message: content, language,
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
    if (!signedIn) write(anonKey, null, "session");
    setMessages([]);
    setView("chat");
  }

  async function openHistory() {
    setView("history");
    try {
      setHistory((await api.get<Page<Conversation>>("/api/v1/conversations", { page_size: 20 })).items);
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }

  function selectConversation(id: string) {
    setConvId(id);
    if (convKey) write(convKey, id, "local");
    setMessages([]);
    setView("chat");
  }

  return {
    signedIn, messages, draft, setDraft, busy, stage, view, setView, convId, history, loadError, dismissedOffer,
    setDismissedOffer, send, newChat, openHistory, selectConversation,
    reloadConversation: () => { if (convId) void loadConversation(convId); },
    abort: () => abortRef.current?.abort(),
  };
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
