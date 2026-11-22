"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Save } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { LanguageSelect } from "@/features/account/language-select";
import { RequireSession } from "@/features/account/require-session";
import { api, errorMessage } from "@/lib/api";
import { LOCALE_LABELS } from "@/lib/constants";
import { saveLocalePreference } from "@/lib/i18n/preference";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import type { LanguageCode, Me } from "@/types/api";

export function AccountSettings() {
  return <RequireSession next="/account">{(uid) => <AccountForm userId={uid} />}</RequireSession>;
}

function AccountForm({ userId }: { userId: string }) {
  const me = useApi<Me>(`me:${userId}`, () => api.get<Me>("/api/v1/me"));
  if (me.loading) return <LoadingState rows={3} />;
  if (me.error) return <ErrorState error={me.error} onRetry={me.reload} />;
  if (!me.data) return null;
  return <Form me={me.data} onSaved={me.reload} />;
}

function Form({ me, onSaved }: { me: Me; onSaved: () => void }) {
  const t = useTranslations("account");
  const router = useRouter();
  const [lang, setLang] = useState<LanguageCode | "">(me.preferred_language);
  const [name, setName] = useState(me.display_name ?? "");
  const [done, setDone] = useState(false);
  const action = useAction();
  const changed = lang !== me.preferred_language || name.trim() !== (me.display_name ?? "");

  async function save() {
    if (!lang) return;
    setDone(false);
    const body: Record<string, string> = { preferred_language: lang };
    if (name.trim()) body.display_name = name.trim();
    const res = await action.run(() => api.patch<Me>("/api/v1/me", body));
    if (res) {
      saveLocalePreference(lang); // the interface follows the preference
      setDone(true);
      onSaved();
      router.refresh();
    }
  }

  return (
    <Card>
      <CardContent className="space-y-5 p-6">
        <div className="space-y-1.5">
          <Label htmlFor="acc-email">{t("email")}</Label>
          <Input id="acc-email" value={me.email ?? ""} disabled />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="acc-name">{t("displayName")}</Label>
          <Input id="acc-name" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="acc-lang">{t("languageLabel")}</Label>
          <LanguageSelect id="acc-lang" value={lang} onChange={setLang} aria-describedby="acc-lang-help" />
          <p id="acc-lang-help" className="text-sm text-muted-foreground">
            {t("languageHelp")}
          </p>
        </div>
        <Alert variant="info">
          <AlertDescription>{t("existingRequestsNote", { language: LOCALE_LABELS[me.preferred_language] })}</AlertDescription>
        </Alert>
        {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
        {done && <Alert variant="success">{t("saved")}</Alert>}
        <Button disabled={!changed || !lang || action.busy} onClick={save}>
          <Save /> {t("save")}
        </Button>
      </CardContent>
    </Card>
  );
}
