"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { LogIn, LogOut, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export function AuthMenu() {
  const t = useTranslations("nav");
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const sb = getSupabaseBrowserClient();
    if (!sb) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- no client to subscribe to
      setReady(true);
      return;
    }
    sb.auth.getSession().then(({ data }) => {
      setEmail(data.session?.user.email ?? null);
      setReady(true);
    });
    const { data: sub } = sb.auth.onAuthStateChange((_e, session) => {
      setEmail(session?.user.email ?? null);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  async function signOut() {
    await getSupabaseBrowserClient()?.auth.signOut();
    router.push("/");
    router.refresh();
  }

  if (!ready) return <div className="h-9 w-20" aria-hidden />;
  if (!email) {
    return (
      <Button asChild variant="outline" size="sm">
        <Link href="/login">
          <LogIn /> {t("login")}
        </Link>
      </Button>
    );
  }
  return (
    <div className="flex items-center gap-1">
      <Button asChild variant="ghost" size="sm" title={email}>
        <Link href="/admin">
          <ShieldCheck /> <span className="hidden lg:inline">{t("admin")}</span>
        </Link>
      </Button>
      <Button variant="ghost" size="sm" onClick={signOut} aria-label={t("logout")}>
        <LogOut /> <span className="hidden lg:inline">{t("logout")}</span>
      </Button>
    </div>
  );
}
