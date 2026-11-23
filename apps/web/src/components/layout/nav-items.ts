export const NAV_ITEMS = [
  { href: "/", key: "home" },
  { href: "/announcements", key: "announcements" },
  { href: "/knowledge", key: "knowledge" },
  { href: "/support", key: "support" },
  { href: "/ai-office", key: "aiOffice" },
] as const;

export function isActivePath(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
