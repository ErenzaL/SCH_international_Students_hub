import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Bot, Megaphone, UserRoundCheck } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { OpenChatButton } from "@/features/chatbot/open-chat";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/shared/states";

export default async function SupportPage() {
  const t = await getTranslations("support");
  const steps = ["step1", "step2", "step3"] as const;
  const contacts = ["office", "supporters", "emergency"] as const;
  return (
    <div className="mx-auto max-w-4xl space-y-8 px-4 py-8">
      <PageHeader title={t("title")} description={t("intro")} />

      <section aria-labelledby="how-h">
        <h2 id="how-h" className="mb-3 text-xl font-semibold">
          {t("howTitle")}
        </h2>
        <ol className="space-y-3">
          {steps.map((s, i) => (
            <li key={s} className="flex gap-3 rounded-lg border border-border bg-card p-4">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-foreground">
                {i + 1}
              </span>
              <p className="text-sm">{t(s)}</p>
            </li>
          ))}
        </ol>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <Link href="/announcements">
              <Megaphone /> {t("linkAnnouncements")}
            </Link>
          </Button>
          <OpenChatButton variant="outline">
            <Bot /> {t("linkAssistant")}
          </OpenChatButton>
        </div>
      </section>

      <section aria-labelledby="contact-h" className="space-y-3">
        <h2 id="contact-h" className="text-xl font-semibold">
          {t("contactTitle")}
        </h2>
        <Alert variant="warning">
          <AlertTitle>{t("placeholderTitle")}</AlertTitle>
          <AlertDescription>{t("placeholderBody")}</AlertDescription>
        </Alert>
        <div className="grid gap-4 md:grid-cols-3">
          {contacts.map((c) => (
            <Card key={c}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <UserRoundCheck className="size-4 text-primary" aria-hidden /> {t(`contacts.${c}.name`)}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-sm text-muted-foreground">
                <p>{t(`contacts.${c}.desc`)}</p>
                <p className="font-mono text-xs">{t("tbd")}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
