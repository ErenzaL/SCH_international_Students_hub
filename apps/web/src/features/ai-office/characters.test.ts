import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  CHARACTER_HEIGHT, CHARACTERS, FOOT_RADIUS, FURNITURE, footprint, STAGE, SUPPORTERS, ZONES, characterWidth,
  type Point, type Rect,
} from "@/features/ai-office/characters";
import { LOCALES } from "@/lib/constants";

/** Does the segment a-b come within `r` of the rectangle? (sampled densely; routes are short) */
function hits(a: Point, b: Point, rect: Rect, r: number): boolean {
  const steps = Math.max(2, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / 2));
  for (let i = 0; i <= steps; i++) {
    const x = a.x + ((b.x - a.x) * i) / steps;
    const y = a.y + ((b.y - a.y) * i) / steps;
    const cx = Math.max(rect.x, Math.min(x, rect.x + rect.w));
    const cy = Math.max(rect.y, Math.min(y, rect.y + rect.h));
    if (Math.hypot(x - cx, y - cy) < r) return true;
  }
  return false;
}

const segments = (pts: Point[]) => pts.slice(1).map((p, i) => [pts[i], p] as const);

describe("AI Office scene configuration", () => {
  it("uses real, distinct character files that exist (copied unchanged from assets/characters)", () => {
    const dir = path.resolve(__dirname, "../../../public/office/characters");
    for (const c of CHARACTERS) {
      const file = path.join(dir, c.file);
      expect(fs.existsSync(file), c.file).toBe(true);
      const png = fs.readFileSync(file);
      // the configured natural size is the image's real size (so the aspect ratio is preserved exactly)
      expect([png.readUInt32BE(16), png.readUInt32BE(20)], c.file).toEqual([c.size.w, c.size.h]);
    }
    expect(new Set(CHARACTERS.map((c) => c.id)).size).toBe(CHARACTERS.length);
    expect(new Set(CHARACTERS.map((c) => c.file)).size).toBe(CHARACTERS.length);
  });

  it("has one language supporter per site language", () => {
    expect(SUPPORTERS.map((c) => c.language).sort()).toEqual([...LOCALES].sort());
  });

  it("starts every route at the character's home and keeps every point inside the floor of the scene", () => {
    for (const c of CHARACTERS) {
      if (c.route.length) expect(c.route[0], c.id).toEqual(c.home);
      for (const p of [c.home, ...c.route]) {
        const w = characterWidth(c);
        expect(p.x - w / 2, c.id).toBeGreaterThanOrEqual(0);
        expect(p.x + w / 2, c.id).toBeLessThanOrEqual(STAGE.w);
        expect(p.y, c.id).toBeGreaterThan(STAGE.wall + 40);            // feet on the floor, not the wall
        expect(p.y, c.id).toBeLessThanOrEqual(STAGE.h - 8);
        expect(p.y - CHARACTER_HEIGHT, c.id).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it("never walks through furniture (every route segment keeps clear of every footprint)", () => {
    const problems: string[] = [];
    for (const c of CHARACTERS) {
      const pts = c.route.length ? c.route : [c.home];
      for (const f of FURNITURE) {
        const fp = footprint(f);
        if (pts.length === 1 && hits(pts[0], pts[0], fp, FOOT_RADIUS)) problems.push(`${c.id} home in ${f.id}`);
        for (const [a, b] of segments(pts)) {
          if (hits(a, b, fp, FOOT_RADIUS)) problems.push(`${c.id} ${JSON.stringify(a)}->${JSON.stringify(b)} crosses ${f.id}`);
        }
      }
    }
    expect(problems).toEqual([]);
  });

  it("gives every desk worker a desk that exists, in their own zone", () => {
    for (const c of CHARACTERS.filter((x) => x.desk)) {
      const d = FURNITURE.find((f) => f.id === c.desk);
      expect(d, c.id).toBeDefined();
      const z = ZONES.find((zone) => zone.id === c.zone)!;
      expect(d!.x >= z.x && d!.x + d!.w <= z.x + z.w, `${c.id} desk outside ${z.id}`).toBe(true);
    }
  });

  it("keeps furniture inside the scene", () => {
    for (const f of FURNITURE) {
      expect(f.x >= 0 && f.y >= 0 && f.x + f.w <= STAGE.w && f.y + f.h <= STAGE.h, f.id).toBe(true);
    }
  });
});
