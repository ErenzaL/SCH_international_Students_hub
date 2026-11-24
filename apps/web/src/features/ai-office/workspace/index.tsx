"use client";

/**
 * Which workspace a tab shows. The backend registry decides each agent's interface type, default view and tabs for
 * the viewer; this map only turns a view id into a component.
 */
import { useTranslations } from "next-intl";
import { BadgeCheck, Database, ShieldCheck } from "lucide-react";
import type { PanelTab } from "@/features/ai-office/agents";
import { ReviewQueue, SourcesAdmin } from "@/features/ai-office/workspace/admin";
import { CareersWorkspace } from "@/features/ai-office/workspace/careers";
import { useWorkspace } from "@/features/ai-office/workspace/context";
import { EventsWorkspace } from "@/features/ai-office/workspace/events";
import { MonitoringWorkspace } from "@/features/ai-office/workspace/monitoring";
import { OpportunitiesWorkspace } from "@/features/ai-office/workspace/opportunities";
import { ChecklistsWorkspace, ProceduresWorkspace, TopikWorkspace } from "@/features/ai-office/workspace/services";
import { MyRequestsWorkspace, SupportRequestWorkspace } from "@/features/ai-office/workspace/support";
import { WorkspaceSection } from "@/features/ai-office/workspace/parts";

export const WORKSPACE_VIEWS: Partial<Record<PanelTab, () => React.ReactElement>> = {
  opportunities: OpportunitiesWorkspace,
  monitoring: MonitoringWorkspace,
  events: EventsWorkspace,
  careers: CareersWorkspace,
  checklists: ChecklistsWorkspace,
  procedures: ProceduresWorkspace,
  topik: TopikWorkspace,
  request: SupportRequestWorkspace,
  requests: MyRequestsWorkspace,
  review: ReviewQueue,
  sources: SourcesAdmin,
  about: AboutAgent,
};

export function WorkspaceView({ view }: { view: PanelTab }) {
  const View = WORKSPACE_VIEWS[view];
  return View ? <View /> : null;
}

/** What this employee does, where the data comes from and what it never does (all from the backend registry). */
function AboutAgent() {
  const ws = useWorkspace();
  const t = useTranslations("office.ws.about");
  const tCap = useTranslations("office.ws.capabilities");
  const tData = useTranslations("office.ws.dataSources");
  const tScope = useTranslations("office.agent.scope");
  const tNever = useTranslations("office.agent.never");
  const ui = ws.agent.interface;
  return (
    <div className="space-y-4" data-testid="desk-capabilities" data-interface={ui?.type}>
      <p>{tScope.has(ws.c.role) ? tScope(ws.c.role) : null}</p>
      {ui && (
        <p className="inline-flex rounded-full bg-muted px-2 py-0.5 text-[11px] font-bold" data-testid="interface-type">
          {t(`types.${ui.type}`)}
        </p>
      )}
      {ui && ui.capabilities.length > 0 && (
        <WorkspaceSection title={t("capabilities")} icon={<BadgeCheck className="size-4" />}>
          <ul className="space-y-1">
            {ui.capabilities.map((c) => (
              <li key={c} className="rounded-xl bg-emerald-50 px-3 py-1.5 dark:bg-emerald-950/30" data-status="available">
                {tCap.has(c) ? tCap(c) : c}
              </li>
            ))}
          </ul>
        </WorkspaceSection>
      )}
      {ui && ui.data_sources.length > 0 && (
        <WorkspaceSection title={t("dataSources")} icon={<Database className="size-4" />}>
          <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
            {ui.data_sources.map((d) => <li key={d}>{tData.has(d) ? tData(d) : d}</li>)}
          </ul>
        </WorkspaceSection>
      )}
      {ws.agent.restricted_actions.length > 0 && (
        <WorkspaceSection title={t("never")} icon={<ShieldCheck className="size-4" />}>
          <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
            {ws.agent.restricted_actions.map((r) => <li key={r}>{tNever.has(r) ? tNever(r) : r}</li>)}
          </ul>
        </WorkspaceSection>
      )}
      <p className="text-xs text-muted-foreground">{t("serverChecks")}</p>
    </div>
  );
}
