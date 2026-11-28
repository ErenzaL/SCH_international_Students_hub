"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Gauge, OctagonPause, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/shared/states";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/use-api";

interface DayTotal { day: string; lane: "chat" | "background"; attempts: number; failed: number; input_tokens: number;
  output_tokens: number; est_cost_usd: number; fully_priced: boolean }
export interface AiUsage {
  provider: string;
  usage: { prices_configured: string[]; price_errors: string[]; by_purpose: Record<string, { attempts: number; ok?: number; failed?: number }> };
  daily_budget: { global_limit: number; global_generated: number; global_used_all_processes: number | null; persistent: boolean | null;
    persist_error: string | null };
  background_budget: { attempts_today: number; attempts_today_all_processes: number | null; daily_attempt_limit: number;
    persistent: boolean | null; persist_error: string | null };
  background_controls: { stopped: boolean; stop_from_env: boolean; flags_available: boolean | null; daily_usd_limit: number | null;
    estimated_spend_today_usd: number; unpriced_attempts_today: number; model: string; model_priced: boolean } | null;
  daily: { available: boolean; totals: DayTotal[] };
}

/** Admin: today's AI budgets, the last 7 days of AI use (estimated cost only where prices are configured) and the emergency stop
 * for background AI. Shows operational numbers only: never prompts, answers or student data. */
export function AiUsageCard() {
  const t = useTranslations("admin.settings.aiUsage");
  const { data, error, loading, reload } = useApi<AiUsage>("admin-ai-usage", () => api.get<AiUsage>("/api/v1/admin/system/llm-usage"));
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const ctl = data?.background_controls;

  async function toggle(stop: boolean) {
    if (stop && !window.confirm(t("confirmStop"))) return;
    setBusy(true);
    setActionError(null);
    try {
      await api.post("/api/v1/admin/system/ai-background-stop", { stop });
      reload();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const used = (all: number | null, local: number) => (all ?? local);
  const money = (x: DayTotal) => (x.fully_priced ? `$${x.est_cost_usd.toFixed(4)}` : t("unpriced"));

  return (
    <Card className="mt-6" data-testid="ai-usage">
      <CardContent className="space-y-4 p-4 text-sm">
        <div className="flex items-center gap-2">
          <Gauge className="size-4 text-primary" aria-hidden />
          <p className="font-medium">{t("title")}</p>
        </div>
        <p className="text-muted-foreground">{t("description")}</p>
        {loading && !data && <LoadingState rows={2} />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {data && (
          <>
            <dl className="grid gap-2 sm:grid-cols-2">
              <div className="rounded-lg bg-muted/60 p-3">
                <dt className="text-xs text-muted-foreground">{t("chatToday")}</dt>
                <dd className="font-mono" data-testid="chat-budget">
                  {used(data.daily_budget.global_used_all_processes, data.daily_budget.global_generated)} / {data.daily_budget.global_limit}
                </dd>
              </div>
              <div className="rounded-lg bg-muted/60 p-3">
                <dt className="text-xs text-muted-foreground">{t("backgroundToday")}</dt>
                <dd className="font-mono" data-testid="background-budget">
                  {used(data.background_budget.attempts_today_all_processes, data.background_budget.attempts_today)} / {data.background_budget.daily_attempt_limit}
                </dd>
              </div>
            </dl>
            <p className="text-xs" data-testid="budget-persistence">
              {data.background_budget.persistent === false || data.daily_budget.persistent === false ? t("notPersistent")
                : data.background_budget.persistent ? t("persistent") : t("persistUnknown")}
            </p>

            {ctl && (
              <div className={ctl.stopped ? "rounded-lg border border-red-300 bg-red-50 p-3 text-red-950 dark:bg-red-950/30 dark:text-red-100"
                : "rounded-lg border border-border p-3"} data-testid="background-stop" data-stopped={ctl.stopped ? "true" : "false"}>
                <p className="font-medium">{ctl.stopped ? t("stopped") : t("running")}</p>
                {ctl.stop_from_env && <p className="text-xs">{t("stopFromEnv")}</p>}
                {ctl.daily_usd_limit ? (
                  <p className="text-xs">{t("ceiling", { spent: ctl.estimated_spend_today_usd.toFixed(4), limit: ctl.daily_usd_limit.toFixed(2) })}</p>
                ) : null}
                {!ctl.model_priced && <p className="text-xs">{t("modelUnpriced", { model: ctl.model })}</p>}
                <div className="mt-2">
                  {ctl.stopped && !ctl.stop_from_env ? (
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => void toggle(false)} data-testid="resume-background">
                      <Play className="size-4" aria-hidden /> {t("resume")}
                    </Button>
                  ) : !ctl.stopped ? (
                    <Button size="sm" variant="destructive" disabled={busy || ctl.flags_available === false}
                      onClick={() => void toggle(true)} data-testid="stop-background">
                      <OctagonPause className="size-4" aria-hidden /> {t("stop")}
                    </Button>
                  ) : null}
                </div>
                {ctl.flags_available === false && <p className="mt-1 text-xs">{t("needsMigration")}</p>}
                {actionError && <p className="mt-1 text-xs text-destructive" role="alert">{actionError}</p>}
              </div>
            )}

            <div>
              <p className="mb-1 font-medium">{t("last7")}</p>
              {!data.daily.available ? <p className="text-xs text-muted-foreground">{t("noDaily")}</p>
                : data.daily.totals.length === 0 ? <p className="text-xs text-muted-foreground">{t("noUse")}</p> : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs" data-testid="usage-days">
                    <thead><tr className="text-left text-muted-foreground">
                      <th className="py-1 pr-2">{t("day")}</th><th className="pr-2">{t("lane")}</th><th className="pr-2">{t("attempts")}</th>
                      <th className="pr-2">{t("failed")}</th><th className="pr-2">{t("tokens")}</th><th>{t("cost")}</th>
                    </tr></thead>
                    <tbody>
                      {data.daily.totals.map((x) => (
                        <tr key={`${x.day}-${x.lane}`} className="border-t border-border">
                          <td className="py-1 pr-2 font-mono">{x.day}</td><td className="pr-2">{t(`lanes.${x.lane}`)}</td>
                          <td className="pr-2">{x.attempts}</td><td className="pr-2">{x.failed}</td>
                          <td className="pr-2 font-mono">{x.input_tokens.toLocaleString()} / {x.output_tokens.toLocaleString()}</td>
                          <td className="font-mono">{money(x)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <p className="text-xs text-muted-foreground" data-testid="prices">
              {data.usage.prices_configured.length ? t("prices", { models: data.usage.prices_configured.join(", ") }) : t("noPrices")}
            </p>
            <p className="text-xs text-muted-foreground">{t("estimateNote")}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
