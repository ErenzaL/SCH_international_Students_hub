/**
 * One shared animation loop for every character in the AI Office (no timer per character, no physics).
 *
 * Each character walks its predefined route (waypoints visited forwards then backwards), pausing for a random idle
 * time at each waypoint. Routes are checked against furniture footprints in tests, so following them never walks
 * through furniture. Positions are written straight to the DOM (transform + z-index): React does not re-render per
 * frame. The loop pauses when the tab is hidden, never runs with reduced motion, slows characters down to "idle only"
 * when frames get slow, and is fully removed by `destroy()`.
 */
import { CHARACTER_HEIGHT, characterWidth, type OfficeCharacter, type Point } from "@/features/ai-office/characters";

export const WALK_SPEED = 52;            // stage units per second
const IDLE_MIN = 2.2;                    // seconds at a waypoint
const IDLE_MAX = 6.5;
const PERSONAL_SPACE = 34;               // walkers wait instead of walking into someone
const MAX_WAIT = 1.6;                    // ... but not longer than this
const SLOW_FRAME_MS = 48;                // average frame time that switches walking off
/** transparent margin around every character image (px of the original image) */
export const IMAGE_PADDING = 20;

type Phase = "idle" | "walk" | "held";

interface Actor {
  c: OfficeCharacter;
  el: HTMLElement | null;
  pos: Point;
  path: Point[];          // forward + backward waypoint loop
  leg: number;            // index of the current target in `path`
  phase: Phase;
  timer: number;          // seconds left idling / waiting
  waited: number;
  rand: () => number;
}

/** Deterministic per-character random numbers (no Math.random: stable tests, no synchronized movement). */
export function seeded(id: string): () => number {
  let h = 2166136261;
  for (const ch of id) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  let a = h >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Waypoints forwards and back again (r0 r1 r2 r1 | r0 ...), without repeating the turning points. */
export function loop(route: Point[]): Point[] {
  if (route.length < 2) return route.slice();
  return [...route, ...route.slice(1, -1).reverse()];
}

/** Top-left corner (stage units) that puts the character's feet on `p`. */
export function placement(c: OfficeCharacter, p: Point): { left: number; top: number } {
  const w = characterWidth(c);
  const pad = (IMAGE_PADDING * CHARACTER_HEIGHT) / c.size.h;
  return { left: p.x - w / 2, top: p.y - CHARACTER_HEIGHT + pad };
}

export interface AnimatorOptions {
  raf?: (cb: FrameRequestCallback) => number;
  caf?: (id: number) => void;
  now?: () => number;
  doc?: Document;
}

export class OfficeAnimator {
  private actors = new Map<string, Actor>();
  private frame: number | null = null;
  private last = 0;
  private running = false;
  private reduced = false;
  private hidden = false;
  private frameTimes: number[] = [];
  degraded = false;
  private readonly raf: (cb: FrameRequestCallback) => number;
  private readonly caf: (id: number) => void;
  private readonly now: () => number;
  private readonly doc: Document | null;
  private readonly onVisibility = () => {
    this.hidden = this.doc?.visibilityState === "hidden";
    if (this.hidden) this.halt();
    else this.kick();
  };

  constructor(chars: OfficeCharacter[], opts: AnimatorOptions = {}) {
    this.raf = opts.raf ?? ((cb) => requestAnimationFrame(cb));
    this.caf = opts.caf ?? ((id) => cancelAnimationFrame(id));
    this.now = opts.now ?? (() => performance.now());
    this.doc = opts.doc ?? (typeof document !== "undefined" ? document : null);
    for (const c of chars) {
      const rand = seeded(c.id);
      const path = loop(c.route.length ? c.route : [c.home]);
      // desynchronized start: everyone begins idle for a different time
      this.actors.set(c.id, { c, el: null, pos: { ...c.home }, path, leg: 0, phase: "idle",
        timer: 0.6 + rand() * IDLE_MAX, waited: 0, rand });
    }
    this.doc?.addEventListener("visibilitychange", this.onVisibility);
    this.hidden = this.doc?.visibilityState === "hidden";
  }

  attach(id: string, el: HTMLElement | null): void {
    const a = this.actors.get(id);
    if (!a) return;
    a.el = el;
    if (el) this.paint(a);
  }

  /** Reduced motion: everyone stands still at home, no loop at all. */
  setReducedMotion(reduced: boolean): void {
    this.reduced = reduced;
    if (reduced) {
      this.halt();
      for (const a of this.actors.values()) {
        a.pos = { ...a.c.home };
        a.leg = 0;
        a.phase = a.phase === "held" ? "held" : "idle";
        this.paint(a);
      }
    } else {
      this.kick();
    }
  }

  /** A character the student clicked: stops where it is (and faces the student) until released. */
  hold(id: string): void {
    const a = this.actors.get(id);
    if (!a) return;
    a.phase = "held";
    this.paint(a);
  }

  release(id: string): void {
    const a = this.actors.get(id);
    if (!a || a.phase !== "held") return;
    a.phase = "idle";
    a.timer = 1.5 + a.rand() * 2;
    this.paint(a);
  }

  position(id: string): Point | undefined {
    const a = this.actors.get(id);
    return a ? { ...a.pos } : undefined;
  }

  phase(id: string): Phase | undefined {
    return this.actors.get(id)?.phase;
  }

  get isRunning(): boolean {
    return this.running;
  }

  start(): void {
    this.running = true;
    this.kick();
  }

  destroy(): void {
    this.running = false;
    this.halt();
    this.doc?.removeEventListener("visibilitychange", this.onVisibility);
    for (const a of this.actors.values()) a.el = null;
  }

  private kick(): void {
    if (!this.running || this.reduced || this.hidden || this.frame !== null) return;
    this.last = this.now();
    this.frame = this.raf(this.tick);
  }

  private halt(): void {
    if (this.frame !== null) this.caf(this.frame);
    this.frame = null;
  }

  /** Advance every character by `dt` seconds (also used directly by tests). */
  step(dt: number): void {
    for (const a of this.actors.values()) {
      if (a.phase === "held") continue;
      if (a.phase === "idle") {
        a.timer -= dt;
        if (a.timer <= 0 && !this.degraded && a.path.length > 1) {
          a.leg = (a.leg + 1) % a.path.length;
          a.phase = "walk";
          a.waited = 0;
          this.paint(a);
        }
        continue;
      }
      const target = a.path[a.leg];
      const dx = target.x - a.pos.x;
      const dy = target.y - a.pos.y;
      const dist = Math.hypot(dx, dy);
      const move = WALK_SPEED * dt;
      if (dist <= move) {
        a.pos = { ...target };
        a.phase = "idle";
        a.timer = IDLE_MIN + a.rand() * (IDLE_MAX - IDLE_MIN);
        this.paint(a);
        continue;
      }
      const next = { x: a.pos.x + (dx / dist) * move, y: a.pos.y + (dy / dist) * move };
      if (a.waited < MAX_WAIT && this.crowded(a, next)) {
        a.waited += dt;           // someone is in the way: wait a moment
        continue;
      }
      a.pos = next;
      this.paint(a);
    }
  }

  private crowded(self: Actor, next: Point): boolean {
    for (const o of this.actors.values()) {
      if (o === self) continue;
      const before = Math.hypot(o.pos.x - self.pos.x, o.pos.y - self.pos.y);
      const after = Math.hypot(o.pos.x - next.x, o.pos.y - next.y);
      if (after < PERSONAL_SPACE && after < before) return true;
    }
    return false;
  }

  private readonly tick = (t: number) => {
    this.frame = null;
    const now = typeof t === "number" ? t : this.now();
    const ms = Math.max(0, now - this.last);
    this.last = now;
    this.frameTimes.push(ms);
    if (this.frameTimes.length > 90) this.frameTimes.shift();
    if (!this.degraded && this.frameTimes.length === 90) {
      const avg = this.frameTimes.reduce((s, x) => s + x, 0) / this.frameTimes.length;
      if (avg > SLOW_FRAME_MS) this.degraded = true;     // a struggling device: characters stay at their spots
    }
    this.step(Math.min(ms, 50) / 1000);
    this.kick();
  };

  private paint(a: Actor): void {
    const el = a.el;
    if (!el) return;
    const { left, top } = placement(a.c, a.pos);
    el.style.transform = `translate3d(${left.toFixed(1)}px, ${top.toFixed(1)}px, 0)`;
    el.style.zIndex = String(Math.round(a.pos.y));
    el.dataset.phase = a.phase;
  }
}
