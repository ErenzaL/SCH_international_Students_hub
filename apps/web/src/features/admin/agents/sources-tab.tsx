"use client";

/** Official sources of every desk: what is watched, prepared sources to add, and a form for another official page. */
import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ExternalLink, Plus, RotateCcw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState } from "@/components/shared/states";
import { api } from "@/lib/api";
import { CATEGORY_SLUGS } from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import { formatDateTime } from "@/lib/utils";

const DESKS = { announcement: "Robo", scholarship: "Leo", career: "Daniel", events: "Mia", immigration: "Yuna", academic: "Joon", topik: "Seo" } as const;
type Desk = keyof typeof DESKS;
interface Source { id: string; agent_id: Desk; name: string; kind: string; url: string; enabled: boolean; last_checked_at: string | null; last_status: string | null; last_error: string | null; consecutive_failures: number }
interface Prepared { agent_id: Desk; name: string; kind: string; url: string; category: string; language: string; config: Record<string, unknown>; added: boolean; ready: boolean; needs: string | null; validated: { status?: string; checked?: string }; recommended_interval_minutes: number }

export function SourcesTab() {
  const t = useTranslations("admin.agents");
  const locale = useLocale();
  const sources = useApi<{ items: Source[] }>("admin-sources", () => api.get("/api/v1/admin/discovery/sources"));
  const catalog = useApi<{ items: Prepared[] }>("admin-catalog", () => api.get("/api/v1/admin/discovery/catalog"));
  const action = useAction();
  const [confirm, setConfirm] = useState<string | null>(null);
  const reload = () => { sources.reload(); catalog.reload(); };
  async function run(fn: () => Promise<unknown>) {
    await action.run(fn);
    setConfirm(null);
    reload();
  }
  const open = (catalog.data?.items ?? []).filter((x) => !x.added);
  return (
    <div className="space-y-8">
      <p className="text-sm text-muted-foreground">{t("sourcesHelp")}</p>
      {action.error && <ErrorState error={action.error} />}
      <section className="space-y-3" aria-labelledby="src-active">
        <h2 id="src-active" className="text-lg font-semibold">{t("sourcesActive")}</h2>
        {sources.loading && !sources.data && <LoadingState rows={3} />}
        {sources.error && <ErrorState error={sources.error} onRetry={reload} />}
        {sources.data && (sources.data.items.length === 0 ? <EmptyState title={t("sourcesNone")} /> : (
          <Table>
            <TableHeader><TableRow><TableHead>{t("desk")}</TableHead><TableHead>{t("source")}</TableHead><TableHead>{t("lastRun")}</TableHead><TableHead>{t("state")}</TableHead><TableHead><span className="sr-only">{t("actions")}</span></TableHead></TableRow></TableHeader>
            <TableBody>
              {sources.data.items.map((s) => (
                <TableRow key={s.id} data-testid="source-row">
                  <TableCell className="font-semibold">{DESKS[s.agent_id] ?? s.agent_id}</TableCell>
                  <TableCell className="text-xs"><a href={s.url} target="_blank" rel="noopener noreferrer" className="font-medium text-primary hover:underline">{s.name} <ExternalLink className="inline size-3" aria-hidden /></a></TableCell>
                  <TableCell className="text-xs">{s.last_checked_at ? formatDateTime(s.last_checked_at, locale) : "—"}{s.last_error && <span className="block text-red-700">{s.last_error}</span>}</TableCell>
                  <TableCell>{s.consecutive_failures > 0 ? <Badge variant="danger">{t("failing", { count: s.consecutive_failures })}</Badge> : <Badge variant={s.enabled ? "success" : "muted"}>{s.enabled ? t("on") : t("off")}</Badge>}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap justify-end gap-1">
                      <Button size="sm" variant="outline" disabled={action.busy} onClick={() => void run(() => api.patch(`/api/v1/admin/discovery/sources/${s.id}`, { enabled: !s.enabled }))}>{s.enabled ? t("turnOff") : t("turnOn")}</Button>
                      {s.consecutive_failures > 0 && <Button size="sm" variant="ghost" disabled={action.busy} onClick={() => void run(() => api.patch(`/api/v1/admin/discovery/sources/${s.id}`, { reset_failures: true }))}><RotateCcw className="size-4" aria-hidden /> {t("reset")}</Button>}
                      {confirm === s.id
                        ? <Button size="sm" variant="destructive" disabled={action.busy} onClick={() => void run(() => api.delete(`/api/v1/admin/discovery/sources/${s.id}`))}>{t("confirmDelete")}</Button>
                        : <Button size="sm" variant="ghost" aria-label={t("remove")} onClick={() => setConfirm(s.id)}><Trash2 className="size-4" aria-hidden /></Button>}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ))}
      </section>

      <section className="space-y-3" aria-labelledby="src-prepared">
        <h2 id="src-prepared" className="text-lg font-semibold">{t("prepared", { count: open.length })}</h2>
        <p className="text-sm text-muted-foreground">{t("preparedHelp")}</p>
        <ul className="grid gap-2 md:grid-cols-2">
          {open.map((x) => (
            <li key={`${x.agent_id}${x.url}${x.kind}`}>
              <Card><CardContent className="flex flex-wrap items-center gap-2 p-3 text-sm" data-testid="prepared">
                <span className="min-w-0 flex-1"><span className="font-semibold">{DESKS[x.agent_id]}</span> · <a className="break-words text-primary hover:underline" href={x.url} target="_blank" rel="noopener noreferrer">{x.name}</a>
                  <span className="block text-xs text-muted-foreground">{x.needs ? (x.ready ? t("keySet", { key: x.needs }) : t("keyMissing", { key: x.needs })) : t("checkedOn", { date: x.validated.checked ?? "—" })}</span></span>
                <Button size="sm" variant="outline" disabled={action.busy} onClick={() => void run(() => api.post("/api/v1/admin/discovery/sources", {
                  agent_id: x.agent_id, name: x.name, kind: x.kind, url: x.url, category: x.category, language: x.language, config: x.config }))}><Plus className="size-4" aria-hidden /> {t("add")}</Button>
              </CardContent></Card>
            </li>
          ))}
        </ul>
      </section>
      <CustomSource onAdded={reload} />
    </div>
  );
}

function CustomSource({ onAdded }: { onAdded: () => void }) {
  const t = useTranslations("admin.agents");
  const tCat = useTranslations("categories");
  const action = useAction();
  const [f, setF] = useState({ agent_id: "announcement", name: "", kind: "page", url: "", category: "university-announcements", config: "" });
  const [bad, setBad] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF((x) => ({ ...x, [k]: e.target.value }));
  async function add() {
    let config: unknown = {};
    try {
      config = f.config.trim() ? JSON.parse(f.config) : {};
      setBad(false);
    } catch {
      setBad(true);
      return;
    }
    const r = await action.run(() => api.post("/api/v1/admin/discovery/sources", { ...f, config }));
    if (r) {
      setF((x) => ({ ...x, name: "", url: "", config: "" }));
      onAdded();
    }
  }
  return (
    <section className="space-y-3" aria-labelledby="src-custom">
      <h2 id="src-custom" className="text-lg font-semibold">{t("custom")}</h2>
      <p className="text-sm text-muted-foreground">{t("customHelp")}</p>
      {action.error && <ErrorState error={action.error} />}
      <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); void add(); }}>
        <div><Label htmlFor="src-desk">{t("desk")}</Label><Select id="src-desk" value={f.agent_id} onChange={set("agent_id")}>{Object.entries(DESKS).map(([id, n]) => <option key={id} value={id}>{n}</option>)}</Select></div>
        <div><Label htmlFor="src-kind">{t("kind")}</Label><Select id="src-kind" value={f.kind} onChange={set("kind")}>{["page", "listing", "sch_board"].map((k) => <option key={k} value={k}>{t(`kinds.${k}`)}</option>)}</Select></div>
        <div><Label htmlFor="src-name">{t("source")}</Label><Input id="src-name" value={f.name} onChange={set("name")} required minLength={2} maxLength={200} /></div>
        <div><Label htmlFor="src-url">URL</Label><Input id="src-url" type="url" value={f.url} onChange={set("url")} required maxLength={1000} /></div>
        <div><Label htmlFor="src-cat">{t("category")}</Label><Select id="src-cat" value={f.category} onChange={set("category")}>{CATEGORY_SLUGS.map((c) => <option key={c} value={c}>{tCat.has(c) ? tCat(c) : c}</option>)}</Select></div>
        <div className="sm:col-span-2"><Label htmlFor="src-config">{t("config")}</Label><Textarea id="src-config" rows={3} value={f.config} onChange={set("config")} placeholder='{"item_selector": "table tbody tr"}' />{bad && <FieldError>{t("configBad")}</FieldError>}</div>
        <div><Button type="submit" disabled={action.busy}><Plus className="size-4" aria-hidden /> {t("add")}</Button></div>
      </form>
    </section>
  );
}
