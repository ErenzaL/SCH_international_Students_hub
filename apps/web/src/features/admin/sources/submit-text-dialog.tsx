"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FieldError, Input, Label, Textarea } from "@/components/ui/input";
import { api, errorMessage } from "@/lib/api";
import { useAction } from "@/lib/use-action";
import type { Job, Source } from "@/types/api";

export function SubmitTextDialog({
  source,
  onClose,
  onDone,
}: {
  source: Source | null;
  onClose: () => void;
  onDone: (job: Job) => void;
}) {
  const t = useTranslations("admin.sources.submitText");
  const c = useTranslations("common");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [published, setPublished] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const action = useAction();
  const isKakao = source?.source_type === "kakao_message";

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    if (!source) return;
    const errs: Record<string, string> = {};
    if (!title.trim()) errs.title = t("errTitle");
    if (text.trim().length < 10) errs.text = t("errText");
    if (isKakao && !authorized) errs.authorized = t("errAuthorized");
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const job = await action.run(() =>
      api.post<Job>(`/api/v1/admin/sources/${source.id}/submit-text`, {
        title: title.trim(),
        text,
        source_published_at: published || undefined,
        authorized_by_supporter: isKakao ? authorized : undefined,
      }),
    );
    if (job) {
      setTitle("");
      setText("");
      setPublished("");
      setAuthorized(false);
      onDone(job);
    }
  }

  return (
    <Dialog open={!!source} onOpenChange={(o) => !o && onClose()}>
      <DialogContent closeLabel={c("close")} className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{source?.title}</DialogDescription>
        </DialogHeader>
        {isKakao && (
          <Alert variant="warning">
            <AlertTitle>{t("kakaoTitle")}</AlertTitle>
            <AlertDescription>{t("kakaoBody")}</AlertDescription>
          </Alert>
        )}
        <form onSubmit={submit} noValidate className="space-y-4">
          <div>
            <Label htmlFor="st-title">{t("docTitle")}</Label>
            <Input id="st-title" value={title} onChange={(e) => setTitle(e.target.value)} aria-invalid={!!errors.title} />
            <FieldError>{errors.title}</FieldError>
          </div>
          <div>
            <Label htmlFor="st-text">{t("text")}</Label>
            <Textarea id="st-text" rows={10} value={text} onChange={(e) => setText(e.target.value)} aria-invalid={!!errors.text} />
            <FieldError>{errors.text}</FieldError>
          </div>
          <div>
            <Label htmlFor="st-pub">{t("publishedAt")}</Label>
            <Input id="st-pub" type="date" value={published} onChange={(e) => setPublished(e.target.value)} />
          </div>
          {isKakao && (
            <div>
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={authorized} onChange={(e) => setAuthorized(e.target.checked)} />
                <span>{t("authorized")}</span>
              </label>
              <FieldError>{errors.authorized}</FieldError>
            </div>
          )}
          {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
          <DialogFooter>
            <Button type="submit" disabled={action.busy}>
              {action.busy ? c("saving") : t("submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
