"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/input";
import { LanguageSelect } from "@/features/account/language-select";
import { api, errorMessage } from "@/lib/api";
import { saveLocalePreference } from "@/lib/i18n/preference";
import { useAction } from "@/lib/use-action";
import type { LanguageCode, Me } from "@/types/api";

/** One-time prompt when the profile language was never chosen explicitly (e.g. old accounts). */
export function LanguagePrompt({ current, onDone }: { current: LanguageCode; onDone: () => void }) {
  const t = useTranslations("account");
  const router = useRouter();
  const [open, setOpen] = useState(true);
  const [lang, setLang] = useState<LanguageCode | "">(current);
  const action = useAction();

  async function save() {
    if (!lang) return;
    const res = await action.run(() => api.patch<Me>("/api/v1/me", { preferred_language: lang }));
    if (res) {
      saveLocalePreference(lang);
      setOpen(false);
      onDone();
      router.refresh();
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) onDone();
      }}
    >
      <DialogContent closeLabel={t("later")}>
        <DialogHeader>
          <DialogTitle>{t("promptTitle")}</DialogTitle>
          <DialogDescription>{t("promptBody")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="prompt-lang">{t("languageLabel")}</Label>
          <LanguageSelect id="prompt-lang" value={lang} onChange={setLang} />
        </div>
        {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
        <DialogFooter>
          <Button variant="outline" onClick={() => { setOpen(false); onDone(); }}>
            {t("later")}
          </Button>
          <Button disabled={!lang || action.busy} onClick={save}>
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
