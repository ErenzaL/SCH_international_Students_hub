import type { OfficeCharacter } from "@/features/ai-office/characters";

/** A character's original artwork in a rounded tile (WebP with the PNG as fallback). */
export function Portrait({ c, size }: { c: OfficeCharacter; size: number }) {
  return (
    <span className="flex shrink-0 items-end justify-center overflow-hidden rounded-2xl bg-[#E8F2FB]" style={{ width: size, height: size }}>
      <picture className="contents">
        <source type="image/webp" srcSet={`/office/characters/webp/${c.file.replace(/\.png$/, ".webp")}`} />
        <img src={`/office/characters/${c.file}`} alt="" className="h-full w-full object-contain p-0.5" />
      </picture>
    </span>
  );
}
