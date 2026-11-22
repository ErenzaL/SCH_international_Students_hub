"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Label, Select } from "@/components/ui/input";
import { api, errorMessage } from "@/lib/api";
import { AUTHORITY_TYPES, CATEGORY_SLUGS, FETCHABLE_SOURCE_TYPES, LOCALES, LOCALE_LABELS, SCOPES, SYNC_FREQUENCIES } from "@/lib/constants";
import { useAction } from "@/lib/use-action";
import { useCategoryName } from "@/lib/use-category-name";
import type { Source, SourcePatch } from "@/types/api";

/** Edit metadata, sync schedule and board settings (PATCH /admin/sources/{id}). */
export function EditSourceDialog({ source, onClose, onSaved }: { source: Source | null; onClose: () => void; onSaved: (s: Source) => void }) {
  const c = useTranslations("common");
  return (
    <Dialog open={!!source} onOpenChange={(o) => !o && onClose()}>
      <DialogContent closeLabel={c("close")} className="max-w-2xl">
        {source && <EditForm key={source.id} source={source} onSaved={onSaved} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function EditForm({ source, onSaved, onClose }: { source: Source; onSaved: (s: Source) => void; onClose: () => void }) {
  const t = useTranslations("admin.ks");
  const e = useTranslations("enums");
  const c = useTranslations("common");
  const categoryName = useCategoryName();
  const action = useAction();
  const fetchable = FETCHABLE_SOURCE_TYPES.includes(source.source_type);
  const [v, setV] = useState({
    title: source.title,
    organization: source.organization,
    category: source.category,
    language: source.language,
    scope: source.scope,
    authority_type: source.authority_type,
    sync_frequency: source.sync_frequency,
    stale_after_days: source.stale_after_days ? String(source.stale_after_days) : "",
    max_items: String(source.config?.max_items ?? 5),
    max_pages: String(source.config?.max_pages ?? 1),
  });
  const set = (k: keyof typeof v, val: string) => setV((s) => ({ ...s, [k]: val }));

  async function save(ev: React.FormEvent) {
    ev.preventDefault();
    const body: SourcePatch = {
      title: v.title.trim(),
      organization: v.organization.trim(),
      category: v.category,
      language: v.language,
      scope: v.scope,
      authority_type: v.authority_type,
    };
    if (fetchable) body.sync_frequency = v.sync_frequency;
    if (v.stale_after_days.trim()) body.stale_after_days = Number(v.stale_after_days);
    if (source.source_type === "sch_board") body.config = { max_items: Number(v.max_items), max_pages: Number(v.max_pages) };
    const saved = await action.run(() => api.patch<Source>(`/api/v1/admin/sources/${source.id}`, body));
    if (saved) onSaved(saved);
  }

  return (
    <form onSubmit={save} className="space-y-4">
      <DialogHeader>
        <DialogTitle>{t("editTitle")}</DialogTitle>
        <DialogDescription>{t("editDescription")}</DialogDescription>
      </DialogHeader>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Label htmlFor="es-title">{t("meta.title")}</Label>
          <Input id="es-title" required value={v.title} onChange={(ev) => set("title", ev.target.value)} />
        </div>
        <div>
          <Label htmlFor="es-org">{t("meta.organization")}</Label>
          <Input id="es-org" required value={v.organization} onChange={(ev) => set("organization", ev.target.value)} />
        </div>
        <div>
          <Label htmlFor="es-cat">{t("meta.category")}</Label>
          <Select id="es-cat" value={v.category} onChange={(ev) => set("category", ev.target.value)}>
            {CATEGORY_SLUGS.map((x) => <option key={x} value={x}>{categoryName(x)}</option>)}
          </Select>
        </div>
        <div>
          <Label htmlFor="es-scope">{t("meta.scope")}</Label>
          <Select id="es-scope" value={v.scope} onChange={(ev) => set("scope", ev.target.value)}>
            {SCOPES.map((x) => <option key={x} value={x}>{e(`scope.${x}`)}</option>)}
          </Select>
        </div>
        <div>
          <Label htmlFor="es-auth">{t("meta.authority")}</Label>
          <Select id="es-auth" value={v.authority_type} onChange={(ev) => set("authority_type", ev.target.value)}>
            {AUTHORITY_TYPES.map((x) => <option key={x} value={x}>{e(`authority.${x}`)}</option>)}
          </Select>
        </div>
        <div>
          <Label htmlFor="es-lang">{t("meta.language")}</Label>
          <Select id="es-lang" value={v.language} onChange={(ev) => set("language", ev.target.value)}>
            {LOCALES.map((x) => <option key={x} value={x}>{LOCALE_LABELS[x]}</option>)}
          </Select>
        </div>
        <div>
          <Label htmlFor="es-stale">{t("staleAfterDays")}</Label>
          <Input id="es-stale" type="number" min={1} max={3650} value={v.stale_after_days} placeholder={t("categoryDefault")} onChange={(ev) => set("stale_after_days", ev.target.value)} />
        </div>
        {fetchable && (
          <div>
            <Label htmlFor="es-sync">{t("syncSchedule")}</Label>
            <Select id="es-sync" value={v.sync_frequency} onChange={(ev) => set("sync_frequency", ev.target.value)}>
              {SYNC_FREQUENCIES.map((x) => <option key={x} value={x}>{e(`sync.${x}`)}</option>)}
            </Select>
            <p className="mt-1 text-xs text-muted-foreground">{t("syncHint")}</p>
          </div>
        )}
        {source.source_type === "sch_board" && (
          <>
            <div>
              <Label htmlFor="es-items">{t("boardMaxItems")}</Label>
              <Input id="es-items" type="number" min={1} max={30} value={v.max_items} onChange={(ev) => set("max_items", ev.target.value)} />
            </div>
            <div>
              <Label htmlFor="es-pages">{t("boardMaxPages")}</Label>
              <Input id="es-pages" type="number" min={1} max={5} value={v.max_pages} onChange={(ev) => set("max_pages", ev.target.value)} />
            </div>
          </>
        )}
      </div>
      {action.error && <Alert variant="destructive"><AlertDescription>{errorMessage(action.error)}</AlertDescription></Alert>}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>{c("close")}</Button>
        <Button type="submit" disabled={action.busy}>{action.busy ? c("saving") : t("save")}</Button>
      </DialogFooter>
    </form>
  );
}
