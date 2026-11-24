"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ChevronDown, LifeBuoy, LogIn, LogOut, ShieldCheck, UserCog } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LanguagePrompt } from "@/features/account/language-prompt";
import { UserNotificationBell } from "@/features/notifications/user-notifications";
import { api } from "@/lib/api";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { useApi } from "@/lib/use-api";
import { useSession } from "@/lib/use-session";
import type { Me } from "@/types/api";

export function AuthMenu() {
  const t = useTranslations("nav");
  const router = useRouter();
  const session = useSession();
  const me = useApi<Me>(session.userId ? `me:${session.userId}` : null, () => api.get<Me>("/api/v1/me"));
  const [promptDismissed, setPromptDismissed] = useState(false);

  async function signOut() {
    await getSupabaseBrowserClient()?.auth.signOut();
    router.push("/");
    router.refresh();
  }

  if (!session.ready) return <div className="h-9 w-20" aria-hidden />;
  if (!session.userId) {
    return (
      <Button asChild variant="outline" size="sm">
        <Link href="/login">
          <LogIn /> {t("login")}
        </Link>
      </Button>
    );
  }
  const showPrompt = !promptDismissed && me.data && me.data.preferred_language_confirmed === false;
  return (
    <div className="flex items-center gap-1">
      <UserNotificationBell userId={session.userId} isStaff={Boolean(me.data?.is_staff)} />
      <ProfileMenu email={session.email ?? me.data?.email ?? null} name={me.data?.display_name ?? null}
        isStaff={Boolean(me.data?.is_staff)} onSignOut={signOut} />
      {showPrompt && me.data && (
        <LanguagePrompt
          current={me.data.preferred_language}
          onDone={() => {
            setPromptDismissed(true);
            me.reload();
          }}
        />
      )}
    </div>
  );
}

/**
 * The signed-in account's links in one menu (My requests, Account, Admin for staff, Sign out), so the header keeps
 * one row at every width instead of growing a button per link.
 */
function ProfileMenu({ email, name, isStaff, onSignOut }: {
  email: string | null;
  name: string | null;
  isStaff: boolean;
  onSignOut: () => void;
}) {
  const t = useTranslations("nav");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const label = name || email || t("account");
  const initial = (label.trim()[0] ?? "?").toUpperCase();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    box.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const item = "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none";
  return (
    <div className="relative" ref={box}>
      <button type="button" aria-haspopup="menu" aria-expanded={open} aria-label={t("account")} data-testid="profile-menu-button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-9 items-center gap-1 rounded-full pl-0.5 pr-1.5 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span aria-hidden className="flex size-8 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-foreground">
          {initial}
        </span>
        <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
      </button>
      {open && (
        <div role="menu" aria-label={t("account")} data-testid="profile-menu"
          className="absolute right-0 top-full z-50 mt-2 w-64 rounded-xl border border-border bg-card p-1.5 shadow-xl">
          <p className="truncate px-3 pb-2 pt-1.5 text-xs text-muted-foreground" title={email ?? undefined}>{email ?? label}</p>
          <Link role="menuitem" href="/support/requests" className={item} onClick={() => setOpen(false)}>
            <LifeBuoy className="size-4" aria-hidden /> {t("myRequests")}
          </Link>
          <Link role="menuitem" href="/account" className={item} onClick={() => setOpen(false)}>
            <UserCog className="size-4" aria-hidden /> {t("account")}
          </Link>
          {isStaff && (
            <Link role="menuitem" href="/admin" className={item} onClick={() => setOpen(false)}>
              <ShieldCheck className="size-4" aria-hidden /> {t("admin")}
            </Link>
          )}
          <div className="my-1 border-t border-border" />
          <button role="menuitem" type="button" className={item} onClick={() => { setOpen(false); onSignOut(); }}>
            <LogOut className="size-4" aria-hidden /> {t("logout")}
          </button>
        </div>
      )}
    </div>
  );
}
