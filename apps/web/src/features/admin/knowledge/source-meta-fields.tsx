"use client";

import { useTranslations } from "next-intl";
import { Input, Label, Select } from "@/components/ui/input";
import { useMe, isAdminRole } from "@/features/admin/shell/admin-context";
import { AUTHORITY_TYPES, CATEGORY_SLUGS, LOCALES, LOCALE_LABELS, SCOPES } from "@/lib/constants";
import { useCategoryName } from "@/lib/use-category-name";
import type { AuthorityType, SourceMeta } from "@/types/api";

export const EMPTY_META: SourceMeta = {
  title: "",
  organization: "",
  category: "university-announcements",
  scope: "university",
  authority_type: "official_university",
  language: "ko",
  original_url: "",
};

export function metaErrors(m: SourceMeta): Partial<Record<keyof SourceMeta, string>> {
  const out: Partial<Record<keyof SourceMeta, string>> = {};
  if (!m.title.trim()) out.title = "required";
  if (!m.organization.trim()) out.organization = "required";
  const url = (m.original_url ?? "").trim();
  if (url && !/^https?:\/\//i.test(url)) out.original_url = "invalidUrl";
  return out;
}

export function metaPayload(m: SourceMeta): SourceMeta {
  const url = (m.original_url ?? "").trim();
  return { ...m, title: m.title.trim(), organization: m.organization.trim(), original_url: url || undefined };
}

/** Metadata for a new source created via an intake form (file, screenshot, paste). */
export function SourceMetaFields({
  value,
  onChange,
  idPrefix,
  authorities,
  errors = {},
}: {
  value: SourceMeta;
  onChange: (m: SourceMeta) => void;
  idPrefix: string;
  authorities?: AuthorityType[];
  errors?: Partial<Record<keyof SourceMeta, string>>;
}) {
  const t = useTranslations("admin.ks");
  const e = useTranslations("enums");
  const v = useTranslations("admin.sources.validation");
  const me = useMe();
  const categoryName = useCategoryName();
  const set = <K extends keyof SourceMeta>(k: K, val: SourceMeta[K]) => onChange({ ...value, [k]: val });
  // Supporters relay information; an admin decides whether something is official during review.
  const allowed = (authorities ?? AUTHORITY_TYPES).filter(
    (a) => isAdminRole(me.role) || (a !== "official_government" && a !== "official_university"),
  );
  const id = (k: string) => `${idPrefix}-${k}`;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <Label htmlFor={id("title")}>{t("meta.title")}</Label>
        <Input id={id("title")} value={value.title} aria-invalid={!!errors.title} onChange={(ev) => set("title", ev.target.value)} />
        {errors.title && <p className="mt-1 text-xs text-red-700">{v(errors.title as "required")}</p>}
      </div>
      <div>
        <Label htmlFor={id("org")}>{t("meta.organization")}</Label>
        <Input id={id("org")} value={value.organization} aria-invalid={!!errors.organization} onChange={(ev) => set("organization", ev.target.value)} placeholder={t("meta.organizationHint")} />
        {errors.organization && <p className="mt-1 text-xs text-red-700">{v(errors.organization as "required")}</p>}
      </div>
      <div>
        <Label htmlFor={id("cat")}>{t("meta.category")}</Label>
        <Select id={id("cat")} value={value.category} onChange={(ev) => set("category", ev.target.value)}>
          {CATEGORY_SLUGS.map((c) => <option key={c} value={c}>{categoryName(c)}</option>)}
        </Select>
      </div>
      <div>
        <Label htmlFor={id("scope")}>{t("meta.scope")}</Label>
        <Select id={id("scope")} value={value.scope} onChange={(ev) => set("scope", ev.target.value as SourceMeta["scope"])}>
          {SCOPES.map((s) => <option key={s} value={s}>{e(`scope.${s}`)}</option>)}
        </Select>
      </div>
      <div>
        <Label htmlFor={id("auth")}>{t("meta.authority")}</Label>
        <Select id={id("auth")} value={allowed.includes(value.authority_type) ? value.authority_type : allowed[0]} onChange={(ev) => set("authority_type", ev.target.value as AuthorityType)}>
          {allowed.map((a) => <option key={a} value={a}>{e(`authority.${a}`)}</option>)}
        </Select>
      </div>
      <div>
        <Label htmlFor={id("lang")}>{t("meta.language")}</Label>
        <Select id={id("lang")} value={value.language} onChange={(ev) => set("language", ev.target.value as SourceMeta["language"])}>
          {LOCALES.map((l) => <option key={l} value={l}>{LOCALE_LABELS[l]}</option>)}
        </Select>
      </div>
      <div>
        <Label htmlFor={id("url")}>{t("meta.referenceUrl")}</Label>
        <Input id={id("url")} value={value.original_url ?? ""} aria-invalid={!!errors.original_url} onChange={(ev) => set("original_url", ev.target.value)} placeholder="https://" />
        {errors.original_url && <p className="mt-1 text-xs text-red-700">{v("invalidUrl")}</p>}
      </div>
    </div>
  );
}
