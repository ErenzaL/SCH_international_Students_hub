"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { CheckCircle2, Lock, Send } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Textarea } from "@/components/ui/input";
import { LanguageSelect } from "@/features/account/language-select";
import { api, errorMessage } from "@/lib/api";
import { LOCALE_LABELS } from "@/lib/constants";
import {
  buildHandoffPayload,
  defaultSelection,
  defaultSubject,
  defaultSummary,
  SUBJECT_MAX,
  SUMMARY_MAX,
  type HandoffError,
} from "@/lib/support";
import { useAction } from "@/lib/use-action";
import type { ConversationDetail, LanguageCode, SupportTicket } from "@/types/api";

/**
 * Explicit, consented handoff. Nothing is shared until the student confirms; only the checked messages
 * and the (editable) summary are copied into the support request.
 */
export function HandoffDialog({
  open,
  onOpenChange,
  conversation,
  defaultLanguage,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  conversation: ConversationDetail | null;
  defaultLanguage: LanguageCode;
}) {
  const t = useTranslations("handoff");
  const messages = useMemo(() => conversation?.messages ?? [], [conversation]);
  const isPrivate = Boolean(conversation?.is_private);
  const initialSummary = defaultSummary(messages);
  const [language, setLanguage] = useState<LanguageCode | "">(defaultLanguage);
  const [summary, setSummary] = useState(initialSummary);
  const [subject, setSubject] = useState(defaultSubject(initialSummary));
  const [selected, setSelected] = useState<string[]>(isPrivate ? [] : defaultSelection(messages));
  const [additional, setAdditional] = useState("");
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState<HandoffError[]>([]);
  const [created, setCreated] = useState<SupportTicket | null>(null);
  const action = useAction();

  const shared = messages.filter((m) => selected.includes(m.id));

  async function submit() {
    const res = buildHandoffPayload({
      language,
      subject,
      summary,
      conversationId: conversation?.id,
      selectedIds: selected,
      availableIds: messages.map((m) => m.id),
      additional,
      consent,
      isPrivate,
    });
    if (!res.ok) return setErrors(res.errors);
    setErrors([]);
    const ticket = await action.run(() => api.post<SupportTicket>("/api/v1/support/tickets", res.body));
    if (ticket) setCreated(ticket);
  }

  const err = (k: HandoffError) => errors.includes(k);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl" closeLabel={t("close")}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("intro")}</DialogDescription>
        </DialogHeader>

        {created ? (
          <div className="space-y-3">
            <Alert variant={created.status === "waiting" ? "warning" : "success"}>
              <CheckCircle2 className="size-4" aria-hidden />
              <AlertTitle>{t("createdTitle", { number: created.ticket_number })}</AlertTitle>
              <AlertDescription>{created.status_message}</AlertDescription>
            </Alert>
            <p className="text-sm text-muted-foreground">{t("notJoinedYet")}</p>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                {t("close")}
              </Button>
              <Button asChild>
                <Link href={`/support/requests/${created.id}`}>{t("openRequest")}</Link>
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="ho-lang">{t("language")}</Label>
                <LanguageSelect id="ho-lang" value={language} onChange={setLanguage} aria-invalid={err("language")} />
                <p className="text-xs text-muted-foreground">{t("languageHelp")}</p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ho-subject">{t("subject")}</Label>
                <Input id="ho-subject" value={subject} maxLength={SUBJECT_MAX} onChange={(e) => setSubject(e.target.value)} aria-invalid={err("subject")} />
                {err("subject") && <FieldError>{t("subjectError")}</FieldError>}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ho-summary">{t("summary")}</Label>
              <Textarea id="ho-summary" rows={3} maxLength={SUMMARY_MAX} value={summary} onChange={(e) => setSummary(e.target.value)} aria-invalid={err("summary")} />
              {err("summary") && <FieldError>{t("summaryError")}</FieldError>}
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">{t("messagesToShare")}</legend>
              {isPrivate ? (
                <Alert variant="info">
                  <Lock className="size-4" aria-hidden />
                  <AlertDescription>{t("privateConversation")}</AlertDescription>
                </Alert>
              ) : messages.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("noMessages")}</p>
              ) : (
                <ul className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-border p-2">
                  {messages.map((m) => (
                    <li key={m.id}>
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={selected.includes(m.id)}
                          onChange={(e) =>
                            setSelected((s) => (e.target.checked ? [...s, m.id] : s.filter((x) => x !== m.id)))
                          }
                        />
                        <span className="min-w-0">
                          <span className="text-xs font-semibold text-muted-foreground">
                            {m.role === "user" ? t("you") : t("assistant")}
                          </span>
                          <span className="block line-clamp-2" lang={m.language}>
                            {m.content}
                          </span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>

            <div className="space-y-1.5">
              <Label htmlFor="ho-extra">{t("additional")}</Label>
              <Textarea id="ho-extra" rows={2} maxLength={4000} value={additional} onChange={(e) => setAdditional(e.target.value)} />
            </div>

            <section aria-labelledby="ho-preview" className="rounded-md bg-muted/50 p-3 text-sm">
              <h3 id="ho-preview" className="mb-1 font-semibold">
                {t("previewTitle")}
              </h3>
              <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
                <li>
                  {t("previewTeam", { language: language ? LOCALE_LABELS[language] : "—" })}
                </li>
                <li>{t("previewSubject", { subject: subject.trim() || "—" })}</li>
                <li>{t("previewSummary")}</li>
                <li>{t("previewMessages", { count: shared.length })}</li>
                {additional.trim() && <li>{t("previewAdditional")}</li>}
              </ul>
              <p className="mt-1 text-xs text-muted-foreground">{t("previewNotShared")}</p>
            </section>

            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={consent} onChange={(e) => setConsent(e.target.checked)} aria-invalid={err("consent")} />
              <span>{t("consent", { language: language ? LOCALE_LABELS[language] : "—" })}</span>
            </label>
            {err("consent") && <FieldError>{t("consentError")}</FieldError>}
            {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                {t("cancel")}
              </Button>
              <Button onClick={submit} disabled={action.busy || !consent}>
                <Send /> {t("submit")}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
