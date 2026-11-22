"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import {
  EMPTY_SOURCE_FORM,
  toSourceCreate,
  validateSourceForm,
  type SourceFormErrors,
  type SourceFormValues,
} from "@/features/admin/sources/source-validation";
import { api, errorMessage } from "@/lib/api";
import {
  AUTHORITY_TYPES,
  CATEGORY_SLUGS,
  LOCALES,
  LOCALE_LABELS,
  SCOPES,
  SOURCE_TYPES,
  SYNC_FREQUENCIES,
} from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import { useCategoryName } from "@/lib/use-category-name";
import type { Source } from "@/types/api";

export function AddSourceDialog({ onCreated }: { onCreated: (s: Source) => void }) {
  const t = useTranslations("admin.sources");
  const c = useTranslations("common");
  const e = useTranslations("enums");
  const v = useTranslations("admin.sources.validation");
  const categoryName = useCategoryName();
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<SourceFormValues>(EMPTY_SOURCE_FORM);
  const [errors, setErrors] = useState<SourceFormErrors>({});
  const action = useAction();

  const set = <K extends keyof SourceFormValues>(k: K, val: SourceFormValues[K]) =>
    setValues((s) => {
      const next = { ...s, [k]: val };
      if (k === "source_type") {
        if (val !== "website") next.sync_frequency = "manual";
        if (val === "kakao_message") next.authority_type = "supporter_submitted";
      }
      return next;
    });

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    const errs = validateSourceForm(values);
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;
    const created = await action.run(() => api.post<Source>("/api/v1/admin/sources", toSourceCreate(values)));
    if (created) {
      setOpen(false);
      setValues(EMPTY_SOURCE_FORM);
      onCreated(created);
    }
  }

  const err = (k: keyof SourceFormValues) => (errors[k] ? v(errors[k]!) : undefined);

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) {
          setErrors({});
          action.clear();
        }
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <Plus /> {t("add")}
        </Button>
      </DialogTrigger>
      <DialogContent closeLabel={c("close")}>
        <DialogHeader>
          <DialogTitle>{t("addTitle")}</DialogTitle>
          <DialogDescription>{t("addDescription")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} noValidate className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Label htmlFor="src-title">{t("fields.title")}</Label>
            <Input id="src-title" value={values.title} aria-invalid={!!errors.title} aria-describedby="src-title-err" onChange={(ev) => set("title", ev.target.value)} />
            <FieldError id="src-title-err">{err("title")}</FieldError>
          </div>
          <div>
            <Label htmlFor="src-type">{t("fields.sourceType")}</Label>
            <Select id="src-type" value={values.source_type} onChange={(ev) => set("source_type", ev.target.value as SourceFormValues["source_type"])}>
              {SOURCE_TYPES.map((s) => (
                <option key={s} value={s}>
                  {e(`sourceType.${s}`)}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="src-org">{t("fields.organization")}</Label>
            <Input id="src-org" value={values.organization} aria-invalid={!!errors.organization} aria-describedby="src-org-err" onChange={(ev) => set("organization", ev.target.value)} />
            <FieldError id="src-org-err">{err("organization")}</FieldError>
          </div>
          <div className="sm:col-span-2">
            <Label htmlFor="src-url">
              {t("fields.url")} {values.source_type !== "website" && <span className="text-muted-foreground">({c("optional")})</span>}
            </Label>
            <Input id="src-url" type="url" inputMode="url" placeholder="https://…" value={values.original_url} aria-invalid={!!errors.original_url} aria-describedby="src-url-err" onChange={(ev) => set("original_url", ev.target.value)} />
            <FieldError id="src-url-err">{err("original_url")}</FieldError>
            {values.source_type === "website" && <p className="mt-1 text-xs text-muted-foreground">{t("urlHint")}</p>}
          </div>
          <div>
            <Label htmlFor="src-auth">{t("fields.authority")}</Label>
            <Select id="src-auth" value={values.authority_type} aria-invalid={!!errors.authority_type} onChange={(ev) => set("authority_type", ev.target.value as SourceFormValues["authority_type"])}>
              {AUTHORITY_TYPES.map((s) => (
                <option key={s} value={s}>
                  {e(`authority.${s}`)}
                </option>
              ))}
            </Select>
            <FieldError>{err("authority_type")}</FieldError>
          </div>
          <div>
            <Label htmlFor="src-scope">{t("fields.scope")}</Label>
            <Select id="src-scope" value={values.scope} onChange={(ev) => set("scope", ev.target.value as SourceFormValues["scope"])}>
              {SCOPES.map((s) => (
                <option key={s} value={s}>
                  {e(`scope.${s}`)}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="src-cat">{t("fields.category")}</Label>
            <Select id="src-cat" value={values.category} onChange={(ev) => set("category", ev.target.value)}>
              {CATEGORY_SLUGS.map((s) => (
                <option key={s} value={s}>
                  {categoryName(s)}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="src-lang">{t("fields.language")}</Label>
            <Select id="src-lang" value={values.language} onChange={(ev) => set("language", ev.target.value as SourceFormValues["language"])}>
              {LOCALES.map((l) => (
                <option key={l} value={l}>
                  {LOCALE_LABELS[l]}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="src-sync">{t("fields.sync")}</Label>
            <Select id="src-sync" value={values.sync_frequency} aria-invalid={!!errors.sync_frequency} disabled={values.source_type !== "website"} onChange={(ev) => set("sync_frequency", ev.target.value as SourceFormValues["sync_frequency"])}>
              {SYNC_FREQUENCIES.map((s) => (
                <option key={s} value={s}>
                  {e(`sync.${s}`)}
                </option>
              ))}
            </Select>
            <FieldError>{err("sync_frequency")}</FieldError>
          </div>
          {action.error && (
            <Alert variant="destructive" className="sm:col-span-2">
              {errorMessage(action.error)}
            </Alert>
          )}
          <DialogFooter className="sm:col-span-2">
            <Button type="submit" disabled={action.busy}>
              {action.busy ? c("saving") : t("add")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
