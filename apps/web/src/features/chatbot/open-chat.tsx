"use client";

/** Open the floating SCH Assistant from anywhere (optionally with a prefilled question). */
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

export const OPEN_CHAT_EVENT = "sch-chat:open";

export interface OpenChatDetail {
  /** Prefilled into the input (not sent automatically, so the student can complete or edit it). */
  question?: string;
}

export function openChat(question?: string): void {
  window.dispatchEvent(new CustomEvent<OpenChatDetail>(OPEN_CHAT_EVENT, { detail: { question } }));
}

/** A button for server components / pages that opens the floating assistant. */
export function OpenChatButton({ question, children, variant, size, className }: {
  question?: string;
  children: ReactNode;
  variant?: "default" | "outline" | "secondary" | "ghost";
  size?: "default" | "sm" | "lg";
  className?: string;
}) {
  return (
    <Button type="button" variant={variant} size={size} className={className} onClick={() => openChat(question)}>
      {children}
    </Button>
  );
}
