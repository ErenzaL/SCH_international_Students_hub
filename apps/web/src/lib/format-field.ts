/** Render a structured field value ({start, end} ranges, strings, numbers) as plain text. */
export function formatFieldValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "object") {
    const v = value as { start?: string | null; end?: string | null };
    if ("start" in v || "end" in v) return `${v.start ?? "?"} ~ ${v.end ?? "?"}`;
    return JSON.stringify(value);
  }
  return String(value);
}
