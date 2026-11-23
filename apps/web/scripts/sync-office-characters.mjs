// Copies the AI Office character PNGs that the office uses from the repository's assets/characters/ (the originals,
// never modified or deleted) into public/office/characters/. Run after adding or changing character art:
//   node scripts/sync-office-characters.mjs [path/to/assets/characters]
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(process.argv[2] ?? path.join(here, "../../../assets/characters"));
const dst = path.join(here, "../public/office/characters");
const config = fs.readFileSync(path.join(here, "../src/features/ai-office/characters.ts"), "utf8");
const files = [...new Set([...config.matchAll(/file: "([^"]+\.png)"/g)].map((m) => m[1]))];
fs.mkdirSync(dst, { recursive: true });
let copied = 0;
for (const f of files) {
  const from = path.join(src, f);
  if (!fs.existsSync(from)) {
    console.error(`missing: ${from}`);
    process.exitCode = 1;
    continue;
  }
  fs.copyFileSync(from, path.join(dst, f));
  copied++;
}
console.log(`${copied}/${files.length} character files copied to ${path.relative(process.cwd(), dst)}`);

// WebP copies of the same artwork (same pixel size, alpha kept) are what browsers download; PNGs stay as fallback.
const webp = path.join(dst, "webp");
fs.mkdirSync(webp, { recursive: true });
try {
  for (const f of files) {
    execFileSync("cwebp", ["-quiet", "-q", "88", "-alpha_q", "100", "-m", "6", "-sharp_yuv", path.join(dst, f), "-o",
      path.join(webp, f.replace(/\.png$/, ".webp"))]);
  }
  console.log(`${files.length} WebP copies written to ${path.relative(process.cwd(), webp)}`);
} catch {
  console.error("cwebp (libwebp) is not installed: WebP copies were not regenerated. Install it and run this again.");
  process.exitCode = 1;
}
