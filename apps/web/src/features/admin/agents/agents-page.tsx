"use client";

/**
 * Admin → Agents: what the 14 desks actually did, what waits, what failed; pause, re-run, cancel; schedules; storage.
 * A student's parameters and results are never part of these responses (the API leaves them out).
 */
import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Pause, Play, RefreshCw, RotateCcw, X } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/shared/states";
import { SourcesTab } from "@/features/admin/agents/sources-tab";
import { CHARACTERS } from "@/features/ai-office/characters";
import { api } from "@/lib/api";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";
import type { Page } from "@/types/api";

type Status = "queued" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled";
interface Schedule { id: string; task_type: string; enabled: boolean; interval_minutes: number; last_run_at: string | null; last_success_at: string | null; last_error: string | null; agent_id?: string; agent_name?: string }
interface Desk {
  id: string; name: string; title: string; paused: boolean; tasks_7d: Record<Status, number>; last_success_at: string | null;
  last_failure_at: string | null; last_error: string | null; tools_available: number; tools_unavailable: string[]; monitors: boolean;
  sources: number; sources_enabled: number; sources_failing: number; schedules: Schedule[];
}
interface Queue { queued: number; running: number | null; failed_7d: number | null; oldest_queued_minutes: number | null; stuck: boolean }
interface Health { schedules_enabled_on_server: boolean; tasks_enabled: boolean; queues: Record<string, Queue | null>; agents: Desk[] }
interface AdminTask {
  id: string; agent_id: string; agent_name: string; task_type: string; status: Status; attempts: number; max_attempts: number; error_code: string | null;
  created_at: string; completed_at: string | null; requested: "schedule" | "administrator" | "student"; can_rerun: boolean; can_cancel: boolean;
  result_count?: number; new_count?: number; updated_count?: number; error_message?: string | null;
}
interface Storage {
  available: boolean; reason?: string; limit_bytes: number; database_bytes?: number; share?: number; level?: "ok" | "warning" | "critical";
  tables?: { table_name: string; total_bytes: number; index_bytes: number | null; row_estimate: number }[]; rows_added_30d?: Record<string, number | null>;
}

const TABS = ["desks", "tasks", "sources", "schedules", "storage"] as const;
type Tab = (typeof TABS)[number];
const STATUSES: Status[] = ["queued", "running", "awaiting_approval", "completed", "failed", "cancelled"];
const statusVariant = (s: Status) => (s === "failed" ? "danger" : s === "completed" ? "success" : "secondary") as "danger" | "success" | "secondary";
const mb = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MB`;

export function AgentsPage() {
  const t = useTranslations("admin.agents");
  const [tab, setTab] = useState<Tab>("desks");
  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("subtitle")} />
      <Tabs label={t("title")} value={tab} onChange={(id) => setTab(id as Tab)} items={TABS.map((id) => ({ id, label: t(`tabs.${id}`) }))} />
      {tab === "desks" && <Desks />}
      {tab === "tasks" && <Tasks />}
      {tab === "sources" && <SourcesTab />}
      {tab === "schedules" && <Schedules />}
      {tab === "storage" && <StorageView />}
    </div>
  );
}

function Desks() {
  const t = useTranslations("admin.agents");
  const locale = useLocale();
  const { data, error, loading, reload } = useApi<Health>("agent-operations", () => api.get<Health>("/api/v1/admin/agent-operations"));
  const action = useAction();
  async function setPaused(d: Desk, paused: boolean) {
    await action.run(() => api.put(`/api/v1/admin/agent-operations/agents/${d.id}`, { paused }));
    reload();
  }
  if (loading && !data) return <LoadingState rows={5} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  return (
    <div className="space-y-4">
      {!data.schedules_enabled_on_server && <Alert><AlertTitle>{t("schedulesOffTitle")}</AlertTitle><AlertDescription>{t("schedulesOff")}</AlertDescription></Alert>}
      {action.error && <ErrorState error={action.error} />}
      <ul className="grid gap-3 sm:grid-cols-3" aria-label={t("queues")}>
        {Object.entries(data.queues).map(([k, q]) => (
          <li key={k}>
            <Card className={q?.stuck ? "border-red-300" : undefined}><CardContent className="space-y-1 p-4 text-sm" data-testid={`queue-${k}`}>
              <p className="font-semibold">{t(`queue.${k}`)}</p>
              {q === null ? <p className="text-muted-foreground">{t("needsMigration")}</p> : (
                <p>{t("queueLine", { queued: q.queued, running: q.running ?? 0, failed: q.failed_7d ?? 0 })}
                  {q.oldest_queued_minutes !== null && <span className="block text-xs text-muted-foreground">{t("oldest", { minutes: q.oldest_queued_minutes })}</span>}
                  {q.stuck && <span className="block font-semibold text-red-700">{t("stuck")}</span>}</p>
              )}
            </CardContent></Card>
          </li>
        ))}
      </ul>
      <div className="flex justify-end"><Button size="sm" variant="outline" onClick={reload}><RefreshCw className="size-4" aria-hidden /> {t("refresh")}</Button></div>
      <Table>
        <TableHeader><TableRow>
          <TableHead>{t("desk")}</TableHead><TableHead>{t("tasks7d")}</TableHead><TableHead>{t("lastSuccess")}</TableHead>
          <TableHead>{t("sources")}</TableHead><TableHead>{t("schedules")}</TableHead><TableHead><span className="sr-only">{t("actions")}</span></TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {data.agents.map((d) => {
            const character = CHARACTERS.find((c) => c.name === d.name);
            return (
              <TableRow key={d.id} data-testid={`desk-${d.id}`}>
                <TableCell>
                  <span className="font-semibold">{d.name}</span> {d.paused && <Badge variant="warning">{t("paused")}</Badge>}
                  <span className="block text-xs text-muted-foreground">{d.title}</span>
                  <span className="block text-xs text-muted-foreground">{t("tools", { count: d.tools_available })}{d.tools_unavailable.length > 0 && ` · ${t("toolsOff", { names: d.tools_unavailable.join(", ") })}`}</span>
                </TableCell>
                <TableCell className="text-xs">
                  {STATUSES.filter((s) => d.tasks_7d[s] > 0).map((s) => <span key={s} className={`block ${s === "failed" ? "text-red-700" : ""}`}>{t(`status.${s}`)}: {d.tasks_7d[s]}</span>)}
                  {STATUSES.every((s) => d.tasks_7d[s] === 0) && <span className="text-muted-foreground">{t("noTasks")}</span>}
                </TableCell>
                <TableCell className="text-xs">
                  {d.last_success_at ? formatDateTime(d.last_success_at, locale) : "—"}
                  {d.last_failure_at && <span className="block text-red-700">{t("lastFailure", { when: formatDateTime(d.last_failure_at, locale), code: d.last_error ?? "" })}</span>}
                </TableCell>
                <TableCell className="text-xs">
                  {!d.monitors ? "—" : t("sourcesLine", { enabled: d.sources_enabled, total: d.sources })}
                  {d.sources_failing > 0 && <span className="block text-red-700">{t("failing", { count: d.sources_failing })}</span>}
                </TableCell>
                <TableCell className="text-xs">
                  {d.schedules.length === 0 ? "—" : d.schedules.map((s) => <span key={s.id} className="block">{t.has(`taskTypes.${s.task_type}`) ? t(`taskTypes.${s.task_type}`) : s.task_type}: {s.enabled ? t("on") : t("off")}</span>)}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap justify-end gap-1">
                    <Button size="sm" variant="outline" disabled={action.busy} onClick={() => void setPaused(d, !d.paused)} data-testid={`pause-${d.id}`}>
                      {d.paused ? <Play className="size-4" aria-hidden /> : <Pause className="size-4" aria-hidden />} {d.paused ? t("resume") : t("pause")}
                    </Button>
                    {character && <Button asChild size="sm" variant="ghost"><Link href={`/ai-office?desk=${character.id}`}>{t("open")}</Link></Button>}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function Tasks() {
  const t = useTranslations("admin.agents");
  const locale = useLocale();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const { data, error, loading, reload } = useApi<Page<AdminTask>>(`agent-tasks:${page}:${status}`, () =>
    api.get<Page<AdminTask>>("/api/v1/admin/agent-operations/tasks", { page, page_size: 20, status: status || undefined }));
  const action = useAction();
  async function act(id: string, what: "rerun" | "cancel") {
    await action.run(() => api.post(`/api/v1/admin/agent-operations/tasks/${id}/${what}`));
    reload();
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("privacy")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="task-status" className="text-sm">{t("statusFilter")}</label>
        <Select id="task-status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="w-auto">
          <option value="">{t("all")}</option>
          {STATUSES.map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}
        </Select>
        <Button size="sm" variant="outline" onClick={reload}><RefreshCw className="size-4" aria-hidden /> {t("refresh")}</Button>
      </div>
      {action.error && <ErrorState error={action.error} />}
      {loading && !data && <LoadingState rows={5} />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && data.items.length === 0 && <EmptyState title={t("noTasks")} />}
      {data && data.items.length > 0 && (
        <>
          <Table>
            <TableHeader><TableRow>
              <TableHead>{t("desk")}</TableHead><TableHead>{t("task")}</TableHead><TableHead>{t("statusFilter")}</TableHead><TableHead>{t("result")}</TableHead>
              <TableHead>{t("created")}</TableHead><TableHead><span className="sr-only">{t("actions")}</span></TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.items.map((x) => (
                <TableRow key={x.id} data-testid="admin-task">
                  <TableCell className="font-semibold">{x.agent_name}</TableCell>
                  <TableCell className="text-xs">{t.has(`taskTypes.${x.task_type}`) ? t(`taskTypes.${x.task_type}`) : x.task_type}<span className="block text-muted-foreground">{t(`by.${x.requested}`)}</span></TableCell>
                  <TableCell><Badge variant={statusVariant(x.status)}>{t(`status.${x.status}`)}</Badge><span className="block text-xs text-muted-foreground">{t("attempts", { n: x.attempts, max: x.max_attempts })}</span></TableCell>
                  <TableCell className="text-xs">
                    {x.error_code && <code className="text-red-700">{x.error_code}</code>}
                    {x.result_count !== undefined && x.result_count !== null && t("counts", { count: x.result_count, fresh: x.new_count ?? 0, changed: x.updated_count ?? 0 })}
                  </TableCell>
                  <TableCell className="text-xs">{formatDateTime(x.created_at, locale)}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      {x.can_rerun && <Button size="sm" variant="outline" disabled={action.busy} onClick={() => void act(x.id, "rerun")}><RotateCcw className="size-4" aria-hidden /> {t("rerun")}</Button>}
                      {x.can_cancel && <Button size="sm" variant="ghost" disabled={action.busy} onClick={() => void act(x.id, "cancel")}><X className="size-4" aria-hidden /> {t("cancel")}</Button>}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Pagination page={page} pageSize={20} total={data.total} onChange={setPage} />
        </>
      )}
    </div>
  );
}

function Schedules() {
  const t = useTranslations("admin.agents");
  const locale = useLocale();
  const { data, error, loading, reload } = useApi<{ globally_enabled: boolean; items: Schedule[] }>("agent-schedules", () =>
    api.get("/api/v1/admin/agent-schedules"));
  const action = useAction();
  const [draft, setDraft] = useState<Record<string, string>>({});
  async function save(s: Schedule, body: Record<string, unknown>) {
    await action.run(() => api.patch(`/api/v1/admin/agent-schedules/${s.id}`, body));
    reload();
  }
  if (loading && !data) return <LoadingState rows={5} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  return (
    <div className="space-y-4">
      <Alert><AlertTitle>{data.globally_enabled ? t("serverOn") : t("schedulesOffTitle")}</AlertTitle><AlertDescription>{t("schedulesHelp")}</AlertDescription></Alert>
      {action.error && <ErrorState error={action.error} />}
      <Table>
        <TableHeader><TableRow>
          <TableHead>{t("desk")}</TableHead><TableHead>{t("task")}</TableHead><TableHead>{t("interval")}</TableHead><TableHead>{t("lastRun")}</TableHead><TableHead>{t("state")}</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {data.items.map((s) => (
            <TableRow key={s.id} data-testid={`schedule-${s.agent_id}-${s.task_type}`}>
              <TableCell className="font-semibold">{s.agent_name}</TableCell>
              <TableCell className="text-xs">{t.has(`taskTypes.${s.task_type}`) ? t(`taskTypes.${s.task_type}`) : s.task_type}</TableCell>
              <TableCell>
                <form className="flex items-center gap-1" onSubmit={(e) => { e.preventDefault(); const h = Number(draft[s.id]); if (h >= 1 && h <= 168) void save(s, { interval_minutes: Math.round(h * 60) }); }}>
                  <label htmlFor={`int-${s.id}`} className="sr-only">{t("interval")}</label>
                  <input id={`int-${s.id}`} type="number" min={1} max={168} value={draft[s.id] ?? String(Math.round(s.interval_minutes / 60))}
                    onChange={(e) => setDraft((d) => ({ ...d, [s.id]: e.target.value }))} className="h-9 w-20 rounded-md border border-input bg-background px-2 text-sm" />
                  <span className="text-xs text-muted-foreground">{t("hours")}</span>
                  {draft[s.id] !== undefined && <Button size="sm" type="submit" variant="outline" disabled={action.busy}>{t("save")}</Button>}
                </form>
              </TableCell>
              <TableCell className="text-xs">{s.last_run_at ? formatDateTime(s.last_run_at, locale) : "—"}{s.last_error && <span className="block text-red-700">{s.last_error}</span>}</TableCell>
              <TableCell>
                <Button size="sm" variant={s.enabled ? "default" : "outline"} role="switch" aria-checked={s.enabled} disabled={action.busy} onClick={() => void save(s, { enabled: !s.enabled })}>
                  {s.enabled ? t("on") : t("off")}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function StorageView() {
  const t = useTranslations("admin.agents");
  const { data, error, loading, reload } = useApi<Storage>("admin-storage", () => api.get<Storage>("/api/v1/admin/storage"));
  if (loading && !data) return <LoadingState rows={4} />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  if (!data.available) return <Alert variant="warning"><AlertTitle>{t("needsMigration")}</AlertTitle><AlertDescription>{t("storageMissing")}</AlertDescription></Alert>;
  const pct = Math.round((data.share ?? 0) * 100);
  return (
    <div className="space-y-4" data-testid="storage">
      <Card><CardContent className="space-y-2 p-4 text-sm">
        <p className="font-semibold">{t("storageLine", { used: mb(data.database_bytes ?? 0), limit: mb(data.limit_bytes), pct })}</p>
        <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={t("tabs.storage")}>
          <div className={`h-full ${data.level === "critical" ? "bg-red-600" : data.level === "warning" ? "bg-amber-500" : "bg-emerald-600"}`} style={{ width: `${Math.min(pct, 100)}%` }} />
        </div>
        <p className="text-muted-foreground">{t("storageHelp")}</p>
      </CardContent></Card>
      <Table>
        <TableHeader><TableRow><TableHead>{t("table")}</TableHead><TableHead>{t("size")}</TableHead><TableHead>{t("indexes")}</TableHead><TableHead>{t("rows")}</TableHead><TableHead>{t("rows30d")}</TableHead></TableRow></TableHeader>
        <TableBody>
          {(data.tables ?? []).filter((x) => x.total_bytes > 0).slice(0, 15).map((x) => (
            <TableRow key={x.table_name}>
              <TableCell><code>{x.table_name}</code></TableCell><TableCell>{mb(x.total_bytes)}</TableCell>
              <TableCell>{x.index_bytes === null ? "—" : mb(x.index_bytes)}</TableCell><TableCell>{x.row_estimate}</TableCell>
              <TableCell>{data.rows_added_30d?.[x.table_name] ?? "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
