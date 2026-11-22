"use client";

import { Select } from "@/components/ui/input";
import { LOCALE_LABELS } from "@/lib/constants";
import { SUPPORT_LANGUAGES } from "@/lib/support";
import type { LanguageCode } from "@/types/api";

/** Language picker with native names (never translated, so everyone can find their own language). */
export function LanguageSelect({
  id,
  value,
  onChange,
  placeholder,
  disabled,
  required,
  ...rest
}: {
  id: string;
  value: LanguageCode | "";
  onChange: (v: LanguageCode | "") => void;
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}) {
  return (
    <Select
      id={id}
      value={value}
      disabled={disabled}
      required={required}
      onChange={(e) => onChange(e.target.value as LanguageCode | "")}
      {...rest}
    >
      {placeholder !== undefined && (
        <option value="" disabled>
          {placeholder}
        </option>
      )}
      {SUPPORT_LANGUAGES.map((l) => (
        <option key={l} value={l} lang={l}>
          {LOCALE_LABELS[l]}
        </option>
      ))}
    </Select>
  );
}
