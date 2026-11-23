import { describe, expect, it, vi } from "vitest";
import { CHARACTERS, FOOT_RADIUS, FURNITURE, footprint, type OfficeCharacter } from "@/features/ai-office/characters";
import { OfficeAnimator, loop, seeded } from "@/features/ai-office/movement";

function fakeClock() {
  const frames: FrameRequestCallback[] = [];
  let id = 0;
  const cancelled = new Set<number>();
  const raf = vi.fn((cb: FrameRequestCallback) => { frames.push(cb); return ++id; });
  const caf = vi.fn((n: number) => { cancelled.add(n); });
  return { raf, caf, frames, cancelled };
}

function fakeDoc(hidden = false) {
  const listeners = new Map<string, EventListener>();
  return {
    visibilityState: hidden ? "hidden" : "visible",
    addEventListener: vi.fn((t: string, l: EventListener) => listeners.set(t, l)),
    removeEventListener: vi.fn((t: string) => listeners.delete(t)),
    listeners,
  } as unknown as Document & { listeners: Map<string, EventListener>; visibilityState: string };
}

const walker: OfficeCharacter = CHARACTERS.find((c) => c.id === "guide-bot")!;

describe("route helpers", () => {
  it("visits waypoints forwards and back", () => {
    const p = (x: number) => ({ x, y: 0 });
    expect(loop([p(1), p(2), p(3)])).toEqual([p(1), p(2), p(3), p(2)]);
    expect(loop([p(1)])).toEqual([p(1)]);
  });

  it("gives each character its own deterministic random sequence", () => {
    const a = seeded("a");
    const b = seeded("b");
    expect([a(), a()]).toEqual([seeded("a")(), (() => { const r = seeded("a"); r(); return r(); })()]);
    expect(a()).not.toEqual(b());
  });
});

describe("OfficeAnimator", () => {
  it("moves characters only along their routes, so never through furniture", () => {
    const anim = new OfficeAnimator(CHARACTERS, { raf: vi.fn(), caf: vi.fn(), doc: fakeDoc() });
    const moved = new Set<string>();
    const violations = new Set<string>();
    const rects = FURNITURE.map((f) => [f.id, footprint(f)] as const);
    for (let i = 0; i < 3000; i++) {                       // ~5 minutes of simulated time
      anim.step(0.1);
      for (const c of CHARACTERS) {
        const p = anim.position(c.id)!;
        if (p.x !== c.home.x || p.y !== c.home.y) moved.add(c.id);
        for (const [id, r] of rects) {
          const cx = Math.max(r.x, Math.min(p.x, r.x + r.w));
          const cy = Math.max(r.y, Math.min(p.y, r.y + r.h));
          if (Math.hypot(p.x - cx, p.y - cy) < FOOT_RADIUS - 0.01) violations.add(`${c.id} in ${id}`);
        }
      }
    }
    expect([...violations]).toEqual([]);
    // everyone with a route actually walks
    expect([...moved].sort()).toEqual(CHARACTERS.filter((c) => c.route.length > 1).map((c) => c.id).sort());
  });

  it("stops a clicked character until it is released", () => {
    const anim = new OfficeAnimator([walker], { raf: vi.fn(), caf: vi.fn(), doc: fakeDoc() });
    for (let i = 0; i < 400; i++) anim.step(0.05);
    anim.hold(walker.id);
    const at = anim.position(walker.id);
    for (let i = 0; i < 400; i++) anim.step(0.05);
    expect(anim.position(walker.id)).toEqual(at);
    expect(anim.phase(walker.id)).toBe("held");
    anim.release(walker.id);
    let walked = false;
    for (let i = 0; i < 400; i++) {
      anim.step(0.05);
      const p = anim.position(walker.id)!;
      walked ||= p.x !== at!.x || p.y !== at!.y;
    }
    expect(walked).toBe(true);
  });

  it("writes position and depth to the element without React", () => {
    const anim = new OfficeAnimator([walker], { raf: vi.fn(), caf: vi.fn(), doc: fakeDoc() });
    const el = document.createElement("div");
    anim.attach(walker.id, el);
    expect(el.style.transform).toMatch(/^translate3d\(/);
    expect(el.style.zIndex).toBe(String(walker.home.y));
    expect(el.dataset.phase).toBe("idle");
  });

  it("does not animate at all with reduced motion", () => {
    const clock = fakeClock();
    const anim = new OfficeAnimator(CHARACTERS, { raf: clock.raf, caf: clock.caf, doc: fakeDoc() });
    anim.setReducedMotion(true);
    anim.start();
    expect(clock.raf).not.toHaveBeenCalled();
    for (const c of CHARACTERS) expect(anim.position(c.id)).toEqual(c.home);
    anim.setReducedMotion(false);
    expect(clock.raf).toHaveBeenCalledTimes(1);
    anim.destroy();
  });

  it("pauses while the tab is hidden and resumes when it is visible again", () => {
    const clock = fakeClock();
    const doc = fakeDoc();
    const anim = new OfficeAnimator(CHARACTERS, { raf: clock.raf, caf: clock.caf, doc });
    anim.start();
    expect(clock.raf).toHaveBeenCalledTimes(1);
    doc.visibilityState = "hidden";
    doc.listeners.get("visibilitychange")!(new Event("visibilitychange"));
    expect(clock.caf).toHaveBeenCalledWith(1);
    doc.visibilityState = "visible";
    doc.listeners.get("visibilitychange")!(new Event("visibilitychange"));
    expect(clock.raf).toHaveBeenCalledTimes(2);
    anim.destroy();
  });

  it("runs ONE loop for all characters and cleans everything up on destroy", () => {
    const clock = fakeClock();
    const doc = fakeDoc();
    const anim = new OfficeAnimator(CHARACTERS, { raf: clock.raf, caf: clock.caf, doc, now: () => 0 });
    anim.start();
    anim.start();                                          // starting twice never creates a second loop
    expect(clock.raf).toHaveBeenCalledTimes(1);
    clock.frames.shift()!(16);
    expect(clock.raf).toHaveBeenCalledTimes(2);            // one frame schedules exactly one next frame
    anim.destroy();
    expect(clock.caf).toHaveBeenCalled();
    expect(doc.removeEventListener).toHaveBeenCalledWith("visibilitychange", expect.any(Function));
    expect(doc.listeners.size).toBe(0);
    expect(anim.isRunning).toBe(false);
  });

  it("switches walking off on a struggling device (slow frames)", () => {
    const clock = fakeClock();
    let t = 0;
    const anim = new OfficeAnimator([walker], { raf: clock.raf, caf: clock.caf, doc: fakeDoc(), now: () => t });
    anim.start();
    for (let i = 0; i < 95; i++) {
      t += 80;                                             // 12 fps
      clock.frames.shift()!(t);
    }
    expect(anim.degraded).toBe(true);
    anim.destroy();
  });
});
