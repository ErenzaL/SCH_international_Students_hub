"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface TabItem {
  id: string;
  label: React.ReactNode;
}

/** Small accessible tab list (WAI-ARIA tabs pattern, controlled). */
export function Tabs({
  items,
  value,
  onChange,
  className,
  label,
}: {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
  label: string;
}) {
  const onKey = (e: React.KeyboardEvent, idx: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const next = (idx + (e.key === "ArrowRight" ? 1 : items.length - 1)) % items.length;
    onChange(items[next].id);
    const el = document.getElementById(`tab-${items[next].id}`);
    el?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className={cn("flex flex-wrap gap-1 border-b border-border", className)}>
      {items.map((t, i) => {
        const selected = t.id === value;
        return (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => onKey(e, i)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              selected
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
