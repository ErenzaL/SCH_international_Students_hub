"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowLeft, Loader2, Send } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { api, errorMessage } from "@/lib/api";
import { LOCALE_LABELS } from "@/lib/constants";
import type { HandoffDraft, SupportTicket } from "@/types/api";

/**
 * Review step before anything reaches a Global Supporter: the student sees exactly what will be shared, can edit the
 * subject and summary, deselect messages, and must give explicit consent. Only then is the request created.
 */
export function HandoffReview({ conversationId, onCancel, onSent }: {
  conversationId: string;
  onCancel: () => void;
  onSent: (ticket: SupportTicket) => void;
}) {
  const t = useTranslations("chatbot.handoff");
  const [draft, setDraft] = useState<HandoffDraft | null>(null);
  const [subject, setSubject] = useState("");
  const [summary, setSummary] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.post<HandoffDraft>(`/api/v1/conversations/${encodeURIComponent(conversationId)}/handoff-draft`)
      .then((d) => {
        if (!alive) return;
        setDraft(d);
        setSubject(d.subject);
        setSummary(d.summary);
        setSelected(d.message_ids);
      })
      .catch((err) => alive && setError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, [conversationId]);

  async function send() {
    if (!draft || !consent) return;
    setBusy(true);
    setError(null);
    try {
      const ticket = await api.post<SupportTicket>("/api/v1/support/tickets", {
        subject: subject.trim(), summary: summary.trim(), conversation_id: conversationId, message_ids: selected,
        consent: true,
      });
      onSent(ticket);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="handoff-review">
      <div className="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}><ArrowLeft /> {t("back")}</Button>
        <div>
          <p className="font-semibold">{t("title")}</p>
          <p className="text-muted-foreground">{t("intro")}</p>
        </div>
        {!draft && !error && <Loader2 className="size-4 animate-spin" aria-label={t("preparing")} />}
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
        {draft && (
          <>
            <p className="text-xs text-muted-foreground">{t("team", { language: LOCALE_LABELS[draft.language] ?? draft.language })}</p>
            <div className="space-y-1">
              <Label htmlFor="ho-subject">{t("subject")}</Label>
              <Input id="ho-subject" value={subject} maxLength={200} onChange={(e) => setSubject(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ho-summary">{t("summary")}</Label>
              <Textarea id="ho-summary" rows={5} value={summary} maxLength={4000} onChange={(e) => setSummary(e.target.value)} />
            </div>
            {draft.messages.length > 0 && (
              <fieldset className="space-y-1">
                <legend className="text-xs font-medium">{t("share")}</legend>
                {draft.messages.map((m) => (
                  <label key={m.id} className="flex items-start gap-2 rounded-md border border-border p-2 text-xs">
                    <input type="checkbox" className="mt-0.5" checked={selected.includes(m.id)}
                      onChange={(e) => setSelected((s) => (e.target.checked ? [...s, m.id] : s.filter((x) => x !== m.id)))} />
                    <span><span className="font-semibold">{m.role === "user" ? t("you") : t("assistant")}:</span> {m.content}</span>
                  </label>
                ))}
              </fieldset>
            )}
            {draft.references.length > 0 && (
              <p className="text-xs text-muted-foreground">{t("references", { list: draft.references.map((r) => r.title).join("; ") })}</p>
            )}
            <label className="flex items-start gap-2 rounded-md bg-muted p-2 text-xs">
              <input type="checkbox" className="mt-0.5" checked={consent} onChange={(e) => setConsent(e.target.checked)}
                data-testid="handoff-consent" />
              <span>{t("consent")}</span>
            </label>
          </>
        )}
      </div>
      <div className="border-t border-border p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        <Button className="w-full" disabled={!draft || !consent || busy || subject.trim().length < 3 || !summary.trim()} onClick={send}>
          {busy ? <Loader2 className="animate-spin" /> : <Send />} {t("send")}
        </Button>
      </div>
    </div>
  );
}
