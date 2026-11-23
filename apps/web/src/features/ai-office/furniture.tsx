/**
 * Furniture artwork for the AI Office: flat, rounded, pastel shapes seen from the front and slightly above (front
 * faces plus a sliver of the top surface), one consistent outline and shadow style. Purely decorative SVG.
 */
import type { Furniture } from "@/features/ai-office/characters";

export const PALETTE = {
  cream: "#FFF7E8", beige: "#F2E4CC", warmWhite: "#FFFDF7", sky: "#D9EEFB", mint: "#D8F1E4", lavender: "#E9E3FA",
  yellow: "#FFF1BF", peach: "#FDE3D6",
  wood: "#EBCB9F", woodTop: "#F6DDB8", woodDark: "#D7AE7C", line: "#7A6553",
  screen: "#CDE8F8", screenDark: "#41506A", leaf: "#8FD0A8", leafDark: "#6DB98E", pot: "#F2B7A0", potDark: "#E39E86",
} as const;

const ACCENT: Record<NonNullable<Furniture["accent"]>, string> = {
  mint: "#A9E0C4", sky: "#A9D4F2", lavender: "#C9BDF2", yellow: "#F8DD82", peach: "#F7C3AC", beige: "#E6CFA8",
};

const stroke = { stroke: PALETTE.line, strokeOpacity: 0.32, strokeWidth: 2, strokeLinejoin: "round" as const };

function Shadow({ w, h, inset = 6 }: { w: number; h: number; inset?: number }) {
  return <ellipse cx={w / 2} cy={h - 3} rx={w / 2 - inset} ry={5} fill="#5B4636" opacity={0.12} />;
}

function Desk({ w, h, accent }: { w: number; h: number; accent: string }) {
  const top = h - 58;
  return (
    <>
      <Shadow w={w} h={h} />
      {/* monitor */}
      <rect x={w / 2 - 26} y={top - 36} width={52} height={34} rx={6} fill={PALETTE.screenDark} {...stroke} />
      <rect x={w / 2 - 21} y={top - 31} width={42} height={24} rx={3} fill={PALETTE.screen} />
      <rect x={w / 2 - 16} y={top - 26} width={20} height={3} rx={1.5} fill="#fff" opacity={0.85} />
      <rect x={w / 2 - 16} y={top - 20} width={28} height={3} rx={1.5} fill="#fff" opacity={0.6} />
      <rect x={w / 2 - 4} y={top - 3} width={8} height={6} fill={PALETTE.screenDark} />
      {/* mug + plant */}
      <rect x={w - 26} y={top - 12} width={12} height={13} rx={3} fill={accent} {...stroke} />
      <circle cx={18} cy={top - 10} r={8} fill={PALETTE.leaf} />
      <rect x={12} y={top - 6} width={12} height={9} rx={2} fill={PALETTE.pot} {...stroke} />
      {/* top surface + front panel */}
      <rect x={2} y={top} width={w - 4} height={14} rx={6} fill={PALETTE.woodTop} {...stroke} />
      <rect x={w / 2 - 22} y={top + 3} width={44} height={6} rx={3} fill="#fff" opacity={0.75} />
      <rect x={8} y={top + 12} width={w - 16} height={34} rx={6} fill={PALETTE.wood} {...stroke} />
      <rect x={w - 50} y={top + 18} width={34} height={20} rx={4} fill={accent} {...stroke} />
      <rect x={w - 38} y={top + 26} width={10} height={3} rx={1.5} fill={PALETTE.line} opacity={0.35} />
      {/* legs */}
      <rect x={14} y={top + 44} width={8} height={h - top - 48} rx={3} fill={PALETTE.woodDark} />
      <rect x={w - 22} y={top + 44} width={8} height={h - top - 48} rx={3} fill={PALETTE.woodDark} />
    </>
  );
}

function Bookshelf({ w, h }: { w: number; h: number }) {
  const rows = 3;
  const inner = (h - 22) / rows;
  const books = ["#F7C3AC", "#A9D4F2", "#C9BDF2", "#A9E0C4", "#F8DD82", "#F2B7A0"];
  return (
    <>
      <Shadow w={w} h={h} />
      <rect x={2} y={2} width={w - 4} height={h - 8} rx={8} fill={PALETTE.wood} {...stroke} />
      {Array.from({ length: rows }, (_, r) => {
        const y = 10 + r * inner;
        let x = 10;
        const items = [];
        for (let i = 0; x < w - 22; i++) {
          const bw = 7 + ((i * 7 + r * 3) % 6);
          const bh = inner - 12 - ((i * 5 + r) % 3) * 5;
          if (r === 1 && i === 2) {   // a small globe on the middle shelf
            items.push(<circle key={`g${i}`} cx={x + 9} cy={y + inner - 16} r={8} fill={PALETTE.sky} {...stroke} />);
            x += 22;
            continue;
          }
          items.push(<rect key={i} x={x} y={y + inner - 6 - bh} width={bw} height={bh} rx={2}
            fill={books[(i + r * 2) % books.length]} {...stroke} strokeWidth={1.5} />);
          x += bw + 2;
        }
        return (
          <g key={r}>
            <rect x={8} y={y} width={w - 16} height={inner - 4} rx={4} fill={PALETTE.woodDark} opacity={0.45} />
            {items}
            <rect x={6} y={y + inner - 6} width={w - 12} height={5} rx={2} fill={PALETTE.woodTop} />
          </g>
        );
      })}
    </>
  );
}

function Plant({ w, h, small }: { w: number; h: number; small?: boolean }) {
  const potH = small ? 22 : 28;
  const cx = w / 2;
  return (
    <>
      <Shadow w={w} h={h} inset={8} />
      <g>
        {(small ? [[-9, -10, 10], [8, -12, 11], [0, -22, 12]] : [[-12, -18, 13], [12, -22, 14], [-6, -42, 14], [9, -52, 13], [0, -66, 12]])
          .map(([dx, dy, r], i) => (
            <ellipse key={i} cx={cx + dx} cy={h - potH + dy} rx={r * 0.8} ry={r} fill={i % 2 ? PALETTE.leafDark : PALETTE.leaf}
              {...stroke} strokeWidth={1.5} />
          ))}
      </g>
      <path d={`M${cx - 15} ${h - potH} h30 l-4 ${potH - 6} a4 4 0 0 1 -4 3 h-14 a4 4 0 0 1 -4 -3 z`} fill={PALETTE.pot} {...stroke} />
      <rect x={cx - 17} y={h - potH - 4} width={34} height={7} rx={3} fill={PALETTE.potDark} {...stroke} />
    </>
  );
}

function Board({ w, h }: { w: number; h: number }) {
  const notes = ["#FFF1BF", "#D9EEFB", "#FDE3D6", "#D8F1E4", "#E9E3FA"];
  return (
    <>
      <Shadow w={w} h={h} />
      <rect x={w / 2 - 4} y={h - 34} width={8} height={30} fill={PALETTE.woodDark} />
      <rect x={w / 2 - 22} y={h - 8} width={44} height={6} rx={3} fill={PALETTE.woodDark} />
      <rect x={2} y={2} width={w - 4} height={h - 34} rx={8} fill="#E7C39A" {...stroke} />
      <rect x={8} y={8} width={w - 16} height={h - 46} rx={5} fill="#F3DDBE" />
      {notes.map((c, i) => {
        const x = 14 + (i % 3) * ((w - 34) / 3);
        const y = 13 + Math.floor(i / 3) * 26;
        return (
          <g key={i} transform={`rotate(${(i % 2 ? 4 : -3)} ${x + 14} ${y + 10})`}>
            <rect x={x} y={y} width={30} height={22} rx={3} fill={c} {...stroke} strokeWidth={1.5} />
            <circle cx={x + 15} cy={y + 3} r={2.5} fill="#E07A6A" />
            <rect x={x + 5} y={y + 10} width={18} height={2.5} rx={1} fill={PALETTE.line} opacity={0.3} />
          </g>
        );
      })}
    </>
  );
}

function Counter({ w, h }: { w: number; h: number }) {
  const top = h - 66;
  return (
    <>
      <Shadow w={w} h={h} />
      {/* bell + small monitor */}
      <rect x={w - 70} y={top - 30} width={40} height={28} rx={5} fill={PALETTE.screenDark} {...stroke} />
      <rect x={w - 66} y={top - 26} width={32} height={18} rx={3} fill={PALETTE.screen} />
      <path d={`M28 ${top} a11 11 0 0 1 22 0 z`} fill="#F8DD82" {...stroke} />
      <circle cx={39} cy={top - 12} r={2.5} fill={PALETTE.line} opacity={0.5} />
      <rect x={2} y={top} width={w - 4} height={16} rx={7} fill={PALETTE.woodTop} {...stroke} />
      <rect x={6} y={top + 14} width={w - 12} height={h - top - 22} rx={10} fill={PALETTE.warmWhite} {...stroke} />
      <rect x={18} y={top + 24} width={w - 36} height={h - top - 42} rx={7} fill={PALETTE.sky} opacity={0.75} />
    </>
  );
}

function MeetingTable({ w, h }: { w: number; h: number }) {
  const top = h - 52;
  const chairs = [0.18, 0.4, 0.62, 0.84];
  return (
    <>
      <Shadow w={w} h={h} />
      {/* chair backs behind the table */}
      {chairs.map((f, i) => (
        <rect key={i} x={w * f - 18} y={top - 26} width={36} height={34} rx={10}
          fill={[PALETTE.mint, PALETTE.lavender, PALETTE.sky, PALETTE.yellow][i]} {...stroke} />
      ))}
      <ellipse cx={w / 2} cy={top + 12} rx={w / 2 - 4} ry={20} fill={PALETTE.woodTop} {...stroke} />
      <ellipse cx={w / 2} cy={top + 9} rx={w / 2 - 22} ry={10} fill="#fff" opacity={0.35} />
      <rect x={w * 0.3} y={top + 2} width={34} height={16} rx={3} fill={PALETTE.warmWhite} {...stroke} strokeWidth={1.5} />
      <rect x={w * 0.56} y={top + 4} width={40} height={14} rx={3} fill={PALETTE.screenDark} {...stroke} strokeWidth={1.5} />
      <path d={`M10 ${top + 14} q${w / 2 - 10} 34 ${w - 20} 0 v6 q-${w / 2 - 10} 30 -${w - 20} 0 z`} fill={PALETTE.wood} {...stroke} />
      <rect x={w / 2 - 6} y={top + 30} width={12} height={h - top - 34} rx={4} fill={PALETTE.woodDark} />
    </>
  );
}

function Sofa({ w, h }: { w: number; h: number }) {
  return (
    <>
      <Shadow w={w} h={h} />
      <rect x={10} y={4} width={w - 20} height={34} rx={14} fill={PALETTE.lavender} {...stroke} />
      <rect x={18} y={10} width={(w - 44) / 2} height={24} rx={10} fill="#F3EFFD" />
      <rect x={w / 2 + 4} y={10} width={(w - 44) / 2} height={24} rx={10} fill="#F3EFFD" />
      <rect x={4} y={30} width={w - 8} height={28} rx={12} fill="#DCD2F7" {...stroke} />
      <rect x={2} y={16} width={22} height={44} rx={10} fill={PALETTE.lavender} {...stroke} />
      <rect x={w - 24} y={16} width={22} height={44} rx={10} fill={PALETTE.lavender} {...stroke} />
      <rect x={14} y={58} width={8} height={h - 60} rx={3} fill={PALETTE.woodDark} />
      <rect x={w - 22} y={58} width={8} height={h - 60} rx={3} fill={PALETTE.woodDark} />
    </>
  );
}

function SideTable({ w, h }: { w: number; h: number }) {
  return (
    <>
      <Shadow w={w} h={h} inset={2} />
      <rect x={6} y={2} width={8} height={10} rx={3} fill="#F7C3AC" {...stroke} strokeWidth={1.5} />
      <rect x={1} y={10} width={w - 2} height={8} rx={4} fill={PALETTE.woodTop} {...stroke} />
      <rect x={w / 2 - 3} y={17} width={6} height={h - 20} fill={PALETTE.woodDark} />
    </>
  );
}

function Cabinet({ w, h }: { w: number; h: number }) {
  return (
    <>
      <Shadow w={w} h={h} inset={2} />
      <rect x={2} y={2} width={w - 4} height={h - 8} rx={6} fill="#DCE5EE" {...stroke} />
      {[0, 1, 2].map((i) => (
        <g key={i}>
          <rect x={8} y={8 + i * ((h - 18) / 3)} width={w - 16} height={(h - 18) / 3 - 5} rx={4} fill="#EEF3F8" {...stroke} strokeWidth={1.5} />
          <rect x={w / 2 - 8} y={14 + i * ((h - 18) / 3)} width={16} height={4} rx={2} fill={PALETTE.line} opacity={0.35} />
        </g>
      ))}
    </>
  );
}

function Cooler({ w, h }: { w: number; h: number }) {
  return (
    <>
      <Shadow w={w} h={h} inset={2} />
      <path d={`M${w / 2 - 12} 4 h24 a6 6 0 0 1 6 6 v20 h-36 v-20 a6 6 0 0 1 6 -6 z`} fill="#BFE3F7" {...stroke} />
      <rect x={4} y={30} width={w - 8} height={h - 36} rx={6} fill={PALETTE.warmWhite} {...stroke} />
      <rect x={w / 2 - 6} y={44} width={12} height={8} rx={2} fill="#A9D4F2" />
    </>
  );
}

function Lamp({ w, h }: { w: number; h: number }) {
  return (
    <>
      <Shadow w={w} h={h} inset={4} />
      <path d={`M4 26 l6 -22 h${w - 20} l6 22 z`} fill="#FFF1BF" {...stroke} />
      <rect x={w / 2 - 2} y={26} width={4} height={h - 34} fill={PALETTE.woodDark} />
      <rect x={w / 2 - 10} y={h - 9} width={20} height={5} rx={2} fill={PALETTE.woodDark} />
    </>
  );
}

export function FurnitureArt({ item }: { item: Furniture }) {
  const { w, h } = item;
  const accent = ACCENT[item.accent ?? "beige"];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden focusable="false" className="overflow-visible">
      {item.kind === "desk" && <Desk w={w} h={h} accent={accent} />}
      {item.kind === "bookshelf" && <Bookshelf w={w} h={h} />}
      {item.kind === "plant" && <Plant w={w} h={h} />}
      {item.kind === "plantSmall" && <Plant w={w} h={h} small />}
      {item.kind === "board" && <Board w={w} h={h} />}
      {item.kind === "counter" && <Counter w={w} h={h} />}
      {item.kind === "meetingTable" && <MeetingTable w={w} h={h} />}
      {item.kind === "sofa" && <Sofa w={w} h={h} />}
      {item.kind === "sideTable" && <SideTable w={w} h={h} />}
      {item.kind === "cabinet" && <Cabinet w={w} h={h} />}
      {item.kind === "cooler" && <Cooler w={w} h={h} />}
      {item.kind === "lamp" && <Lamp w={w} h={h} />}
    </svg>
  );
}
