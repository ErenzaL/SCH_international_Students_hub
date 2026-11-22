"use client";

import { useTranslations } from "next-intl";
import { Input, Label } from "@/components/ui/input";
import type { KeyField } from "@/lib/constants";

export const EDITABLE_FIELDS: KeyField[] = [
  "deadline", "event_date", "time", "location", "fee", "contact", "eligibility", "required_documents", "application_method",
];

/** Editable key facts. Values are what a human confirms; detections are only suggestions. */
export function KeyFieldsEditor({
  values,
  onChange,
  idPrefix,
  fields = EDITABLE_FIELDS,
  detected = {},
}: {
  values: Partial<Record<string, string>>;
  onChange: (v: Partial<Record<string, string>>) => void;
  idPrefix: string;
  fields?: KeyField[];
  detected?: Partial<Record<string, string>>;
}) {
  const t = useTranslations("admin.ks.fields");
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {fields.map((f) => (
        <div key={f}>
          <Label htmlFor={`${idPrefix}-${f}`}>{t(f)}</Label>
          <Input
            id={`${idPrefix}-${f}`}
            value={values[f] ?? ""}
            onChange={(ev) => onChange({ ...values, [f]: ev.target.value })}
            placeholder={detected[f] ? t("detected", { value: detected[f] }) : undefined}
          />
        </div>
      ))}
    </div>
  );
}
