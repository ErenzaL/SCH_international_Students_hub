"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowLeft } from "lucide-react";
import { Tabs } from "@/components/ui/tabs";
import { PageHeader } from "@/components/shared/states";
import { DocumentIntake } from "@/features/admin/knowledge/intake-document";
import { PasteIntake } from "@/features/admin/knowledge/intake-paste";
import { ScreenshotIntake } from "@/features/admin/knowledge/intake-screenshot";
import { WebsiteIntake } from "@/features/admin/knowledge/intake-website";
import { isAdminRole, useMe } from "@/features/admin/shell/admin-context";

type Method = "website" | "document" | "screenshot" | "paste";

export function AddKnowledgePage() {
  const t = useTranslations("admin.ks");
  const me = useMe();
  const admin = isAdminRole(me.role);
  // Website registration (outbound fetching) is admin-only; supporters add files, screenshots and pastes.
  const methods: Method[] = admin ? ["website", "document", "screenshot", "paste"] : ["document", "screenshot", "paste"];
  const [method, setMethod] = useState<Method>(methods[0]);
  return (
    <div>
      <Link href={admin ? "/admin/knowledge-sources" : "/admin/submissions"} className="mb-3 inline-flex items-center gap-1 text-sm text-primary hover:underline">
        <ArrowLeft className="size-4" /> {admin ? t("backToSources") : t("mySubmissions")}
      </Link>
      <PageHeader title={t("addKnowledge")} description={t("addSubtitle")} />
      <Tabs label={t("methods")} value={method} onChange={(id) => setMethod(id as Method)} items={methods.map((m) => ({ id: m, label: t(`method.${m}`) }))} className="mb-5" />
      <div role="tabpanel" aria-labelledby={`tab-${method}`}>
        {method === "website" && <WebsiteIntake />}
        {method === "document" && <DocumentIntake />}
        {method === "screenshot" && <ScreenshotIntake />}
        {method === "paste" && <PasteIntake />}
      </div>
    </div>
  );
}
