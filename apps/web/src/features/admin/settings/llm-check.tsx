"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Stethoscope } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api, errorMessage } from "@/lib/api";

interface Probe {
  role: "primary" | "fallback";
  model: string;
  call: "generate" | "stream";
  ok: boolean;
  served_by?: string | null;
  latency_ms: number;
  total_tokens?: number | null;
  error?: string | null;
  http?: number | null;
  status?: string | null;
  quota_id?: string | null;
  detail?: string | null;
}
interface LlmCheck { provider: string; primary?: string | null; fallback?: string | null; probes: Probe[]; note?: string }

/** Admin: test the configured AI models with the server's own key (tiny synthetic calls, nothing secret shown). */
export function LlmCheckCard() {
  const t = useTranslations("admin.settings.llmCheck");
  const [result, setResult] = useState<LlmCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.post<LlmCheck>("/api/v1/admin/system/llm-check"));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mt-6">
      <CardContent className="space-y-3 p-4 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="font-medium">{t("title")}</p>
            <p className="text-muted-foreground">{t("description")}</p>
          </div>
          <Button size="sm" variant="outline" onClick={run} disabled={busy} data-testid="llm-check">
            {busy ? <Loader2 className="animate-spin" /> : <Stethoscope />} {t("run")}
          </Button>
        </div>
        {error && <p className="text-destructive">{error}</p>}
        {result?.note && <p className="text-muted-foreground">{result.note}</p>}
        {result && result.probes.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr><th className="py-1 pr-3">{t("model")}</th><th className="pr-3">{t("call")}</th>
                  <th className="pr-3">{t("result")}</th><th className="pr-3">{t("latency")}</th><th>{t("details")}</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {result.probes.map((p) => (
                  <tr key={`${p.model}-${p.call}`} className="align-top">
                    <td className="py-1.5 pr-3 font-mono">{p.model} <span className="text-muted-foreground">({t(p.role)})</span></td>
                    <td className="pr-3">{p.call}</td>
                    <td className={p.ok ? "pr-3 font-medium text-emerald-700" : "pr-3 font-medium text-red-700"}>
                      {p.ok ? t("ok") : p.error}
                    </td>
                    <td className="pr-3">{p.latency_ms} ms</td>
                    <td className="break-words text-muted-foreground">
                      {p.ok ? `${p.served_by ?? p.model} · ${p.total_tokens ?? "?"} tokens`
                        : [p.http, p.status, p.quota_id, p.detail].filter(Boolean).join(" · ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
