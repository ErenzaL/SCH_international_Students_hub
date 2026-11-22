"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { LifeBuoy, LogIn, LogOut, ShieldCheck, UserCog } from "lucide-react";
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
      <Button asChild variant="ghost" size="sm" title={t("myRequests")}>
        <Link href="/support/requests">
          <LifeBuoy /> <span className="hidden xl:inline">{t("myRequests")}</span>
        </Link>
      </Button>
      <Button asChild variant="ghost" size="sm" title={session.email ?? t("account")}>
        <Link href="/account">
          <UserCog /> <span className="hidden xl:inline">{t("account")}</span>
        </Link>
      </Button>
      {me.data?.is_staff && (
        <Button asChild variant="ghost" size="sm">
          <Link href="/admin">
            <ShieldCheck /> <span className="hidden lg:inline">{t("admin")}</span>
          </Link>
        </Button>
      )}
      <Button variant="ghost" size="sm" onClick={signOut} aria-label={t("logout")}>
        <LogOut /> <span className="hidden lg:inline">{t("logout")}</span>
      </Button>
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
