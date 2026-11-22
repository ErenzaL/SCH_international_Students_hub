"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/shared/states";
import { useMe } from "@/features/admin/shell/admin-context";
import { api, errorMessage } from "@/lib/api";
import { LOCALES, LOCALE_LABELS, ROLES } from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/utils";
import type { AdminUser, LanguageCode, Page, Role } from "@/types/api";

export function UsersPage() {
  const t = useTranslations("admin.users");
  const me = useMe();
  const locale = useLocale();
  const [page, setPage] = useState(1);
  const [notice, setNotice] = useState<string | null>(null);
  const { data, error, loading, reload } = useApi<Page<AdminUser>>(`admin-users:${page}`, () =>
    api.get<Page<AdminUser>>("/api/v1/admin/users", { page, page_size: 25 }),
  );
  const action = useAction();
  const isSuper = me.role === "super_admin";

  async function changeRole(u: AdminUser, role: Role) {
    const res = await action.run(() => api.patch<AdminUser>(`/api/v1/admin/users/${u.id}/role`, { role }));
    if (res) {
      setNotice(t("roleUpdated", { name: u.display_name ?? u.email ?? u.id, role }));
      reload();
    }
  }
  async function toggleLanguage(u: AdminUser, lang: LanguageCode) {
    const languages = u.languages.includes(lang) ? u.languages.filter((l) => l !== lang) : [...u.languages, lang];
    const res = await action.run(() => api.put<AdminUser>(`/api/v1/admin/users/${u.id}/languages`, { languages }));
    if (res) {
      setNotice(t("languagesUpdated"));
      reload();
    }
  }

  return (
    <div>
      <PageHeader title={t("title")} description={t("subtitle")} />
      <Alert variant="info" className="mb-4">
        <AlertDescription>{isSuper ? t("superNote") : t("readOnlyNote")}</AlertDescription>
      </Alert>
      {notice && (
        <Alert variant="success" className="mb-4">
          {notice}
        </Alert>
      )}
      {action.error && (
        <Alert variant="destructive" className="mb-4">
          {errorMessage(action.error)}
        </Alert>
      )}
      {loading && <LoadingState />}
      {!loading && error && <ErrorState error={error} onRetry={reload} />}
      {data && data.items.length === 0 && <EmptyState title={t("empty")} />}
      {data && data.items.length > 0 && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("user")}</TableHead>
                <TableHead>{t("role")}</TableHead>
                <TableHead>{t("supporterLanguages")}</TableHead>
                <TableHead>{t("joined")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((u) => (
                <TableRow key={u.id}>
                  <TableCell>
                    <div className="font-medium">{u.display_name ?? "—"}</div>
                    <div className="text-xs text-muted-foreground">{u.email}</div>
                  </TableCell>
                  <TableCell>
                    {isSuper ? (
                      <Select
                        aria-label={t("role")}
                        className="w-40"
                        value={u.role}
                        disabled={action.busy || u.id === me.id}
                        onChange={(e) => changeRole(u, e.target.value as Role)}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <code className="text-xs">{u.role}</code>
                    )}
                  </TableCell>
                  <TableCell>
                    {u.role === "supporter" && !isSuper ? (
                      <span className="text-xs">
                        {u.languages.length ? u.languages.map((l) => LOCALE_LABELS[l]).join(", ") : "—"}
                      </span>
                    ) : u.role === "supporter" ? (
                      <div className="flex flex-wrap gap-1">
                        {LOCALES.map((l) => {
                          const on = u.languages.includes(l);
                          return (
                            <Button
                              key={l}
                              size="sm"
                              variant={on ? "secondary" : "outline"}
                              aria-pressed={on}
                              disabled={action.busy}
                              onClick={() => toggleLanguage(u, l)}
                            >
                              {LOCALE_LABELS[l]}
                            </Button>
                          );
                        })}
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">{formatDate(u.created_at, locale)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
    </div>
  );
}
