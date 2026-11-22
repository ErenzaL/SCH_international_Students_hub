"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { History, LogIn } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/shared/states";
import { AssistantChat } from "@/features/assistant/assistant-chat";
import { ConversationAssistant } from "@/features/assistant/conversation-assistant";
import { isSupabaseConfigured } from "@/lib/constants";
import { useSession } from "@/lib/use-session";

/** Signed-in: persistent conversations. Signed-out: the stateless retrieval chat (nothing is saved). */
export function AssistantEntry({ initialQuestion = "" }: { initialQuestion?: string }) {
  const t = useTranslations("chat");
  const session = useSession();
  if (!session.ready) return <LoadingState rows={3} />;
  if (session.userId) return <ConversationAssistant userId={session.userId} initialQuestion={initialQuestion} />;
  return (
    <div className="space-y-4">
      {isSupabaseConfigured && (
        <Alert variant="default">
          <History className="size-4" aria-hidden />
          <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
            <span>{t("signInToSave")}</span>
            <Button asChild size="sm" variant="outline">
              <Link href="/login?next=%2Fassistant">
                <LogIn /> {t("signIn")}
              </Link>
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <AssistantChat initialQuestion={initialQuestion} />
    </div>
  );
}
