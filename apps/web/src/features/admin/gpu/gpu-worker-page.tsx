"use client";

/**
 * Admin → GPU worker: the university GPU computer that generates translation drafts. The worker connects to the API; nothing
 * connects to it. Tokens are shown once after creation or rotation and never stored here.
 */
import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Copy, KeyRound, Pause, Play, Plus, RefreshCw, RotateCcw, ShieldOff, X } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { useMe } from "@/features/admin/shell/admin-context";
import { api } from "@/lib/api";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";

interface Worker { id: string; name: string; status: "active" | "paused" | "revoked"; expires_at: string; expired: boolean; last_seen_at: string | null }
interface Job { id: string; job_type: string; status: string; attempts: number; max_attempts: number; created_at: string; error_code: string | null; language?: string | null; cancel_requested?: boolean }
interface GpuStatus {
  available: boolean; routed_job_types: string[]; workers: Worker[]; queue: { queued: number; running: number };
  last_24h: { succeeded: number; failed: Record<string, number>; average_seconds: number | null }; jobs: Job[];
}

export function GpuWorkerPage() {
  const t = useTranslations("admin.gpu");
  const locale = useLocale();
  const me = useMe();
  const superAdmin = me.role === "super_admin";
  const { data, error, loading, reload } = useApi<GpuStatus>("gpu-status", () => api.get<GpuStatus>("/api/v1/admin/gpu/status"));
  const action = useAction();
  const [name, setName] = useState("school-gpu");
  const [token, setToken] = useState<{ name: string; token: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirm, setConfirm] = useState<string | null>(null);

  async function create() {
    const r = await action.run(() => api.post<{ name: string; token: string }>("/api/v1/admin/gpu/workers", { name: name.trim() }));
    if (r) setToken(r);
    reload();
  }
  async function rotate(w: Worker) {
    const r = await action.run(() => api.post<{ name: string; token: string }>(`/api/v1/admin/gpu/workers/${w.id}/rotate`, { grace_minutes: 10 }));
    if (r) setToken(r);
    setConfirm(null);
    reload();
  }
  async function setStatus(w: Worker, status: Worker["status"]) {
    await action.run(() => api.patch(`/api/v1/admin/gpu/workers/${w.id}`, { status }));
    setConfirm(null);
    reload();
  }
  async function cancel(id: string) {
    await action.run(() => api.post(`/api/v1/admin/gpu/jobs/${id}/cancel`));
    reload();
  }
  const jobs = data?.jobs ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("subtitle")}
        actions={<Button size="sm" variant="outline" onClick={reload}><RefreshCw className="size-4" aria-hidden /> {t("refresh")}</Button>} />
      {loading && !data && <LoadingState rows={4} />}
      {error && (error.status === 404
        ? <Alert data-testid="gpu-off"><AlertTitle>{t("offTitle")}</AlertTitle><AlertDescription>{t("off")}</AlertDescription></Alert>
        : <ErrorState error={error} onRetry={reload} />)}
      {action.error && <ErrorState error={action.error} />}
      {token && (
        <Alert variant="warning" data-testid="gpu-token">
          <AlertTitle>{t("tokenTitle", { name: token.name })}</AlertTitle>
          <AlertDescription>
            <p>{t("tokenBody")}</p>
            <code className="mt-2 block break-all rounded bg-background p-2 text-xs">{token.token}</code>
            <div className="mt-2 flex gap-2">
              <Button size="sm" variant="outline" onClick={() => void navigator.clipboard.writeText(token.token).then(() => setCopied(true))}><Copy className="size-4" aria-hidden /> {copied ? t("copied") : t("copy")}</Button>
              <Button size="sm" variant="ghost" onClick={() => { setToken(null); setCopied(false); }}>{t("hide")}</Button>
            </div>
          </AlertDescription>
        </Alert>
      )}
      {data && (
        <>
          <ul className="grid gap-3 sm:grid-cols-3">
            <li><Card><CardContent className="p-4 text-sm" data-testid="gpu-available"><p className="font-semibold">{data.available ? t("available") : t("unavailable")}</p>
              <p className="text-muted-foreground">{data.available ? t("availableHint", { types: data.routed_job_types.join(", ") }) : t("unavailableHint")}</p></CardContent></Card></li>
            <li><Card><CardContent className="p-4 text-sm"><p className="font-semibold">{t("queue")}</p><p>{t("queueLine", data.queue)}</p></CardContent></Card></li>
            <li><Card><CardContent className="p-4 text-sm"><p className="font-semibold">{t("last24h")}</p>
              <p>{t("doneLine", { ok: data.last_24h.succeeded, failed: Object.values(data.last_24h.failed).reduce((a, b) => a + b, 0) })}</p>
              {data.last_24h.average_seconds !== null && <p className="text-muted-foreground">{t("average", { seconds: data.last_24h.average_seconds })}</p>}</CardContent></Card></li>
          </ul>

          <section className="space-y-3">
            <h2 className="text-lg font-semibold">{t("workers")}</h2>
            {data.workers.length === 0 ? <EmptyState title={t("noWorkers")} /> : (
              <Table>
                <TableHeader><TableRow><TableHead>{t("name")}</TableHead><TableHead>{t("state")}</TableHead><TableHead>{t("lastSeen")}</TableHead><TableHead>{t("expires")}</TableHead><TableHead><span className="sr-only">{t("actions")}</span></TableHead></TableRow></TableHeader>
                <TableBody>
                  {data.workers.map((w) => (
                    <TableRow key={w.id} data-testid={`worker-${w.name}`}>
                      <TableCell className="font-semibold">{w.name}</TableCell>
                      <TableCell><Badge variant={w.status === "active" && !w.expired ? "success" : w.status === "revoked" || w.expired ? "danger" : "warning"}>{w.expired && w.status !== "revoked" ? t("expired") : t(`status.${w.status}`)}</Badge></TableCell>
                      <TableCell className="text-xs">{w.last_seen_at ? formatDateTime(w.last_seen_at, locale) : t("never")}</TableCell>
                      <TableCell className="text-xs">{formatDateTime(w.expires_at, locale)}</TableCell>
                      <TableCell>
                        {superAdmin && w.status !== "revoked" && (
                          <div className="flex flex-wrap justify-end gap-1">
                            <Button size="sm" variant="outline" disabled={action.busy} onClick={() => void setStatus(w, w.status === "paused" ? "active" : "paused")}>
                              {w.status === "paused" ? <Play className="size-4" aria-hidden /> : <Pause className="size-4" aria-hidden />} {w.status === "paused" ? t("resume") : t("pause")}
                            </Button>
                            <Button size="sm" variant="ghost" disabled={action.busy} onClick={() => void rotate(w)}><RotateCcw className="size-4" aria-hidden /> {t("rotate")}</Button>
                            {confirm === w.id
                              ? <Button size="sm" variant="destructive" disabled={action.busy} onClick={() => void setStatus(w, "revoked")}>{t("confirmRevoke")}</Button>
                              : <Button size="sm" variant="ghost" disabled={action.busy} onClick={() => setConfirm(w.id)}><ShieldOff className="size-4" aria-hidden /> {t("revoke")}</Button>}
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {superAdmin ? (
              <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); void create(); }}>
                <div><Label htmlFor="worker-name">{t("newName")}</Label><Input id="worker-name" value={name} onChange={(e) => setName(e.target.value)} pattern="[a-z0-9][a-z0-9\-]{1,40}" required className="w-56" /></div>
                <Button type="submit" disabled={action.busy}><Plus className="size-4" aria-hidden /> {t("create")}</Button>
              </form>
            ) : <p className="flex items-center gap-1 text-sm text-muted-foreground"><KeyRound className="size-4" aria-hidden /> {t("superOnly")}</p>}
          </section>

          <section className="space-y-3">
            <h2 className="text-lg font-semibold">{t("jobs")}</h2>
            {jobs.length === 0 ? <EmptyState title={t("noJobs")} /> : (
              <Table>
                <TableHeader><TableRow><TableHead>{t("job")}</TableHead><TableHead>{t("state")}</TableHead><TableHead>{t("created")}</TableHead><TableHead><span className="sr-only">{t("actions")}</span></TableHead></TableRow></TableHeader>
                <TableBody>
                  {jobs.map((j) => (
                    <TableRow key={j.id}>
                      <TableCell className="text-xs">{j.job_type}{j.language ? ` · ${j.language}` : ""}</TableCell>
                      <TableCell className="text-xs">{j.status} ({j.attempts}/{j.max_attempts}){j.error_code && <code className="ml-1 text-red-700">{j.error_code}</code>}</TableCell>
                      <TableCell className="text-xs">{formatDateTime(j.created_at, locale)}</TableCell>
                      <TableCell><div className="flex justify-end"><Button size="sm" variant="ghost" disabled={action.busy} onClick={() => void cancel(j.id)}><X className="size-4" aria-hidden /> {t("cancel")}</Button></div></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </section>
        </>
      )}
    </div>
  );
}
