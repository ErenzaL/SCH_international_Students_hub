"use client";

import { usePathname } from "next/navigation";

/** Pages that are full-screen experiences with their own navigation (the AI Office): no site header / footer, so
 * keyboard focus cannot land in hidden chrome behind them. */
export const FULLSCREEN_ROUTES = ["/ai-office"];

export function isFullscreenRoute(pathname: string | null): boolean {
  return FULLSCREEN_ROUTES.some((p) => pathname === p || pathname?.startsWith(`${p}/`));
}

export function HideOnFullscreen({ children }: { children: React.ReactNode }) {
  return isFullscreenRoute(usePathname()) ? null : <>{children}</>;
}
