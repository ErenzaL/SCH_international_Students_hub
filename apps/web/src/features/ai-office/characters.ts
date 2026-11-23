/**
 * AI Support Office - scene and character configuration (stage coordinates: 1600 x 1000, origin top-left).
 *
 * Positions are FEET points (bottom centre of a character). Furniture has a drawing box (x, y, w, h: the artwork) and
 * a floor footprint (`depth` above its base line) that characters never walk through: every route segment is
 * checked against the footprints in tests (`characters.test.ts`). Depth sorting: z = base line / feet y.
 *
 * Character art: the PNGs in the repository's assets/characters/ (copied unchanged to public/office/characters/ by
 * scripts/sync-office-characters.mjs). All are single, front-facing, transparent figures of similar proportions, so
 * they are shown at one height with their own aspect ratio, never cropped, stretched or mirrored.
 */
import type { LanguageCode } from "@/types/api";

export const STAGE = { w: 1600, h: 1000, wall: 250 } as const;
export const CHARACTER_HEIGHT = 124;            // stage units; width follows each image's aspect ratio
export const FOOT_RADIUS = 18;                  // clearance kept from furniture footprints

export interface Point { x: number; y: number }
export interface Rect { x: number; y: number; w: number; h: number }

export type ZoneId = "reception" | "supporters" | "visa" | "academic" | "opportunities" | "events" | "career"
  | "meeting" | "waiting";

export interface Zone extends Rect {
  id: ZoneId;
  /** floor colour (palette token) */
  tone: "cream" | "mint" | "sky" | "lavender" | "yellow" | "beige" | "peach";
  /** where the sign hangs (stage coordinates of its centre); undefined = no sign */
  sign?: Point;
}

export const ZONES: Zone[] = [
  { id: "supporters", x: 28, y: 276, w: 566, h: 340, tone: "mint", sign: { x: 311, y: 150 } },
  { id: "visa", x: 620, y: 276, w: 304, h: 250, tone: "sky", sign: { x: 772, y: 150 } },
  { id: "academic", x: 950, y: 276, w: 314, h: 250, tone: "lavender", sign: { x: 1107, y: 150 } },
  { id: "opportunities", x: 1290, y: 276, w: 282, h: 340, tone: "yellow", sign: { x: 1431, y: 150 } },
  { id: "meeting", x: 620, y: 552, w: 420, h: 170, tone: "beige" },
  { id: "events", x: 28, y: 650, w: 404, h: 322, tone: "peach", sign: { x: 230, y: 684 } },
  { id: "reception", x: 458, y: 756, w: 446, h: 216, tone: "cream" },   // its name is on the counter
  { id: "waiting", x: 924, y: 770, w: 200, h: 202, tone: "beige" },
  { id: "career", x: 1146, y: 650, w: 426, h: 322, tone: "sky", sign: { x: 1359, y: 684 } },
];

export type FurnitureKind = "desk" | "bookshelf" | "plant" | "plantSmall" | "board" | "counter" | "meetingTable"
  | "sofa" | "sideTable" | "cabinet" | "cooler" | "lamp";

export interface Furniture extends Rect {
  id: string;
  kind: FurnitureKind;
  /** floor footprint depth above the base line (y + h) */
  depth: number;
  /** desk accent colour / variation */
  accent?: "mint" | "sky" | "lavender" | "yellow" | "peach" | "beige";
}

const desk = (id: string, x: number, base: number, accent: Furniture["accent"]): Furniture =>
  ({ id, kind: "desk", x, y: base - 92, w: 124, h: 92, depth: 40, accent });

export const FURNITURE: Furniture[] = [
  // global supporters: two rows of workstations
  desk("desk-ko", 56, 402, "mint"), desk("desk-en", 246, 402, "mint"), desk("desk-id", 436, 402, "mint"),
  desk("desk-vi", 56, 562, "mint"), desk("desk-zh", 246, 562, "mint"),
  { id: "plant-sup", kind: "plant", x: 548, y: 470, w: 46, h: 90, depth: 20 },
  { id: "shelf-sup", kind: "bookshelf", x: 40, y: 168, w: 112, h: 132, depth: 28 },
  // visa & immigration
  desk("desk-visa", 664, 402, "sky"),
  { id: "cabinet-visa", kind: "cabinet", x: 846, y: 214, w: 64, h: 92, depth: 26 },
  // academic & TOPIK
  desk("desk-academic", 992, 402, "lavender"),
  { id: "shelf-academic", kind: "bookshelf", x: 1166, y: 168, w: 96, h: 132, depth: 28 },
  // scholarships & opportunities
  desk("desk-opportunities", 1322, 402, "yellow"),
  { id: "plant-opp", kind: "plantSmall", x: 1520, y: 322, w: 40, h: 62, depth: 16 },
  // meeting table in the middle
  { id: "meeting-table", kind: "meetingTable", x: 700, y: 560, w: 262, h: 96, depth: 62 },
  { id: "cooler", kind: "cooler", x: 1052, y: 540, w: 40, h: 96, depth: 22 },
  // events & campus life
  desk("desk-events", 66, 786, "peach"),
  { id: "board-events", kind: "board", x: 284, y: 680, w: 132, h: 96, depth: 14 },
  { id: "plant-events", kind: "plant", x: 36, y: 880, w: 46, h: 90, depth: 20 },
  // reception
  { id: "counter", kind: "counter", x: 486, y: 790, w: 236, h: 98, depth: 46 },
  { id: "plant-reception", kind: "plantSmall", x: 470, y: 900, w: 40, h: 62, depth: 16 },
  // waiting area
  { id: "sofa", kind: "sofa", x: 940, y: 836, w: 160, h: 70, depth: 40 },
  { id: "side-table", kind: "sideTable", x: 1104, y: 868, w: 30, h: 38, depth: 18 },
  { id: "lamp", kind: "lamp", x: 1100, y: 774, w: 34, h: 92, depth: 14 },
  // career & internships
  desk("desk-career", 1176, 786, "sky"),
  { id: "shelf-career", kind: "bookshelf", x: 1478, y: 656, w: 88, h: 110, depth: 28 },
  { id: "plant-career", kind: "plant", x: 1522, y: 880, w: 46, h: 90, depth: 20 },
];

/** Floor footprint of a piece of furniture (what characters must not walk through). */
export function footprint(f: Furniture): Rect {
  return { x: f.x, y: f.y + f.h - f.depth, w: f.w, h: f.depth };
}

export type CharacterRole = "reception" | "guide" | "supporter" | "supporterLead" | "visa" | "academic" | "topik"
  | "opportunities" | "events" | "career" | "visitor";

export interface OfficeCharacter {
  id: string;
  /** a proper name: never translated */
  name: string;
  /** file in assets/characters (and public/office/characters) */
  file: string;
  /** natural pixel size of the image (aspect ratio is preserved) */
  size: { w: number; h: number };
  role: CharacterRole;
  zone: ZoneId;
  /** conversation language for language supporters; desk agents answer in the site language */
  language?: LanguageCode;
  desk?: string;
  home: Point;
  /** waypoints visited in order and then in reverse (a back-and-forth route); empty = stays at home */
  route: Point[];
  /** visitors are scenery: not focusable, no conversation */
  interactive: boolean;
}

const C = (c: Omit<OfficeCharacter, "interactive"> & { interactive?: boolean }): OfficeCharacter =>
  ({ interactive: true, ...c });

export const CHARACTERS: OfficeCharacter[] = [
  C({ id: "reception", name: "Hana", file: "Agent_General_AI.png", size: { w: 254, h: 364 }, role: "reception",
    zone: "reception", home: { x: 762, y: 894 }, route: [{ x: 762, y: 894 }, { x: 750, y: 946 }] }),
  C({ id: "guide-bot", name: "Robo", file: "AI_General_Robot.png", size: { w: 267, h: 369 }, role: "guide",
    zone: "meeting", home: { x: 1000, y: 690 },
    route: [{ x: 1000, y: 690 }, { x: 1000, y: 704 }, { x: 664, y: 704 }, { x: 664, y: 572 }, { x: 990, y: 572 }] }),
  // language supporters: neutral staff artwork (they represent language services, not nationalities)
  C({ id: "supporter-ko", name: "Minji", file: "Staff_04_Glasses_Female.png", size: { w: 271, h: 354 }, role: "supporter",
    zone: "supporters", language: "ko", desk: "desk-ko", home: { x: 210, y: 426 },
    route: [{ x: 210, y: 426 }, { x: 210, y: 470 }, { x: 140, y: 470 }] }),
  C({ id: "supporter-en", name: "Alex", file: "Staff_07_Curly_Hair.png", size: { w: 271, h: 373 }, role: "supporter",
    zone: "supporters", language: "en", desk: "desk-en", home: { x: 400, y: 426 },
    route: [{ x: 400, y: 426 }, { x: 400, y: 474 }, { x: 330, y: 474 }] }),
  C({ id: "supporter-id", name: "Sari", file: "Staff_09_Long_Blue_Hair.png", size: { w: 290, h: 366 }, role: "supporter",
    zone: "supporters", language: "id", desk: "desk-id", home: { x: 586, y: 426 },
    route: [{ x: 586, y: 426 }, { x: 520, y: 466 }] }),
  C({ id: "supporter-vi", name: "Minh", file: "Staff_03_Glasses_Male.png", size: { w: 261, h: 366 }, role: "supporter",
    zone: "supporters", language: "vi", desk: "desk-vi", home: { x: 210, y: 586 },
    route: [{ x: 210, y: 586 }, { x: 210, y: 626 }, { x: 130, y: 626 }] }),
  C({ id: "supporter-zh", name: "Mei", file: "Staff_06_Ponytail.png", size: { w: 246, h: 376 }, role: "supporter",
    zone: "supporters", language: "zh-CN", desk: "desk-zh", home: { x: 400, y: 586 },
    route: [{ x: 400, y: 586 }, { x: 400, y: 626 }, { x: 470, y: 626 }] }),
  C({ id: "supporter-lead", name: "Sumin", file: "Agent_Global_Supporter.png", size: { w: 277, h: 367 },
    role: "supporterLead", zone: "supporters", home: { x: 506, y: 586 },
    route: [{ x: 506, y: 586 }, { x: 560, y: 630 }] }),
  // service desks
  C({ id: "visa", name: "Yuna", file: "Agent_Visa_and_Stay.png", size: { w: 253, h: 361 }, role: "visa", zone: "visa",
    desk: "desk-visa", home: { x: 830, y: 426 },
    route: [{ x: 830, y: 426 }, { x: 884, y: 486 }, { x: 748, y: 486 }] }),
  C({ id: "academic", name: "Joon", file: "Agent_Academics.png", size: { w: 251, h: 384 }, role: "academic",
    zone: "academic", desk: "desk-academic", home: { x: 1158, y: 426 },
    route: [{ x: 1158, y: 426 }, { x: 1090, y: 486 }, { x: 1010, y: 486 }] }),
  C({ id: "topik", name: "Seo", file: "Agent_TOPIK.png", size: { w: 259, h: 359 }, role: "topik", zone: "academic",
    home: { x: 1232, y: 470 }, route: [{ x: 1232, y: 470 }, { x: 1214, y: 360 }] }),
  C({ id: "opportunities", name: "Leo", file: "Agent_Events_and_Contests.png", size: { w: 251, h: 366 },
    role: "opportunities", zone: "opportunities", desk: "desk-opportunities", home: { x: 1492, y: 426 },
    route: [{ x: 1492, y: 426 }, { x: 1500, y: 548 }, { x: 1376, y: 548 }] }),
  C({ id: "events", name: "Mia", file: "Agent_Life_in_Korea.png", size: { w: 276, h: 365 }, role: "events",
    zone: "events", desk: "desk-events", home: { x: 236, y: 808 },
    route: [{ x: 236, y: 808 }, { x: 236, y: 912 }, { x: 120, y: 912 }] }),
  C({ id: "career", name: "Daniel", file: "Agent_Part_Time_Job.png", size: { w: 262, h: 365 }, role: "career",
    zone: "career", desk: "desk-career", home: { x: 1344, y: 808 },
    route: [{ x: 1344, y: 808 }, { x: 1344, y: 912 }, { x: 1456, y: 912 }] }),
  // visiting students (scenery)
  C({ id: "visitor-1", name: "", file: "BR_Brazil.png", size: { w: 222, h: 330 }, role: "visitor", zone: "reception",
    home: { x: 870, y: 966 }, interactive: false,
    route: [{ x: 870, y: 966 }, { x: 870, y: 732 }, { x: 590, y: 732 }, { x: 590, y: 632 }] }),
  C({ id: "visitor-2", name: "", file: "MN_Mongolia.png", size: { w: 230, h: 343 }, role: "visitor", zone: "waiting",
    home: { x: 1155, y: 960 }, interactive: false,
    route: [{ x: 1155, y: 960 }, { x: 1155, y: 726 }, { x: 1300, y: 640 }, { x: 1300, y: 566 }] }),
  C({ id: "visitor-3", name: "", file: "FR_France.png", size: { w: 220, h: 330 }, role: "visitor", zone: "waiting",
    home: { x: 964, y: 944 }, interactive: false,
    route: [{ x: 964, y: 944 }, { x: 912, y: 944 }, { x: 912, y: 726 }, { x: 1010, y: 726 }, { x: 1010, y: 476 }] }),
];

export function characterWidth(c: OfficeCharacter): number {
  return Math.round((CHARACTER_HEIGHT * c.size.w) / c.size.h);
}

export const INTERACTIVE = CHARACTERS.filter((c) => c.interactive);
export const SUPPORTERS = CHARACTERS.filter((c) => c.role === "supporter");
