"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { LogIn } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/shared/states";
import { useSession } from "@/lib/use-session";

/** Renders children only for signed-in users; otherwise a sign-in prompt (with a safe `next`). */
export function RequireSession({ next, children }: { next: string; children: (userId: string) => React.ReactNode }) {
  const t = useTranslations("account");
  const session = useSession();
  if (!session.ready) return <LoadingState rows={2} />;
  if (!session.userId) {
    return (
      <Alert variant="info">
        <AlertTitle>{t("signInRequiredTitle")}</AlertTitle>
        <AlertDescription>
          <p>{t("signInRequiredBody")}</p>
          <Button asChild size="sm" className="mt-3">
            <Link href={`/login?next=${encodeURIComponent(next)}`}>
              <LogIn /> {t("signIn")}
            </Link>
          </Button>
        </AlertDescription>
      </Alert>
    );
  }
  return <>{children(session.userId)}</>;
}
