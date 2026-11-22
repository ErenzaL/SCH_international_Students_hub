"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  Activity,
  ClipboardCheck,
  Database,
  FileText,
  Inbox,
  Languages,
  LayoutDashboard,
  LifeBuoy,
  Lock,
  Megaphone,
  Settings,
  Users,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { NotificationBell } from "@/features/admin/notifications/notification-bell";
import { UserNotificationBell } from "@/features/notifications/user-notifications";
import { AdminProvider, isAdminRole, navForRole } from "@/features/admin/shell/admin-context";
import { api } from "@/lib/api";
import { isSupabaseConfigured } from "@/lib/constants";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import type { Me } from "@/types/api";

const ICONS: Record<string, LucideIcon> = {
  Activity,
  LayoutDashboard,
  Database,
  FileText,
  Inbox,
  Megaphone,
  Languages,
  ClipboardCheck,
  Users,
  UsersRound,
  LifeBuoy,
  Settings,
};

function isActive(pathname: string, href: string) {
  return href === "/admin" ? pathname === "/admin" : pathname === href || pathname.startsWith(`${href}/`);
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations("admin");
  const pathname = usePathname();
  const router = useRouter();
  const me = useApi<Me>(isSupabaseConfigured ? "me" : null, () => api.get<Me>("/api/v1/me"));

  useEffect(() => {
    if (me.error?.isUnauthenticated) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [me.error, pathname, router]);

  // Supporters land on the pages they may use.
  useEffect(() => {
    if (me.data?.role === "supporter" && pathname === "/admin") router.replace("/admin/support");
  }, [me.data, pathname, router]);

  if (!isSupabaseConfigured) {
    return (
      <Container>
        <Alert variant="warning">
          <AlertTitle>{t("notConfiguredTitle")}</AlertTitle>
          <AlertDescription>
            <p>{t("notConfiguredBody")}</p>
            <ol className="mt-2 list-decimal space-y-1 pl-5">
              <li>{t("notConfiguredStep1")}</li>
              <li>
                {t("notConfiguredStep2")} <code>NEXT_PUBLIC_SUPABASE_URL</code>, <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code>,{" "}
                <code>NEXT_PUBLIC_API_URL</code>
              </li>
              <li>{t("notConfiguredStep3")}</li>
            </ol>
          </AlertDescription>
        </Alert>
      </Container>
    );
  }

  if (me.loading) {
    return (
      <Container>
        <LoadingState rows={3} />
      </Container>
    );
  }
  if (me.error && !me.error.isUnauthenticated) {
    return (
      <Container>
        <ErrorState error={me.error} onRetry={me.reload} />
      </Container>
    );
  }
  if (!me.data) {
    return (
      <Container>
        <LoadingState rows={1} />
      </Container>
    );
  }

  const user = me.data;
  if (!user.is_staff) {
    return (
      <Container>
        <Alert variant="destructive">
          <Lock className="size-4" aria-hidden />
          <AlertTitle>{t("noAccessTitle")}</AlertTitle>
          <AlertDescription>
            <p>{t("noAccessBody", { role: user.role })}</p>
            <Button asChild variant="outline" size="sm" className="mt-3">
              <Link href="/">{t("backHome")}</Link>
            </Button>
          </AlertDescription>
        </Alert>
      </Container>
    );
  }

  const items = navForRole(user.role);
  return (
    <AdminProvider value={user}>
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 lg:flex-row">
        <aside className="lg:w-56 lg:shrink-0">
          <p className="mb-2 px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("title")}
          </p>
          <nav aria-label={t("navLabel")} className="flex gap-1 overflow-x-auto lg:flex-col">
            {items.map((item) => {
              const Icon = ICONS[item.icon];
              const active = isActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active ? "bg-secondary text-secondary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <Icon className="size-4" aria-hidden /> {t(`nav.${item.key}`)}
                </Link>
              );
            })}
          </nav>
          <p className="mt-4 hidden px-3 text-xs text-muted-foreground lg:block">
            {user.display_name ?? user.email}
            <br />
            <span className="font-mono">{user.role}</span>
          </p>
        </aside>
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex items-center justify-end gap-2">
            {/* personal notifications (tickets, translation tasks) for every staff member */}
            <UserNotificationBell userId={user.id} isStaff />
            {/* system notifications (sync / indexing) for content admins */}
            {isAdminRole(user.role) && <NotificationBell />}
          </div>
          {children}
        </div>
      </div>
    </AdminProvider>
  );
}

function Container({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-3xl px-4 py-10">{children}</div>;
}
