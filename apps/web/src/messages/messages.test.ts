import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import en from "@/messages/en.json";
import ko from "@/messages/ko.json";
import id from "@/messages/id.json";
import vi from "@/messages/vi.json";
import zh from "@/messages/zh-CN.json";

type Dict = { [k: string]: string | Dict };

function flatten(obj: Dict, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "string" ? [prefix + k] : flatten(v, `${prefix}${k}.`),
  );
}

function has(obj: Dict, dotted: string): boolean {
  let cur: string | Dict | undefined = obj;
  for (const part of dotted.split(".")) {
    if (typeof cur !== "object" || cur === null || !(part in cur)) return false;
    cur = cur[part];
  }
  return true;
}

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(name) && !/\.test\./.test(name)) out.push(p);
  }
  return out;
}

describe("message catalogs", () => {
  const enKeys = new Set(flatten(en as Dict));

  it.each([
    ["ko", ko],
    ["id", id],
    ["vi", vi],
    ["zh-CN", zh],
  ])("%s has no keys missing from English", (_name, messages) => {
    const extra = flatten(messages as Dict).filter((k) => !enKeys.has(k));
    expect(extra).toEqual([]);
  });

  it("every literal translation key used in source exists in en.json", () => {
    const root = path.resolve(__dirname, "..");
    const missing: string[] = [];
    for (const file of walk(root)) {
      const src = readFileSync(file, "utf8");
      const namespaces = new Map<string, string[]>();
      for (const m of src.matchAll(/const (\w+) = (?:await )?(?:useTranslations|getTranslations)\("([^"]+)"\)/g)) {
        namespaces.set(m[1], [...(namespaces.get(m[1]) ?? []), m[2]]);
      }
      for (const [varName, nsList] of namespaces) {
        const re = new RegExp(`(?<![\\w.])${varName}\\(\\s*([\`"])([^\`"]+)\\1`, "g");
        for (const m of src.matchAll(re)) {
          const key = m[2];
          // The same variable name can be bound to different namespaces in different
          // components of one file, so a key is valid if it exists in any of them.
          const prefix = key.includes("${") ? key.split("${")[0].replace(/\.$/, "") : key;
          const ok = nsList.some((ns) => has(en as Dict, prefix ? `${ns}.${prefix}` : ns));
          if (!ok) missing.push(`${path.relative(root, file)}: ${nsList.join("|")}.${key}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });
});
