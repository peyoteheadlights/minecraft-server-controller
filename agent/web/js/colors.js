/* A server's color carried through its whole page.

   The base color (from the server's row, a palette color or the person's
   own hex) is only ever used as a fill. For everything people read, this
   derives darker or lighter shades on the current theme until they pass
   WCAG AA (4.5:1 for text, 3:1 for focus rings and other non-text marks),
   so any color works on every theme. Status colors (green, amber, red)
   are separate tokens and never change with the server's color. */

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

function mix(a, b, amount) {
  return a.map((c, i) => c + (b[i] - c) * amount);
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

function token(name) {
  return rgb(getComputedStyle(document.documentElement).getPropertyValue(name));
}

/* The theme's own surfaces, read from the tokens in styles.css. */
export function themeSurfaces() {
  return {
    surface: token("--surface") || WHITE,
    sheet: token("--sheet") || WHITE,
    desk: token("--desk") || WHITE,
    text: token("--text-primary") || BLACK,
  };
}

/* Every token a server's color sets, for the current theme. */
export function derive(baseHex) {
  const base = rgb(baseHex);
  if (!base) return null;
  const s = themeSurfaces();
  const dark = luminance(s.sheet) < 0.18;
  const { fill, text } = fillWithText(base);
  const hover = fillWithText(mix(fill, dark ? WHITE : BLACK, 0.12));
  const band = mix(s.sheet, base, dark ? 0.16 : 0.1);
  const ink = readable(base, [s.surface, s.sheet, band]);
  const ring = readable(base, [s.surface, s.sheet], AA_MARK);
  const tab = mix(s.desk, base, dark ? 0.32 : 0.24);
  return {
    "--accent": hex(fill),
    "--accent-text": hex(text),
    "--accent-hover": hex(hover.fill),
    "--accent-hover-text": hex(hover.text),
    "--accent-ink": hex(ink),
    "--accent-soft": `rgba(${base.map(Math.round).join(", ")}, ${dark ? 0.2 : 0.13})`,
    "--accent-band": hex(band),
    "--accent-edge": hex(base),
    "--accent-ring": hex(ring),
    "--tab-fill": hex(tab),
    "--tab-text": hex(readable(s.text, [tab])),
  };
}

const APPLIED = Object.keys(derive("#808080") || {});

/* Colors the page for one server, or back to the neutral look (null). */
export function applyServerColor(baseHex) {
  const root = document.documentElement.style;
  const tokens = baseHex ? derive(baseHex) : null;
  for (const name of APPLIED) {
    if (tokens) root.setProperty(name, tokens[name]);
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
  const s = themeSurfaces();
  const c = (name) => rgb(tokens[name]);
  return [
    ["text on button", contrast(c("--accent-text"), c("--accent")), AA_TEXT],
    ["text on hovered button", contrast(c("--accent-hover-text"), c("--accent-hover")), AA_TEXT],
    ["link on card", contrast(c("--accent-ink"), s.surface), AA_TEXT],
    ["link on page", contrast(c("--accent-ink"), s.sheet), AA_TEXT],
    ["link on header band", contrast(c("--accent-ink"), c("--accent-band")), AA_TEXT],
    ["text on tab", contrast(c("--tab-text"), c("--tab-fill")), AA_TEXT],
    ["focus ring on page", contrast(c("--accent-ring"), s.sheet), AA_MARK],
  ].map(([pair, ratio, min]) => ({ pair, ratio: Math.round(ratio * 100) / 100, min }));
}
