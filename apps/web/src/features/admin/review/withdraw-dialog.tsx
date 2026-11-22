"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Ban } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Label, Textarea } from "@/components/ui/input";
import { api, errorMessage } from "@/lib/api";

/** Withdraw published content (POST /admin/documents/{id}/cancel): removed from search immediately, versions kept. */
export function WithdrawButton({
  documentId,
  title,
  onDone,
  size = "default",
  label = "long",
}: {
  documentId: string;
  title: string;
  onDone?: (message: string) => void;
  size?: "default" | "sm";
  label?: "long" | "short";
}) {
  const t = useTranslations("admin.withdraw");
  const c = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    if (reason.trim().length < 3) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/admin/documents/${encodeURIComponent(documentId)}/cancel`, { reason: reason.trim() });
      setOpen(false);
      setReason("");
      onDone?.(t("done"));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="destructive" size={size} onClick={() => setOpen(true)} title={t("button")}>
        <Ban /> {label === "long" ? t("button") : t("short")}
      </Button>
      <Dialog open={open} onOpenChange={(o) => !busy && setOpen(o)}>
        <DialogContent closeLabel={c("close")}>
          <DialogHeader>
            <DialogTitle>{t("title")}</DialogTitle>
            <DialogDescription>{t("description", { title })}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor={`wd-${documentId}`}>{t("reason")}</Label>
            <Textarea
              id={`wd-${documentId}`}
              rows={3}
              value={reason}
              placeholder={t("reasonPlaceholder")}
              aria-invalid={invalid}
              onChange={(e) => setReason(e.target.value)}
            />
            <FieldError>{invalid ? t("reasonRequired") : undefined}</FieldError>
            {error && <Alert variant="destructive">{error}</Alert>}
          </div>
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button variant="destructive" disabled={busy} onClick={confirm}>
              <Ban /> {t("confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
