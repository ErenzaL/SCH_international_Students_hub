"use client";

/**
 * /ai-office - the SCH AI Support Office: a full-screen illustrated office whose characters open the Hub's existing
 * assistant and desk tools. Frontend only: every answer and list comes from the existing backend APIs.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowLeft, CircleHelp, Users } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { useAgentDirectory } from "@/features/ai-office/agent-api";
import { CHARACTERS, INTERACTIVE, ZONES } from "@/features/ai-office/characters";
import { HelpContent, OfficePanel, Portrait } from "@/features/ai-office/office-panel";
import { OfficeScene, type SceneHandle } from "@/features/ai-office/office-scene";
import { SUPPORTER_LINES } from "@/features/ai-office/supporter-lines";
import { useOfficeLabels } from "@/features/ai-office/use-office-labels";
import { cn } from "@/lib/utils";

const BUBBLE_MS = 4500;

export function AiOffice() {
  const t = useTranslations("office");
  const labels = useOfficeLabels();
  const [selected, setSelected] = useState<string | null>(null);
  const [minimized, setMinimized] = useState(false);
  const [bubble, setBubble] = useState<{ id: string; text: string } | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const scene = useRef<SceneHandle | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const bubbleTimer = useRef<number | null>(null);
  const directory = useAgentDirectory();     // backend-owned agent states (working / waiting / ...)

  const onReady = useCallback((h: SceneHandle) => {
    scene.current = h;
  }, []);

  const greeting = useCallback((id: string) => {
    const c = CHARACTERS.find((x) => x.id === id)!;
    return c.role === "supporter" && c.language ? SUPPORTER_LINES[c.language].greeting : t(`greetings.${c.role}`);
  }, [t]);

  const select = useCallback((id: string, el?: HTMLElement | null) => {
    setSelected((prev) => {
      if (prev && prev !== id) scene.current?.release(prev);
      return id;
    });
    scene.current?.hold(id);
    opener.current = el ?? document.querySelector<HTMLElement>(`[data-testid="character-${id}"]`);
    setMinimized(false);
    setMenuOpen(false);
    setBubble({ id, text: greeting(id) });
    if (bubbleTimer.current) window.clearTimeout(bubbleTimer.current);
    bubbleTimer.current = window.setTimeout(() => setBubble(null), BUBBLE_MS);
  }, [greeting]);

  const close = useCallback(() => {
    setSelected((prev) => {
      if (prev) scene.current?.release(prev);
      return null;
    });
    setBubble(null);
    opener.current?.focus();          // back to the character that was opened
  }, []);

  useEffect(() => () => {
    if (bubbleTimer.current) window.clearTimeout(bubbleTimer.current);
  }, []);

  // deep link: /ai-office?desk=visa opens that character
  useEffect(() => {
    const id = new URL(window.location.href).searchParams.get("desk");
    if (id && INTERACTIVE.some((c) => c.id === id)) {
      const timer = window.setTimeout(() => select(id), 0);
      return () => window.clearTimeout(timer);
    }
  }, [select]);

  const current = selected ? CHARACTERS.find((c) => c.id === selected) ?? null : null;

  return (
    <div className="fixed inset-0 z-30 flex flex-col bg-[#FBF3E6]" data-testid="ai-office">
      <h1 className="sr-only">{t("title")}</h1>
      <div className={cn("pointer-events-none absolute inset-x-0 top-0 z-[35] flex flex-wrap items-start justify-between gap-2 p-2 pt-[max(0.5rem,env(safe-area-inset-top))] sm:p-3",
        current && !minimized && "md:pr-[452px]")}>
        <div className="pointer-events-auto flex items-center gap-2">
          <Link href="/" data-testid="back-to-hub"
            className="inline-flex h-10 items-center gap-1.5 rounded-full bg-white/95 px-3.5 text-sm font-semibold text-[#3D4B5C] shadow-md ring-1 ring-black/5 hover:bg-white">
            <ArrowLeft className="size-4" aria-hidden /> {t("backToHub")}
          </Link>
          <span className="hidden h-10 items-center rounded-full bg-[#3D6A8C] px-4 text-sm font-bold text-white shadow-md md:inline-flex">
            {t("title")}
          </span>
        </div>
        <div className="pointer-events-auto flex items-center gap-2">
          <div className="rounded-full bg-white/95 shadow-md ring-1 ring-black/5 [&_select]:h-10 [&_select]:rounded-full [&_select]:border-0">
            <LanguageSwitcher />
          </div>
          <button type="button" onClick={() => setMenuOpen(true)} data-testid="people-menu-button"
            className="inline-flex h-10 items-center gap-1.5 rounded-full bg-white/95 px-3.5 text-sm font-semibold text-[#3D4B5C] shadow-md ring-1 ring-black/5 hover:bg-white">
            <Users className="size-4" aria-hidden /> <span className="hidden sm:inline">{t("people")}</span>
            <span className="sr-only sm:hidden">{t("people")}</span>
          </button>
          <button type="button" onClick={() => setHelpOpen(true)} aria-label={t("help")} data-testid="help-button"
            className="inline-flex size-10 items-center justify-center rounded-full bg-white/95 text-[#3D4B5C] shadow-md ring-1 ring-black/5 hover:bg-white">
            <CircleHelp className="size-5" aria-hidden />
          </button>
        </div>
      </div>

      {/* with a conversation open on desktop the office re-fits beside the panel: everyone stays visible and clickable */}
      <div className={cn("min-h-0 flex-1 transition-[padding] duration-300", current && !minimized && "md:pr-[440px]")}
        data-testid="office-area">
        <OfficeScene selectedId={selected} bubble={bubble} onSelect={(id, el) => select(id, el)} onReady={onReady}
          states={directory.agents ? Object.fromEntries(directory.agents.map((a) => [a.character_id, a.state])) : undefined} />
      </div>

      {current && (
        <OfficePanel key={current.id} c={current} minimized={minimized} onClose={close}
          onMinimize={() => setMinimized(true)} onRestore={() => setMinimized(false)} onSelect={(id) => select(id)}
          agent={directory.byCharacter(current.id)} agents={directory.agents} agentsSignedIn={directory.signedIn}
          agentsAdmin={directory.isAdmin}
          onAgentsChanged={() => void directory.refresh()} />
      )}

      <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
        <DialogContent closeLabel={t("close")}>
          <DialogTitle>{t("helpDialog.title")}</DialogTitle>
          <DialogDescription className="sr-only">{t("helpDialog.intro")}</DialogDescription>
          <div className="text-sm"><HelpContent /></div>
        </DialogContent>
      </Dialog>

      <Dialog open={menuOpen} onOpenChange={setMenuOpen}>
        <DialogContent closeLabel={t("close")} className="max-w-2xl">
          <DialogTitle>{t("peopleTitle")}</DialogTitle>
          <DialogDescription>{t("peopleIntro")}</DialogDescription>
          <div className="space-y-4" data-testid="people-menu">
            {ZONES.filter((z) => INTERACTIVE.some((c) => c.zone === z.id)).map((z) => (
              <div key={z.id}>
                <p className="mb-1 text-xs font-bold tracking-wide text-muted-foreground">
                  {z.id === "meeting" ? t("zones.meeting") : labels.zone(z.id)}
                </p>
                <ul className="grid gap-1 sm:grid-cols-2">
                  {INTERACTIVE.filter((c) => c.zone === z.id).map((c) => (
                    <li key={c.id}>
                      <button type="button" onClick={() => select(c.id)} data-testid={`menu-${c.id}`}
                        className="flex w-full items-center gap-3 rounded-xl px-2 py-1.5 text-left hover:bg-muted">
                        <Portrait c={c} size={40} />
                        <span className="min-w-0">
                          <span className="block font-medium">{c.name}</span>
                          <span className="block truncate text-xs text-muted-foreground">{labels.roleTitle(c)}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
