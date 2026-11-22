"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { AlertTriangle, Bell, CheckCheck, Info, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { relativeTime } from "@/lib/version-state";
import type { AdminNotification, NotificationList, NotificationSeverity } from "@/types/api";

const POLL_MS = 60_000;

const SEVERITY: Record<NotificationSeverity, { icon: typeof Info; cls: string }> = {
  info: { icon: Info, cls: "text-sky-700" },
  warning: { icon: AlertTriangle, cls: "text-amber-700" },
  error: { icon: XCircle, cls: "text-red-700" },
};

/** GET /admin/notifications with optional polling (only while the tab is visible). */
export function useNotifications(limit = 30, pollMs: number | null = POLL_MS) {
  const [data, setData] = useState<NotificationList | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.get<NotificationList>("/api/v1/admin/notifications", { limit }));
      setError(null);
    } catch (err) {
      setError(err);
    }
  }, [limit]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- start of an async fetch cycle
    void load();
    if (!pollMs) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, pollMs);
    return () => clearInterval(id);
  }, [load, pollMs]);

  const markAll = useCallback(async () => {
    await api.post("/api/v1/admin/notifications/read");
    await load();
  }, [load]);

  return { data, error, reload: load, markAll };
}

export function NotificationItems({ items, onNavigate }: { items: AdminNotification[]; onNavigate?: () => void }) {
  const t = useTranslations("admin.notifications");
  const locale = useLocale();
  if (items.length === 0) return <p className="p-3 text-sm text-muted-foreground">{t("empty")}</p>;
  return (
    <ul className="divide-y divide-border">
      {items.map((n) => {
        const sev = SEVERITY[n.severity] ?? SEVERITY.info;
        const Icon = sev.icon;
        const body = (
          <div className="flex gap-2 p-3">
            <Icon className={cn("mt-0.5 size-4 shrink-0", sev.cls)} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className={cn("text-sm", n.unread ? "font-semibold" : "font-medium")}>{n.title}</p>
              {n.message && <p className="mt-0.5 line-clamp-3 text-xs text-muted-foreground">{n.message}</p>}
              <p className="mt-0.5 text-xs text-muted-foreground">
                <time dateTime={n.created_at}>{relativeTime(n.created_at, locale)}</time>
              </p>
            </div>
            {n.unread && <span className="mt-1.5 size-2 shrink-0 rounded-full bg-primary" aria-hidden />}
          </div>
        );
        return (
          <li key={n.id}>
            {n.link ? (
              <Link href={n.link} onClick={onNavigate} className="block hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none">
                {body}
              </Link>
            ) : (
              body
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Header bell with unread count and a dropdown panel. */
export function NotificationBell() {
  const t = useTranslations("admin.notifications");
  const { data, error, markAll } = useNotifications();
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
        variant="outline"
        size="sm"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={unread ? `${t("label")} – ${t("unread", { count: unread })}` : t("label")}
        onClick={() => setOpen((o) => !o)}
      >
        <Bell /> <span className="hidden sm:inline">{t("label")}</span>
        {unread > 0 && (
          <span className="ml-1 rounded-full bg-destructive px-1.5 py-0.5 text-[10px] font-semibold leading-none text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </Button>
      {open && (
        <div role="region" aria-label={t("label")} className="absolute right-0 z-40 mt-2 w-[min(24rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-border bg-card shadow-lg">
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
          <div className="max-h-96 overflow-auto">
            {error != null && !data ? (
              <p className="p-3 text-sm text-red-700">{t("error")}</p>
            ) : (
              <NotificationItems items={data?.items ?? []} onNavigate={() => setOpen(false)} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
