// Writes what the dashboard's own colors.js derives for every palette color
// in every theme, so the phone apps' tests can check they tint the same way.
// Run by mobile/tools/generate.py:
//   node color_cases.mjs <theme.json> <palette.json> <copy of colors.js named colors.mjs>
// (the copy is loaded as a module on any Node version, without a package.json).
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const { deriveFrom, rgb } = await import(pathToFileURL(process.argv[4]).href);

const themes = JSON.parse(readFileSync(process.argv[2], "utf-8"));
const palette = JSON.parse(readFileSync(process.argv[3], "utf-8"));
const cases = [];
for (const [theme, tokens] of Object.entries(themes)) {
  const k = {};
  for (const [name, value] of Object.entries(tokens)) {
    if (typeof value === "string" && rgb(value)) k[`--${name}`] = rgb(value);
  }
  for (const color of palette) {
    cases.push({ theme, base: color.hex, tokens: deriveFrom(color.hex, k, theme) });
  }
  // A person's own hex, too: very light and very dark.
  for (const base of ["#FAFAFA", "#050505"]) {
    cases.push({ theme, base, tokens: deriveFrom(base, k, theme) });
  }
}
process.stdout.write(JSON.stringify(cases, null, 1) + "\n");
