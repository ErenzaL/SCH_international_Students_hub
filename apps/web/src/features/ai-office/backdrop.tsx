/** The room: back wall (windows, posters, clock), wooden floor and the zone rugs. Decorative SVG, one layer. */
import { STAGE, ZONES, type Zone } from "@/features/ai-office/characters";
import { PALETTE } from "@/features/ai-office/furniture";

const RUG: Record<Zone["tone"], string> = {
  cream: "#FFF3DC", mint: "#DDF3E7", sky: "#DCEEFA", lavender: "#ECE6FA", yellow: "#FFF2C6", beige: "#F4E7D2", peach: "#FDE6DA",
};

const line = { stroke: PALETTE.line, strokeOpacity: 0.28, strokeWidth: 2 };

function Window({ x }: { x: number }) {
  return (
    <g>
      <rect x={x} y={34} width={170} height={112} rx={14} fill="#FFFDF7" {...line} />
      <rect x={x + 10} y={44} width={150} height={92} rx={9} fill="#CFE9FA" />
      <ellipse cx={x + 52} cy={84} rx={26} ry={11} fill="#fff" opacity={0.9} />
      <ellipse cx={x + 70} cy={78} rx={18} ry={10} fill="#fff" opacity={0.9} />
      <ellipse cx={x + 120} cy={104} rx={22} ry={8} fill="#fff" opacity={0.75} />
      <rect x={x + 83} y={44} width={5} height={92} fill="#FFFDF7" />
      <rect x={x + 10} y={88} width={150} height={5} fill="#FFFDF7" />
      <rect x={x - 6} y={144} width={182} height={10} rx={5} fill={PALETTE.woodTop} {...line} />
    </g>
  );
}

function Poster({ x, y, tone, icon }: { x: number; y: number; tone: string; icon: "book" | "globe" | "star" | "cap" }) {
  return (
    <g transform={`rotate(${icon === "globe" || icon === "cap" ? 2 : -2} ${x + 34} ${y + 42})`}>
      <rect x={x} y={y} width={68} height={86} rx={8} fill={tone} {...line} />
      <circle cx={x + 34} cy={y + 2} r={3.5} fill="#E07A6A" />
      {icon === "book" && <path d={`M${x + 18} ${y + 22} h14 v26 h-14 z M${x + 36} ${y + 22} h14 v26 h-14 z`} fill="#fff" {...line} />}
      {icon === "globe" && <><circle cx={x + 34} cy={y + 36} r={15} fill="#fff" {...line} /><path d={`M${x + 19} ${y + 36} h30 M${x + 34} ${y + 21} q-12 15 0 30 q12 -15 0 -30`} fill="none" {...line} /></>}
      {icon === "star" && <path d={`M${x + 34} ${y + 20} l5 11 12 1 -9 8 3 12 -11 -6 -11 6 3 -12 -9 -8 12 -1z`} fill="#fff" {...line} />}
      {icon === "cap" && <path d={`M${x + 14} ${y + 32} l20 -10 20 10 -20 10z M${x + 22} ${y + 37} v9 q12 7 24 0 v-9`} fill="#fff" {...line} />}
      <rect x={x + 14} y={y + 60} width={40} height={4} rx={2} fill={PALETTE.line} opacity={0.3} />
      <rect x={x + 20} y={y + 69} width={28} height={4} rx={2} fill={PALETTE.line} opacity={0.22} />
    </g>
  );
}

export function Backdrop() {
  const { w, h, wall } = STAGE;
  return (
    <svg className="absolute inset-0" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden focusable="false">
      <defs>
        <linearGradient id="office-wall" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#FFF9EE" />
          <stop offset="1" stopColor="#FBEFDC" />
        </linearGradient>
        <pattern id="office-planks" width="300" height="56" patternUnits="userSpaceOnUse">
          <rect width="300" height="56" fill="#F7EAD6" />
          <rect y="28" width="300" height="28" fill="#F4E5CE" />
          <path d="M0 27.5 H300 M0 55.5 H300 M210 0 V28 M90 28 V56" stroke="#EAD7BA" strokeWidth="1" />
        </pattern>
      </defs>
      {/* wall */}
      <rect width={w} height={wall + 10} fill="url(#office-wall)" />
      <rect y={wall - 70} width={w} height={70} fill="#F3E3C8" opacity={0.55} />
      <Window x={560} />
      <Window x={890} />
      <Poster x={190} y={52} tone="#E9E3FA" icon="globe" />
      <Poster x={1290} y={52} tone="#D8F1E4" icon="cap" />
      <Poster x={1480} y={70} tone="#FFF1BF" icon="star" />
      <Poster x={1084} y={176} tone="#FDE3D6" icon="book" />
      {/* clock */}
      <g>
        <circle cx={800} cy={196} r={24} fill="#FFFDF7" {...line} />
        <path d="M800 184 V196 H810" stroke={PALETTE.line} strokeOpacity={0.6} strokeWidth={3} strokeLinecap="round" fill="none" />
      </g>
      {/* skirting board */}
      <rect y={wall} width={w} height={14} fill="#E9D3B3" />
      {/* floor */}
      <rect y={wall + 14} width={w} height={h - wall - 14} fill="url(#office-planks)" />
      {/* zone rugs */}
      {ZONES.map((z) => (
        <rect key={z.id} x={z.x} y={z.y} width={z.w} height={z.h} rx={28} fill={RUG[z.tone]}
          stroke="#FFFFFF" strokeWidth={6} strokeOpacity={0.85} />
      ))}
      {/* entrance mat */}
      <rect x={720} y={978} width={160} height={18} rx={9} fill="#E8C9A0" />
    </svg>
  );
}
