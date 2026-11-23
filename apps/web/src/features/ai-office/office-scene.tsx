"use client";

/**
 * The illustrated office: one 1600 x 1000 stage, scaled to the viewport. Wide screens see the whole office; narrow /
 * portrait screens keep a readable scale and scroll sideways (starting at reception). Furniture and characters are
 * depth-sorted by their floor line. Characters are real buttons (keyboard and screen-reader accessible); visiting
 * students are scenery. Movement is driven by one shared `OfficeAnimator`.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Backdrop } from "@/features/ai-office/backdrop";
import {
  CHARACTER_HEIGHT, CHARACTERS, FURNITURE, STAGE, ZONES, characterWidth, type OfficeCharacter,
} from "@/features/ai-office/characters";
import type { AgentState } from "@/features/ai-office/agent-api";
import { StateDot } from "@/features/ai-office/agent-work";
import { FurnitureArt } from "@/features/ai-office/furniture";
import { OfficeAnimator, placement } from "@/features/ai-office/movement";
import { useOfficeLabels } from "@/features/ai-office/use-office-labels";
import { cn } from "@/lib/utils";

const WALL_ZONES = new Set(["supporters", "visa", "academic", "opportunities"]);

export interface SceneHandle {
  hold: (id: string) => void;
  release: (id: string) => void;
}

export function OfficeScene({ selectedId, bubble, onSelect, onReady, states }: {
  selectedId: string | null;
  /** Phase 2: each agent's state from the backend, by character id (idle characters show no badge) */
  states?: Record<string, AgentState>;
  /** speech bubble shown above a character (greeting after a click) */
  bubble: { id: string; text: string } | null;
  onSelect: (id: string, el: HTMLButtonElement) => void;
  onReady?: (handle: SceneHandle) => void;
}) {
  const t = useTranslations("office");
  const labels = useOfficeLabels();
  const box = useRef<HTMLDivElement>(null);
  const animator = useRef<OfficeAnimator | null>(null);
  const [view, setView] = useState({ scale: 0, pan: false });

  // fit the stage: whole office on wide screens, readable + horizontally scrollable on narrow ones
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const fit = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (!w || !h) return;
      const whole = Math.min(w / STAGE.w, h / STAGE.h);
      const pan = whole < 0.62 && w < 1100;
      const scale = pan ? Math.max(h / STAGE.h, w / STAGE.w) : whole;
      setView((v) => (v.scale === scale && v.pan === pan ? v : { scale, pan }));
    };
    fit();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(fit) : null;
    ro?.observe(el);
    window.addEventListener("resize", fit);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", fit);
    };
  }, []);

  // start the narrow-screen view at the reception desk
  useEffect(() => {
    const el = box.current;
    if (el && view.pan) el.scrollLeft = Math.max(0, 690 * view.scale - el.clientWidth / 2);
  }, [view.pan, view.scale]);

  // one shared animation loop; reduced motion = everyone stays at their spot
  useEffect(() => {
    const a = new OfficeAnimator(CHARACTERS);
    animator.current = a;
    for (const el of box.current?.querySelectorAll<HTMLElement>("[data-actor]") ?? []) a.attach(el.dataset.actor!, el);
    const mq = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    a.setReducedMotion(Boolean(mq?.matches));
    const onMotion = (e: MediaQueryListEvent) => a.setReducedMotion(e.matches);
    mq?.addEventListener?.("change", onMotion);
    a.start();
    onReady?.({ hold: (id) => a.hold(id), release: (id) => a.release(id) });
    return () => {
      mq?.removeEventListener?.("change", onMotion);
      a.destroy();
      animator.current = null;
    };
  }, [onReady]);

  // a working agent stays at its desk (the backend owns the state; the animator only stops new walks)
  useEffect(() => {
    const a = animator.current;
    if (!a) return;
    for (const c of CHARACTERS) a.setBusy(c.id, states?.[c.id] === "working");
  }, [states]);

  const ready = view.scale > 0;
  return (
    <div ref={box} data-testid="office-viewport"
      className={cn("relative h-full w-full", view.pan ? "overflow-x-auto overflow-y-hidden" : "overflow-hidden")}>
      <div className={cn("relative", !view.pan && "mx-auto")}
        style={{ width: STAGE.w * (view.scale || 1), height: STAGE.h * (view.scale || 1),
          top: view.pan ? 0 : `max(0px, calc((100% - ${STAGE.h * view.scale}px) / 2))`, visibility: ready ? "visible" : "hidden" }}>
        <div role="group" aria-label={t("sceneLabel")} data-testid="office-stage"
          className="absolute left-0 top-0 origin-top-left select-none"
          style={{ width: STAGE.w, height: STAGE.h, transform: `scale(${view.scale || 1})` }}>
          <Backdrop />
          {ZONES.filter((z) => z.sign).map((z) => (
            <ZoneSign key={z.id} label={labels.zone(z.id)} x={z.sign!.x} y={z.sign!.y} hanging={WALL_ZONES.has(z.id)} />
          ))}
          {FURNITURE.map((f) => (
            <div key={f.id} className="pointer-events-none absolute" data-furniture={f.id}
              style={{ left: f.x, top: f.y, width: f.w, height: f.h, zIndex: f.y + f.h }}>
              <FurnitureArt item={f} />
              {f.kind === "counter" && (
                <span className="absolute inset-x-5 bottom-[21px] truncate text-center text-[15px] font-extrabold tracking-wide text-[#3D6A8C]">
                  {labels.zone("reception")}
                </span>
              )}
            </div>
          ))}
          {CHARACTERS.map((c) => (
            <Actor key={c.id} c={c} selected={selectedId === c.id} bubble={bubble?.id === c.id ? bubble.text : null}
              onSelect={onSelect} state={states?.[c.id]} />
          ))}
        </div>
      </div>
    </div>
  );
}

function ZoneSign({ label, x, y, hanging }: { label: string; x: number; y: number; hanging: boolean }) {
  return (
    <div className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2" style={{ left: x, top: y, zIndex: 5 }}>
      {hanging && <div className="mx-auto h-5 w-24 border-x-2 border-t-2 border-[#C9A57B]/70" aria-hidden />}
      <div className={cn("max-w-[300px] whitespace-nowrap rounded-xl border-2 border-white px-3.5 py-1 text-center text-[15px] font-extrabold tracking-wider text-[#4B5D73] shadow-[0_3px_0_rgba(91,70,54,0.12)]",
        hanging ? "bg-[#FFFDF7]" : "bg-white/85")}>
        {label}
      </div>
    </div>
  );
}

function Actor({ c, selected, bubble, onSelect, state }: {
  c: OfficeCharacter; selected: boolean; bubble: string | null;
  onSelect: (id: string, el: HTMLButtonElement) => void;
  state?: AgentState;
}) {
  const t = useTranslations("office");
  const tState = useTranslations("office.agent.states");
  const labels = useOfficeLabels();
  const w = characterWidth(c);
  const start = placement(c, c.home);
  const delay = `-${(c.id.length * 0.37) % 3}s`;       // de-synchronized breathing, same on server and client
  const style = { width: w, height: CHARACTER_HEIGHT, transform: `translate3d(${start.left}px, ${start.top}px, 0)`,
    zIndex: c.home.y };
  const img = (
    // eslint-disable-next-line @next/next/no-img-element -- original transparent PNG, shown at its own aspect ratio
    <img src={`/office/characters/${c.file}`} alt="" width={w} height={CHARACTER_HEIGHT} draggable={false}
      decoding="async" className="pointer-events-none block h-full w-full object-contain drop-shadow-[0_3px_2px_rgba(91,70,54,0.18)]" />
  );
  if (!c.interactive) {
    return (
      <div data-actor={c.id} data-phase="idle" aria-hidden className="office-actor pointer-events-none absolute left-0 top-0" style={style}>
        <span className="office-bob block h-full w-full" style={{ animationDelay: delay }}>{img}</span>
      </div>
    );
  }
  const role = labels.roleTitle(c);
  const busy = state && state !== "idle" ? ` (${tState(state)})` : "";
  // bubbles / tooltips open towards the middle of the office for people standing near an edge (never clipped)
  const anchor = c.home.x < 300 ? "left-0" : c.home.x > STAGE.w - 300 ? "right-0" : "left-1/2 -translate-x-1/2";
  const tail = c.home.x < 300 ? "left-8" : c.home.x > STAGE.w - 300 ? "right-8" : "left-1/2 -translate-x-1/2";
  return (
    <div data-actor={c.id} data-phase="idle" data-state={state ?? "idle"} className="office-actor absolute left-0 top-0" style={style}>
      {state && state !== "idle" && (
        <span aria-hidden className="pointer-events-none absolute right-1 top-1 z-[1]" data-testid={`state-${c.id}`}>
          <StateDot state={state} />
        </span>
      )}
      <button type="button" data-testid={`character-${c.id}`} aria-label={t("talkTo", { name: c.name, role }) + busy}
        aria-pressed={selected} onClick={(e) => onSelect(c.id, e.currentTarget)}
        className="group relative block h-full w-full cursor-pointer rounded-2xl outline-none focus-visible:ring-4 focus-visible:ring-[#7FB7E6]">
        <span className={cn("office-bob block h-full w-full transition-[filter] duration-200",
          "group-hover:brightness-105 group-hover:drop-shadow-[0_0_10px_rgba(255,255,255,0.95)]",
          selected && "drop-shadow-[0_0_12px_rgba(127,183,230,0.95)]")} style={{ animationDelay: delay }}>
          {img}
        </span>
        <span className={cn("absolute left-1/2 top-full mt-0.5 -translate-x-1/2 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[13px] font-bold shadow-sm",
          selected ? "bg-[#3D6A8C] text-white" : "bg-white/95 text-[#4B5D73]")}>
          {c.name}{c.language ? <span className="ml-1 font-semibold opacity-70">· {labels.languageShort(c.language)}</span> : null}
        </span>
        {!bubble && (
          <span role="tooltip" className={cn("pointer-events-none absolute bottom-full mb-2 hidden whitespace-nowrap", anchor, " rounded-xl bg-white px-3 py-1.5 text-left text-[13px] shadow-lg ring-1 ring-black/5 group-hover:block group-focus-visible:block")}>
            <span className="block font-bold text-[#3D4B5C]">{c.name} · {role}</span>
            <span className="block text-[#6B7A8C]">{t("clickToTalk")}</span>
          </span>
        )}
      </button>
      {bubble && (
        <div role="status" className={cn("office-pop absolute bottom-full mb-2 w-max max-w-[260px] rounded-2xl bg-white px-3.5 py-2 text-[14px] font-medium leading-snug text-[#3D4B5C] shadow-lg ring-1 ring-black/5", anchor)}
          data-testid="speech-bubble">
          {bubble}
          <span className={cn("absolute top-full -mt-1 size-3 rotate-45 bg-white", tail)} aria-hidden />
        </div>
      )}
    </div>
  );
}
