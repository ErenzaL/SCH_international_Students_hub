"use client";

import { createContext, useContext } from "react";
import type { Me, Role } from "@/types/api";

const AdminContext = createContext<Me | null>(null);

export const AdminProvider = AdminContext.Provider;

export function useMe(): Me {
  const me = useContext(AdminContext);
  if (!me) throw new Error("useMe must be used inside <AdminShell>");
  return me;
}

export function isAdminRole(role: Role) {
  return role === "admin" || role === "super_admin";
}

export const ADMIN_NAV = [
  { href: "/admin", key: "overview", icon: "LayoutDashboard", roles: ["admin", "super_admin"] },
  { href: "/admin/knowledge-sources", key: "sources", icon: "Database", roles: ["admin", "super_admin"] },
  { href: "/admin/support", key: "support", icon: "LifeBuoy", roles: ["admin", "super_admin", "supporter"] },
  { href: "/admin/submissions", key: "submissions", icon: "Inbox", roles: ["admin", "super_admin", "supporter"] },
  { href: "/admin/documents", key: "documents", icon: "FileText", roles: ["admin", "super_admin"] },
  { href: "/admin/announcements", key: "announcements", icon: "Megaphone", roles: ["admin", "super_admin", "supporter"] },
  { href: "/admin/translations", key: "translations", icon: "Languages", roles: ["admin", "super_admin", "supporter"] },
  { href: "/admin/review", key: "review", icon: "ClipboardCheck", roles: ["admin", "super_admin"] },
  { href: "/admin/rag-sync", key: "ragSync", icon: "Activity", roles: ["admin", "super_admin"] },
  { href: "/admin/agents", key: "agents", icon: "Bot", roles: ["admin", "super_admin"] },
  { href: "/admin/gpu-worker", key: "gpuWorker", icon: "Cpu", roles: ["admin", "super_admin"] },
  { href: "/admin/users", key: "users", icon: "Users", roles: ["admin", "super_admin"] },
  { href: "/admin/language-teams", key: "languageTeams", icon: "UsersRound", roles: ["admin", "super_admin", "supporter"] },
  { href: "/admin/settings", key: "settings", icon: "Settings", roles: ["admin", "super_admin"] },
] as const;

export function navForRole(role: Role) {
  return ADMIN_NAV.filter((n) => (n.roles as readonly string[]).includes(role));
}
