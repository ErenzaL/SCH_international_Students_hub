"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Save } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/shared/states";
import { useMe } from "@/features/admin/shell/admin-context";
import { api, ApiError, errorMessage } from "@/lib/api";
import { LOCALES, LOCALE_LABELS } from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import { useApi } from "@/lib/use-api";
import type { AdminUser, LanguageCode, LanguageTeams, Page, TeamAssignment } from "@/types/api";

type Flags = Omit<TeamAssignment, "language">;
const FLAGS: (keyof Flags)[] = ["can_support", "can_review_translations", "is_team_lead"];

/** Super admins edit per-language permissions; team leads see their own teams read-only. */
export function LanguageTeamsPage() {
  const t = useTranslations("admin.teams");
  const me = useMe();
  const teams = useApi<LanguageTeams>("language-teams", () => api.get<LanguageTeams>("/api/v1/admin/language-teams"));

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("subtitle")} />
      {teams.loading && <LoadingState rows={3} />}
      {teams.error &&
        (teams.error instanceof ApiError && teams.error.status === 404 ? (
          <Alert variant="info">
            <AlertDescription>{t("notLead")}</AlertDescription>
          </Alert>
        ) : (
          <ErrorState error={teams.error} onRetry={teams.reload} />
        ))}
      {teams.data && (
        <div className="grid gap-4 md:grid-cols-2">
          {teams.data.items.map((team) => (
            <Card key={team.language}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2 text-base">
                  {LOCALE_LABELS[team.language]}
                  <span className="text-xs font-normal text-muted-foreground">
                    {t("counts", { waiting: team.waiting, active: team.active })}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {team.members.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("noMembers")}</p>
                ) : (
                  <ul className="space-y-1 text-sm">
                    {team.members.map((m) => (
                      <li key={m.user_id} className="flex flex-wrap items-center gap-1">
                        <span className="font-medium">{m.display_name ?? m.email}</span>
                        {m.can_support && <Badge variant="secondary">{t("flag.can_support")}</Badge>}
                        {m.can_review_translations && <Badge variant="info">{t("flag.can_review_translations")}</Badge>}
                        {m.is_team_lead && <Badge variant="success">{t("flag.is_team_lead")}</Badge>}
                        {!m.is_available && <Badge variant="muted">{t("unavailable")}</Badge>}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      {me.role === "super_admin" && teams.data?.can_manage_members && <MemberEditor onSaved={teams.reload} />}
    </div>
  );
}

function MemberEditor({ onSaved }: { onSaved: () => void }) {
  const t = useTranslations("admin.teams");
  const users = useApi<Page<AdminUser>>("teams-users", () =>
    api.get<Page<AdminUser>>("/api/v1/admin/users", { page: 1, page_size: 100 }),
  );
  const teams = useApi<LanguageTeams>("language-teams-editor", () => api.get<LanguageTeams>("/api/v1/admin/language-teams"));
  const [userId, setUserId] = useState("");
  const [draft, setDraft] = useState<Partial<Record<LanguageCode, Flags>>>({});
  const [done, setDone] = useState(false);
  const action = useAction();

  function load(id: string) {
    setUserId(id);
    setDone(false);
    const next: Partial<Record<LanguageCode, Flags>> = {};
    for (const team of teams.data?.items ?? []) {
      const m = team.members.find((x) => x.user_id === id);
      if (m) next[team.language] = { can_support: m.can_support, can_review_translations: m.can_review_translations, is_team_lead: m.is_team_lead };
    }
    setDraft(next);
  }
  function toggle(lang: LanguageCode, flag: keyof Flags | "member") {
    setDraft((d) => {
      const cur = d[lang];
      if (flag === "member") {
        const copy = { ...d };
        if (cur) delete copy[lang];
        else copy[lang] = { can_support: true, can_review_translations: false, is_team_lead: false };
        return copy;
      }
      if (!cur) return d;
      return { ...d, [lang]: { ...cur, [flag]: !cur[flag] } };
    });
  }
  async function save() {
    const assignments = (Object.entries(draft) as [LanguageCode, Flags][]).map(([language, f]) => ({ language, ...f }));
    const res = await action.run(() => api.put(`/api/v1/admin/users/${userId}/team`, { assignments }));
    if (res) {
      setDone(true);
      onSaved();
      teams.reload();
    }
  }

  const staff = (users.data?.items ?? []).filter((u) => u.role !== "student");
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("editTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{t("editNote")}</p>
        {users.error && <ErrorState error={users.error} onRetry={users.reload} />}
        {users.data && staff.length === 0 && <EmptyState title={t("noStaff")} />}
        {staff.length > 0 && (
          <Select aria-label={t("chooseUser")} value={userId} onChange={(e) => load(e.target.value)} className="max-w-md">
            <option value="">{t("chooseUser")}</option>
            {staff.map((u) => (
              <option key={u.id} value={u.id}>
                {u.display_name ?? u.email} ({u.role})
              </option>
            ))}
          </Select>
        )}
        {userId && (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("language")}</TableHead>
                  <TableHead>{t("member")}</TableHead>
                  {FLAGS.map((f) => (
                    <TableHead key={f}>{t(`flag.${f}`)}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {LOCALES.map((lang) => {
                  const f = draft[lang];
                  return (
                    <TableRow key={lang}>
                      <TableCell>{LOCALE_LABELS[lang]}</TableCell>
                      <TableCell>
                        <input type="checkbox" aria-label={`${LOCALE_LABELS[lang]} ${t("member")}`} checked={Boolean(f)} onChange={() => toggle(lang, "member")} />
                      </TableCell>
                      {FLAGS.map((flag) => (
                        <TableCell key={flag}>
                          <input
                            type="checkbox"
                            aria-label={`${LOCALE_LABELS[lang]} ${t(`flag.${flag}`)}`}
                            disabled={!f}
                            checked={Boolean(f?.[flag])}
                            onChange={() => toggle(lang, flag)}
                          />
                        </TableCell>
                      ))}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            {action.error && <Alert variant="destructive">{errorMessage(action.error)}</Alert>}
            {done && <Alert variant="success">{t("saved")}</Alert>}
            <Button disabled={action.busy} onClick={save}>
              <Save /> {t("save")}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
