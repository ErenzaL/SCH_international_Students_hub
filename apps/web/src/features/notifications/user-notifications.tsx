"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Bell, CheckCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { notificationHref } from "@/lib/support";
import { cn } from "@/lib/utils";
import { relativeTime } from "@/lib/version-state";
import type { RealtimeChannel } from "@supabase/supabase-js";
import type { UserNotification, UserNotificationList } from "@/types/api";

const POLL_MS = 60_000;
type Listener = (n: UserNotification) => void;
const listeners = new Set<Listener>();

/** Subscribe to new notifications of the signed-in user (fired by Realtime or polling). */
export function onUserNotification(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/**
 * ONE Realtime channel per user, shared by every component that needs it (e.g. the site-header bell and the
 * admin-shell bell). supabase-js returns the existing channel for a repeated topic, and adding a
 * `postgres_changes` callback to a channel that already subscribed throws - which crashed every admin page.
 * Realtime problems must never break the page: on any error we stay on polling.
 */
type Shared = { channel: RealtimeChannel; subscribers: Set<() => void>; live: boolean; liveSubs: Set<(l: boolean) => void> };
const shared = new Map<string, Shared>();

export function subscribeUserChannel(userId: string, onInsert: () => void, onLive: (live: boolean) => void): () => void {
  const sb = getSupabaseBrowserClient();
  if (!sb) return () => {};
  let entry = shared.get(userId);
  if (!entry) {
    try {
      const created: Shared = { channel: null as never, subscribers: new Set(), live: false, liveSubs: new Set() };
      created.channel = sb
        .channel(`user-notifications-${userId}`)
        .on(
          "postgres_changes",
          { event: "INSERT", schema: "public", table: "user_notifications", filter: `user_id=eq.${userId}` },
          () => created.subscribers.forEach((fn) => fn()),
        )
        .subscribe((status) => {
          created.live = status === "SUBSCRIBED";
          created.liveSubs.forEach((fn) => fn(created.live));
        });
      entry = created;
      shared.set(userId, entry);
    } catch (err) {
      console.warn("Realtime notifications unavailable; using polling.", err);
      return () => {};
    }
  }
  const e = entry;
  e.subscribers.add(onInsert);
  e.liveSubs.add(onLive);
  onLive(e.live);
  return () => {
    e.subscribers.delete(onInsert);
    e.liveSubs.delete(onLive);
    if (e.subscribers.size === 0 && shared.get(userId) === e) {
      shared.delete(userId);
      void sb.removeChannel(e.channel).catch(() => undefined);
    }
  };
}

/**
 * GET /me/notifications + Supabase Realtime (INSERT on public.user_notifications filtered to the user;
 * RLS limits rows to the owner). Falls back to polling every 60 s while the tab is visible.
 */
export function useUserNotifications(userId: string | null) {
  const [data, setData] = useState<UserNotificationList | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [live, setLive] = useState(false);
  const lastTop = useRef<number | null>(null);

  const load = useCallback(async () => {
    if (!userId) return;
    try {
      const res = await api.get<UserNotificationList>("/api/v1/me/notifications", { limit: 30 });
      const top = res.items[0]?.id ?? null;
      if (lastTop.current !== null && top !== null && top > lastTop.current) {
        res.items.filter((n) => n.id > (lastTop.current ?? 0)).forEach((n) => listeners.forEach((l) => l(n)));
      }
      lastTop.current = top;
      setData(res);
      setError(null);
    } catch (err) {
      setError(err);
    }
  }, [userId]);

  useEffect(() => {
    if (!userId) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- start of an async fetch cycle
    void load();
    const id = setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, POLL_MS);
    const unsubscribe = subscribeUserChannel(userId, () => void load(), setLive);
    return () => {
      clearInterval(id);
      unsubscribe();
    };
  }, [load, userId]);

  const markAll = useCallback(async () => {
    await api.post("/api/v1/me/notifications/read", {});
    await load();
  }, [load]);

  return { data, error, live, reload: load, markAll };
}

export function UserNotificationBell({ userId, isStaff = false }: { userId: string; isStaff?: boolean }) {
  const t = useTranslations("notify");
  const locale = useLocale();
  const { data, markAll } = useUserNotifications(userId);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const unread = data?.unread ?? 0;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <Button
        variant="ghost"
        size="sm"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={unread ? `${t("label")} – ${t("unread", { count: unread })}` : t("label")}
        onClick={() => setOpen((o) => !o)}
      >
        <Bell />
        {unread > 0 && (
          <span className="rounded-full bg-destructive px-1.5 py-0.5 text-[10px] font-semibold leading-none text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </Button>
      {open && (
        <div
          role="region"
          aria-label={t("label")}
          className="absolute right-0 z-50 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-border bg-card shadow-lg"
        >
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <p className="text-sm font-semibold">{t("label")}</p>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy || unread === 0}
              onClick={async () => {
                setBusy(true);
                try {
                  await markAll();
                } finally {
                  setBusy(false);
                }
              }}
            >
              <CheckCheck /> {t("markAll")}
            </Button>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {!data || data.items.length === 0 ? (
              <p className="p-3 text-sm text-muted-foreground">{t("empty")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {data.items.map((n) => {
                  const href = notificationHref(n, isStaff);
                  const unreadItem = !n.read_at;
                  const body = (
                    <div className="flex gap-2 p-3">
                      <div className="min-w-0 flex-1">
                        <p className={cn("text-sm", unreadItem ? "font-semibold" : "font-medium")}>{n.title}</p>
                        {n.body && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{n.body}</p>}
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          <time dateTime={n.created_at}>{relativeTime(n.created_at, locale)}</time>
                        </p>
                      </div>
                      {unreadItem && <span className="mt-1.5 size-2 shrink-0 rounded-full bg-primary" aria-hidden />}
                    </div>
                  );
                  return (
                    <li key={n.id}>
                      {href ? (
                        <Link href={href} onClick={() => setOpen(false)} className="block hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none">
                          {body}
                        </Link>
                      ) : (
                        body
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
