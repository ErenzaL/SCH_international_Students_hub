"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import type {
  AnnouncementStatus,
  AuthorityType,
  IndexingStatus,
  JobStatus,
  PublicationStatus,
  Scope,
  SourceStatus,
  TranslationStatus,
  VerificationStatus,
} from "@/types/api";

type Variant = React.ComponentProps<typeof Badge>["variant"];

const announcementVariant: Record<AnnouncementStatus, Variant> = {
  active: "success",
  upcoming: "info",
  expired: "muted",
};
export function AnnouncementStatusBadge({ status }: { status: AnnouncementStatus }) {
  const t = useTranslations("status");
  return <Badge variant={announcementVariant[status]}>{t(status)}</Badge>;
}

const sourceVariant: Record<SourceStatus, Variant> = {
  registered: "secondary",
  fetching: "info",
  processing: "info",
  pending_review: "warning",
  approved: "success",
  failed: "danger",
  blocked: "danger",
  inactive: "muted",
};
export function SourceStatusBadge({ status }: { status: SourceStatus }) {
  const t = useTranslations("enums.sourceStatus");
  return <Badge variant={sourceVariant[status]}>{t(status)}</Badge>;
}

const versionVariant: Record<VerificationStatus, Variant> = {
  draft: "muted",
  pending_review: "warning",
  approved: "success",
  rejected: "danger",
  superseded: "muted",
};
export function VersionStatusBadge({ status }: { status: VerificationStatus }) {
  const t = useTranslations("enums.verification");
  return <Badge variant={versionVariant[status]}>{t(status)}</Badge>;
}

const jobVariant: Record<JobStatus, Variant> = {
  queued: "secondary",
  running: "info",
  succeeded: "success",
  failed: "danger",
};
export function JobStatusBadge({ status }: { status: JobStatus }) {
  const t = useTranslations("enums.jobStatus");
  return <Badge variant={jobVariant[status]}>{t(status)}</Badge>;
}

const pubVariant: Record<PublicationStatus, Variant> = {
  draft: "muted",
  pending_approval: "warning",
  published: "success",
  rejected: "danger",
  canceled: "muted",
};
export function PublicationBadge({ status }: { status: PublicationStatus }) {
  const t = useTranslations("enums.publication");
  return <Badge variant={pubVariant[status]}>{t(status)}</Badge>;
}

const trVariant: Record<TranslationStatus, Variant> = {
  machine_draft: "warning",
  in_review: "info",
  human_approved: "success",
  rejected: "danger",
};
/** Machine drafts are always labelled as such – never as human-reviewed. */
export function TranslationStatusBadge({ status }: { status: TranslationStatus }) {
  const t = useTranslations("enums.translation");
  return <Badge variant={trVariant[status]}>{t(status)}</Badge>;
}

export function ScopeBadge({ scope }: { scope: Scope }) {
  const t = useTranslations("enums.scope");
  return <Badge variant={scope === "university" ? "default" : "outline"}>{t(scope)}</Badge>;
}

export function AuthorityBadge({ authority }: { authority: AuthorityType }) {
  const t = useTranslations("enums.authority");
  return <Badge variant="secondary">{t(authority)}</Badge>;
}

export function TestDataBadge() {
  const t = useTranslations("common");
  return <Badge variant="warning">{t("testData")}</Badge>;
}

const indexVariant: Record<IndexingStatus, Variant> = {
  not_indexed: "muted",
  indexing: "info",
  indexed: "success",
  failed: "danger",
};
export function IndexingStatusBadge({ status }: { status: IndexingStatus }) {
  const t = useTranslations("enums.indexing");
  return <Badge variant={indexVariant[status]}>{t(status)}</Badge>;
}

/** Shown when verified guidance is older than the category's freshness window. */
export function StaleBadge({ days }: { days?: number | null }) {
  const t = useTranslations("knowledge");
  return (
    <Badge variant="warning" title={t("staleHint")}>
      {days != null ? t("staleDays", { days }) : t("stale")}
    </Badge>
  );
}

export function ExactMatchBadge() {
  const t = useTranslations("knowledge");
  return <Badge variant="info">{t("exactMatch")}</Badge>;
}
