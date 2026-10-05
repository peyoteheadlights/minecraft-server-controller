/* A server's color carried through its whole page.

   The base color (from the server's row, a palette color or the person's
   own hex) tints the whole page: the page itself, its header band, the
   cards and the sunken areas each take a little of it, and buttons are
   filled with it. Everything people read is then derived again on those
   tinted backgrounds, shaded darker or lighter until it passes WCAG AA
   (4.5:1 for text, 3:1 for focus rings and other non-text marks), so any
   color works on every theme. Status colors (green, amber, red) keep their
   hue; they are only shaded to stay readable on the tint. */

const AA_TEXT = 4.5;
const AA_MARK = 3;

export function rgb(hex) {
  const value = /^#?([0-9a-f]{6})$/i.exec(String(hex || "").trim());
  if (!value) return null;
  const n = parseInt(value[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function hex(color) {
  return `#${color.map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, "0")).join("")}`
    .toUpperCase();
}

function channel(c) {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function luminance(color) {
  const [r, g, b] = color.map(channel);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/* Rounded to whole channels, as the hex token will be, so a contrast
   checked here is the contrast the page gets. */
function mix(a, b, amount) {
  return a.map((c, i) => Math.round(c + (b[i] - c) * amount));
}

const BLACK = [0, 0, 0];
const WHITE = [255, 255, 255];

/* color moved toward black or white, whichever reads better against every
   background, until it reaches min contrast with all of them. */
export function readable(color, backgrounds, min = AA_TEXT) {
  const darkest = Math.min(...backgrounds.map(luminance));
  const target = darkest > 0.18 ? BLACK : WHITE;
  for (let step = 0; step <= 20; step += 1) {
    const candidate = mix(color, target, step / 20);
    if (backgrounds.every((bg) => contrast(candidate, bg) >= min)) return candidate;
  }
  return target;
}

/* A fill that text can sit on: white or near-black text, whichever reads
   better, with the fill itself shaded until that text passes. */
export function fillWithText(color) {
  const dark = [17, 17, 17];
  const text = contrast(color, WHITE) >= contrast(color, dark) ? WHITE : dark;
  const away = text === WHITE ? BLACK : WHITE;
  for (let step = 0; step <= 20; step += 1) {
    const fill = mix(color, away, step / 20);
    if (contrast(fill, text) >= AA_TEXT) return { fill, text };
  }
  return { fill: away, text };
}

/* Every token a server's color sets. The page itself is tinted with it,
   not only the header: the sheet, the cards and the sunken areas take a
   little of the color, and every text color is then re-checked against
   those tinted backgrounds. */
const TINTED = ["--sheet", "--surface", "--surface-sunken", "--surface-float",
  "--text-primary", "--text-secondary", "--text-tertiary", "--success", "--warning", "--danger"];
const ACCENT = ["--accent", "--accent-text", "--accent-hover", "--accent-hover-text", "--accent-ink",
  "--accent-soft", "--accent-band", "--accent-edge", "--accent-ring", "--tab-fill", "--tab-text"];
const APPLIED = [...TINTED, ...ACCENT];

/* The theme's own tokens, read with any server tint taken off for the
   moment, so a color is always derived from the untinted theme. */
function themeTokens() {
  const root = document.documentElement.style;
  const saved = APPLIED.map((name) => [name, root.getPropertyValue(name)]);
  for (const name of APPLIED) root.removeProperty(name);
  const style = getComputedStyle(document.documentElement);
  const read = (name) => rgb(style.getPropertyValue(name));
  const tokens = Object.fromEntries(TINTED.map((name) => [name, read(name)]));
  tokens["--desk"] = read("--desk");
  for (const [name, value] of saved) if (value) root.setProperty(name, value);
  return tokens;
}

/* How much of the server's color each surface takes. High contrast keeps
   its tint faint so it stays as stark as it is meant to be. */
function tintAmounts(dark) {
  if (document.documentElement.dataset.theme === "contrast") {
    return { sheet: 0.1, surface: 0.06, sunken: 0.1, band: 0.2 };
  }
  return dark
    ? { sheet: 0.18, surface: 0.13, sunken: 0.16, band: 0.3 }
    : { sheet: 0.2, surface: 0.07, sunken: 0.18, band: 0.32 };
}

/* A text color kept at least as readable on the tinted backgrounds as it
   was on the theme's own (and never under AA for body text). */
function keepReadable(color, before, after, floor = AA_TEXT) {
  if (!color) return null;
  const was = Math.min(...before.map((bg) => contrast(color, bg)));
  return readable(color, after, Math.min(floor, was));
}

export function derive(baseHex) {
  const base = rgb(baseHex);
  if (!base) return null;
  const k = themeTokens();
  const sheet0 = k["--sheet"] || WHITE, surface0 = k["--surface"] || WHITE;
  const sunken0 = k["--surface-sunken"] || surface0, float0 = k["--surface-float"] || surface0;
  const desk = k["--desk"] || WHITE;
  const dark = luminance(sheet0) < 0.18;
  const amount = tintAmounts(dark);
  const sheet = mix(sheet0, base, amount.sheet);
  const surface = mix(surface0, base, amount.surface);
  const sunken = mix(sunken0, base, amount.sunken);
  const float = mix(float0, base, amount.surface);
  const band = mix(sheet0, base, amount.band);
  const before = [sheet0, surface0, sunken0];
  const after = [sheet, surface, sunken, band];
  const textOn = (name, floor) => keepReadable(k[name], before, after, floor);
  const text = textOn("--text-primary");
  const { fill, text: onFill } = fillWithText(base);
  const hover = fillWithText(mix(fill, dark ? WHITE : BLACK, 0.12));
  const ink = readable(base, [surface, sheet, band]);
  const ring = readable(base, [surface, sheet], AA_MARK);
  const tab = mix(desk, base, dark ? 0.32 : 0.24);
  const tokens = {
    "--sheet": sheet, "--surface": surface, "--surface-sunken": sunken, "--surface-float": float,
    "--text-primary": text,
    "--text-secondary": textOn("--text-secondary"),
    "--text-tertiary": textOn("--text-tertiary"),
    "--success": textOn("--success"),
    "--warning": textOn("--warning"),
    "--danger": textOn("--danger"),
    "--accent": fill,
    "--accent-text": onFill,
    "--accent-hover": hover.fill,
    "--accent-hover-text": hover.text,
    "--accent-ink": ink,
    "--accent-band": band,
    "--accent-edge": base,
    "--accent-ring": ring,
    "--tab-fill": tab,
    "--tab-text": readable(k["--text-primary"] || BLACK, [tab]),
  };
  const out = {};
  for (const [name, value] of Object.entries(tokens)) if (value) out[name] = hex(value);
  out["--accent-soft"] = `rgba(${base.map(Math.round).join(", ")}, ${dark ? 0.2 : 0.13})`;
  return out;
}

/* Colors the page for one server, or back to the neutral look (null). */
export function applyServerColor(baseHex) {
  const root = document.documentElement.style;
  const tokens = baseHex ? derive(baseHex) : null;
  for (const name of APPLIED) {
    if (tokens && tokens[name]) root.setProperty(name, tokens[name]);
    else root.removeProperty(name);
  }
  setFavicon(baseHex);
}

/* The browser tab's icon: the app's cube on the server's color. */
export function setFavicon(baseHex) {
  const base = rgb(baseHex);
  const fill = base ? fillWithText(base) : { fill: [60, 60, 67], text: WHITE };
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">`
    + `<rect width="32" height="32" rx="8" fill="${hex(fill.fill)}"/>`
    + `<g fill="none" stroke="${hex(fill.text)}" stroke-width="2.2" stroke-linejoin="round">`
    + `<path d="M16 5.5l9.5 5.2v10.6L16 26.5l-9.5-5.2V10.7z"/><path d="M6.8 11 16 16l9.2-5M16 16v10"/></g></svg>`;
  let link = document.querySelector("link[rel=icon]");
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.append(link);
  }
  link.type = "image/svg+xml";
  link.href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/* For the browser check: every pair that must pass, with its ratio. */
export function contrastReport(baseHex) {
  const tokens = derive(baseHex);
  const c = (name) => rgb(tokens[name]);
  const pairs = [
    ["text on button", "--accent-text", "--accent", AA_TEXT],
    ["text on hovered button", "--accent-hover-text", "--accent-hover", AA_TEXT],
    ["link on card", "--accent-ink", "--surface", AA_TEXT],
    ["link on page", "--accent-ink", "--sheet", AA_TEXT],
    ["link on header band", "--accent-ink", "--accent-band", AA_TEXT],
    ["text on tab", "--tab-text", "--tab-fill", AA_TEXT],
    ["focus ring on page", "--accent-ring", "--sheet", AA_MARK],
  ];
  for (const bg of ["--sheet", "--surface", "--surface-sunken", "--accent-band"]) {
    pairs.push([`text on ${bg.slice(2)}`, "--text-primary", bg, AA_TEXT]);
    pairs.push([`secondary text on ${bg.slice(2)}`, "--text-secondary", bg, AA_TEXT]);
  }
  for (const status of ["--success", "--warning", "--danger"]) {
    pairs.push([`${status.slice(2)} on card`, status, "--surface", AA_MARK]);
  }
  return pairs.map(([pair, fg, bg, min]) => {
    const ratio = contrast(c(fg), c(bg));
    return { pair, ratio: Math.round(ratio * 100) / 100, min };
  });
}
