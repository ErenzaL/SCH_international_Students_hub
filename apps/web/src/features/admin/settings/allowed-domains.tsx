"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Plus, Trash2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { useMe } from "@/features/admin/shell/admin-context";
import { api, errorMessage } from "@/lib/api";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/utils";
import type { AllowedDomain } from "@/types/api";

/** Trusted-domain allowlist for outbound fetching: environment defaults + admin entries (super_admin edits). */
export function AllowedDomainsCard() {
  const t = useTranslations("admin.settings");
  const locale = useLocale();
  const me = useMe();
  const canEdit = me.role === "super_admin";
  const { data, error, loading, reload } = useApi<{ items: AllowedDomain[] }>("allowed-domains", () =>
    api.get<{ items: AllowedDomain[] }>("/api/v1/admin/allowed-domains"),
  );
  const [domain, setDomain] = useState("");
  const [note, setNote] = useState("");
  const action = useAction();

  async function add(ev: React.FormEvent) {
    ev.preventDefault();
    const r = await action.run(() => api.post<AllowedDomain>("/api/v1/admin/allowed-domains", { domain: domain.trim(), note: note.trim() || undefined }));
    if (r) {
      setDomain("");
      setNote("");
      reload();
    }
  }
  async function remove(d: string) {
    const r = await action.run(() => api.delete<null>(`/api/v1/admin/allowed-domains/${encodeURIComponent(d)}`));
    if (r !== undefined) reload();
  }

  return (
    <Card className="mt-6">
      <CardHeader><CardTitle>{t("domainsTitle")}</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{t("domainsHint")}</p>
        {loading && !data && <LoadingState rows={2} />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {data && (
          <ul className="divide-y divide-border rounded-md border border-border text-sm">
            {data.items.map((d) => (
              <li key={d.domain} className="flex flex-wrap items-center gap-2 px-3 py-2">
                <span className="font-mono">{d.domain}</span>
                <Badge variant={d.origin === "environment" ? "outline" : "secondary"}>{d.origin === "environment" ? t("originEnv") : t("originAdmin")}</Badge>
                {d.note && <span className="text-xs text-muted-foreground">{d.note}</span>}
                {d.created_at && <span className="text-xs text-muted-foreground">{formatDate(d.created_at, locale)}</span>}
                {canEdit && d.removable && (
                  <Button size="sm" variant="ghost" className="ml-auto" disabled={action.busy} onClick={() => remove(d.domain)}>
                    <Trash2 /> {t("remove")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {canEdit ? (
          <form onSubmit={add} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <div><Label htmlFor="ad-domain">{t("domain")}</Label><Input id="ad-domain" value={domain} placeholder="example.go.kr" onChange={(e) => setDomain(e.target.value)} /></div>
            <div><Label htmlFor="ad-note">{t("note")}</Label><Input id="ad-note" value={note} onChange={(e) => setNote(e.target.value)} /></div>
            <Button type="submit" disabled={action.busy || domain.trim().length < 3}><Plus /> {t("addDomain")}</Button>
          </form>
        ) : <p className="text-xs text-muted-foreground">{t("superAdminOnly")}</p>}
        {action.error && <Alert variant="destructive"><AlertDescription>{errorMessage(action.error)}</AlertDescription></Alert>}
      </CardContent>
    </Card>
  );
}
