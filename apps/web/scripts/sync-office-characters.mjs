// Copies the AI Office character PNGs that the office uses from the repository's assets/characters/ (the originals,
// never modified or deleted) into public/office/characters/. Run after adding or changing character art:
//   node scripts/sync-office-characters.mjs [path/to/assets/characters]
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
