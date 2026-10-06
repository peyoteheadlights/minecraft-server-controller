import { t, technical } from "./strings.js";

export const $ = (sel) => document.querySelector(sel);

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    // Style objects go through the CSSOM: the page's CSP blocks style attributes.
    else if (key === "style") Object.assign(node.style, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const ICONS = {
  overview: [["rect", { x: 3.5, y: 3.5, width: 7, height: 7, rx: 1.5 }], ["rect", { x: 13.5, y: 3.5, width: 7, height: 7, rx: 1.5 }],
             ["rect", { x: 3.5, y: 13.5, width: 7, height: 7, rx: 1.5 }], ["rect", { x: 13.5, y: 13.5, width: 7, height: 7, rx: 1.5 }]],
  servers: [["rect", { x: 3.5, y: 4, width: 17, height: 6.5, rx: 1.5 }], ["rect", { x: 3.5, y: 13.5, width: 17, height: 6.5, rx: 1.5 }],
            ["path", { d: "M7 7.25h.01M7 16.75h.01" }]],
  console: [["rect", { x: 2.5, y: 4, width: 19, height: 16, rx: 2.5 }], ["path", { d: "M7 9.5l3 2.5-3 2.5" }], ["path", { d: "M12.5 15h4.5" }]],
  players: [["circle", { cx: 9, cy: 8, r: 3.5 }], ["path", { d: "M2.5 20c.8-3.6 3.4-5.6 6.5-5.6s5.7 2 6.5 5.6" }],
            ["path", { d: "M15.5 4.6a3.5 3.5 0 0 1 0 6.8" }], ["path", { d: "M18 14.6c1.8.7 3 2.6 3.5 5.4" }]],
  performance: [["path", { d: "M3 12.5h4l2.6-7 4.8 13 2.6-6h4" }]],
  backups: [["rect", { x: 3, y: 4, width: 18, height: 5, rx: 1.2 }], ["path", { d: "M5 9v9.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V9" }], ["path", { d: "M10 13h4" }]],
  mods: [["path", { d: "M12 2.8l8.5 4.7v9L12 21.2 3.5 16.5v-9z" }], ["path", { d: "M3.8 7.6 12 12l8.2-4.4" }], ["path", { d: "M12 12v9" }]],
  schedules: [["circle", { cx: 12, cy: 12, r: 8.5 }], ["path", { d: "M12 7.5V12l3 2" }]],
  events: [["path", { d: "M8.5 6.5h12M8.5 12h12M8.5 17.5h12" }], ["path", { d: "M4 6.5h.01M4 12h.01M4 17.5h.01" }]],
  crashes: [["path", { d: "M12 3.8 21 19.5H3z" }], ["path", { d: "M12 10v4" }], ["path", { d: "M12 16.8h.01" }]],
  settings: [["path", { d: "M4 7h9M17 7h3M4 17h3M11 17h9" }], ["circle", { cx: 15, cy: 7, r: 2 }], ["circle", { cx: 9, cy: 17, r: 2 }]],
  gear: [["circle", { cx: 12, cy: 12, r: 3 }],
         ["path", { d: "M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" }],
         ["circle", { cx: 12, cy: 12, r: 6.2 }]],
  security: [["path", { d: "M12 3l7.5 3v5.5c0 4.5-3.1 8.2-7.5 9.5-4.4-1.3-7.5-5-7.5-9.5V6z" }], ["path", { d: "M9 12l2 2 4-4" }]],
  plus: [["path", { d: "M12 5v14M5 12h14" }]],
  game: [["rect", { x: 3, y: 7, width: 18, height: 11, rx: 3.5 }], ["path", { d: "M7.5 12.5h3M9 11v3" }],
         ["path", { d: "M15 11.5h.01M17 13.5h.01" }]],
  info: [["circle", { cx: 12, cy: 12, r: 8.5 }], ["path", { d: "M12 11v5.5M12 7.8h.01" }]],
  chevron: [["path", { d: "M9 6l6 6-6 6" }]],
  search: [["circle", { cx: 11, cy: 11, r: 6.5 }], ["path", { d: "M16 16l4.5 4.5" }]],
  copy: [["rect", { x: 8.5, y: 8.5, width: 11, height: 11, rx: 2 }], ["path", { d: "M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5" }]],
  download: [["path", { d: "M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14" }]],
  clear: [["path", { d: "M5 7h14M10 7V5h4v2M7 7l.8 12h8.4L17 7" }]],
  follow: [["path", { d: "M12 5v13M7 13l5 5 5-5" }]],
  pause: [["path", { d: "M9 6v12M15 6v12" }]],
  signout: [["path", { d: "M14 4.5h4A1.5 1.5 0 0 1 19.5 6v12a1.5 1.5 0 0 1-1.5 1.5h-4" }], ["path", { d: "M10 8l-4 4 4 4M6 12h9" }]],
};

export function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  for (const [tag, attrs] of ICONS[name] || []) {
    const shape = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) shape.setAttribute(k, v);
    svg.append(shape);
  }
  return svg;
}

export const known = (v) => v !== null && v !== undefined;

const unknown = () => t("value.unknown");

export const fmt = {
  bytes(n) {
    if (!known(n)) return unknown();
    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = Number(n), i = 0;
    while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
    return `${value.toFixed(value >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
  },
  gb(n) { return known(n) ? `${Number(n).toFixed(1)} GB` : unknown(); },
  pct(n) { return known(n) ? `${Number(n).toFixed(0)}%` : unknown(); },
  memory(mb) {
    if (!known(mb)) return null;
    return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
  },
  duration(seconds) {
    if (!known(seconds)) return unknown();
    const s = Math.max(0, Math.floor(seconds));
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d) return t("time.days_hours", { d, h });
    if (h) return t("time.hours_minutes", { h, m });
    if (m) return t("time.minutes", { m });
    return t("time.seconds", { s });
  },
  time(ts) {
    if (!ts) return t("time.never");
    return new Date(ts * 1000).toLocaleString(undefined,
      { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  },
  clock(ts) {
    return new Date(ts * 1000).toLocaleTimeString(undefined,
      { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  },
  ago(ts) {
    if (!ts) return t("time.never");
    return t("time.ago", { duration: fmt.duration(Date.now() / 1000 - ts) });
  },
  until(ts) {
    return t("time.in", { duration: fmt.duration(ts - Date.now() / 1000) });
  },
  xmx(memory) {
    const m = /-Xmx(\d+)([GgMm])/.exec(memory || "");
    if (!m) return null;
    return m[2].toLowerCase() === "g" ? `${m[1]} GB` : `${m[1]} MB`;
  },
  java(text) {
    const m = /version "([^"]+)"/.exec(text || "");
    return m ? m[1] : (text || null);
  },
};

export function announce(text) {
  const node = $("#announcer");
  node.textContent = "";
  setTimeout(() => { node.textContent = text; }, 50);
}

/* "This just happened": a short note in the corner that goes by itself. */
export function toast(message, level = "info", ms = 5200, action = null) {
  const tone = { error: "danger", warn: "warning", success: "success", info: "neutral" }[level] || "neutral";
  const node = el("div", { class: "toast", role: level === "error" ? "alert" : "status" },
    el("span", { class: `status-dot tone-${tone}` }),
    el("div", { class: "toast-text" }, message),
    action ? el("button", {
      class: "btn plain small",
      onclick: () => { node.remove(); action.onClick(); },
    }, action.label) : null);
  $("#toasts").append(node);
  setTimeout(() => node.remove(), ms);
}

/* A dialog. Body may be a string (shown as text, never parsed as markup)
   or a DOM node. Resolves true when confirmed. */
export function confirmDialog({ title, body, confirmLabel = null, danger = false, extra = null,
                         cancelLabel = null, wide = false, acknowledge = false }) {
  return new Promise((resolve) => {
    const root = $("#modal-root");
    const previous = document.activeElement;
    const bodyNode = el("div", { class: "body", id: "dialog-body" });
    if (typeof body === "string") bodyNode.append(el("p", {}, body));
    else if (body) bodyNode.append(body);
    const close = (value) => {
      document.removeEventListener("keydown", onKey, true);
      root.replaceChildren();
      if (previous && previous.focus) previous.focus();
      resolve(value);
    };
    const cancel = acknowledge ? null
      : el("button", { class: "btn", type: "button", onclick: () => close(false) },
        cancelLabel || t("action.cancel"));
    const confirm = el("button", {
      class: `btn ${danger ? "danger-filled" : "primary"}`, type: "button",
      onclick: () => close(true),
    }, confirmLabel || (acknowledge ? t("action.close") : t("action.confirm")));
    const onKey = (event) => {
      if (event.key === "Escape") { event.preventDefault(); close(false); }
      if (event.key === "Tab") {  // keep focus inside the dialog
        const focusable = [...root.querySelectorAll("button, input, select, textarea, a[href], summary")];
        if (!focusable.length) return;
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey, true);
    root.append(el("div", {
      class: "modal-backdrop",
      onclick: (e) => { if (e.target.classList.contains("modal-backdrop")) close(false); },
    }, el("div", {
      class: `modal ${wide || acknowledge ? "wide" : ""}`, role: "dialog", "aria-modal": "true",
      "aria-labelledby": "dialog-title", "aria-describedby": "dialog-body",
    },
      el("h3", { id: "dialog-title" }, title),
      bodyNode,
      extra,
      el("div", { class: "actions" }, cancel, confirm))));
    // A destructive action starts on Cancel.
    (danger && cancel ? cancel : confirm).focus();
  });
}

/* Runs an async action with its button showing progress, and refuses a
   second click while the first is still running. */
export async function busy(button, label, fn) {
  if (!button || button.classList.contains("is-busy")) return undefined;
  const original = [...button.childNodes];
  button.classList.add("is-busy");
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.replaceChildren(el("span", { class: "spinner", "aria-hidden": "true" }), label);
  try {
    return await fn();
  } finally {
    button.classList.remove("is-busy");
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.replaceChildren(...original);
  }
}

/* A titled group: the heading sits above the box. aside is an optional
   node on the heading's right (a link or small button). */
export function card(title, ...children) {
  return section(title, null, ...children);
}

export function section(title, aside, ...children) {
  return el("section", { class: "section" },
    title ? el("div", { class: "section-head" }, el("h2", {}, title),
      aside ? el("div", { class: "grow" }) : null, aside) : null,
    el("div", { class: "group-box" }, ...children));
}

/* Detail most people never need: collapsed in Simple mode, open in
   Technical mode, with a way to switch from right there. */
export function advanced(title, ...children) {
  // Loaded on click: prefs.js imports api.js, which imports this module.
  const switchLink = technical() ? null : el("button", {
    class: "btn plain small advanced-switch", type: "button",
    onclick: () => import("./prefs.js").then((prefs) => prefs.choose("mode", "technical")),
  }, t("advanced.show_technical"));
  return foldable(title, ...children, switchLink);
}

function foldable(title, ...children) {
  return el("details", { class: "advanced", open: technical() ? "open" : false },
    el("summary", {}, el("span", { class: "chev", "aria-hidden": "true" }, icon("chevron")), title),
    el("div", { class: "advanced-body" }, ...children));
}

/* A short, honest "we don't know yet" line, in place of a value. */
export function unknownNote(reason) {
  return el("span", { class: "unknown-note" }, reason || t("value.unknown"));
}

/* A small statistic. Unknown values say so, never 0. opts.summary, when
   given, builds a short summary shown on hover, tap or keyboard focus. */
export function metric(label, value, note, opts = {}) {
  const isUnknown = !known(value);
  const tip = opts.summary ? el("div", { class: "stat-summary", role: "tooltip" }) : null;
  const node = el("div", {
    class: `stat${opts.summary ? " has-summary" : ""}`,
    tabindex: opts.summary ? "0" : null,
  },
    el("div", { class: "label" }, label),
    el("div", { class: `value${isUnknown ? " unknown" : ""}` },
      isUnknown ? t("value.unknown") : value,
      opts.unit && !isUnknown ? el("small", {}, ` ${opts.unit}`) : null),
    note ? el("div", { class: "note", title: note }, note) : null,
    opts.bar !== undefined && opts.bar !== null && !isUnknown
      ? el("div", { class: `meter ${opts.barLevel || ""}` },
          el("span", { style: { width: `${Math.min(100, Math.max(0, opts.bar))}%` } }))
      : null,
    tip);
  if (tip) {
    const id = `summary-${Math.random().toString(36).slice(2, 9)}`;
    tip.id = id;
    node.setAttribute("aria-describedby", id);
    const fill = () => {
      const content = opts.summary();
      tip.replaceChildren(...(Array.isArray(content) ? content : [content]));
    };
    node.addEventListener("mouseenter", fill);
    node.addEventListener("focus", fill);
    // a tap on a phone toggles it
    node.addEventListener("click", () => { fill(); node.classList.toggle("show-summary"); });
    node.addEventListener("blur", () => node.classList.remove("show-summary"));
    fill();
  }
  return node;
}

export function emptyState(title, detail) {
  return el("div", { class: "empty" }, el("strong", {}, title), detail || null);
}

/* An error, in one plain sentence, with what to do and the technical
   detail behind "Show details" (open in Technical mode). */
export function problem(message, detail = null, action = null) {
  return el("div", { class: "banner error", role: "alert" },
    el("div", { class: "grow" }, message,
      detail ? foldable(t("action.show_details"), el("pre", { class: "detail mono" }, detail)) : null),
    action);
}

export async function loadInto(node, loader) {
  node.append(el("div", { class: "empty", "aria-busy": "true" }, t("status.loading")));
  try {
    const content = await loader();
    node.replaceChildren(content);
  } catch (err) {
    node.replaceChildren(problem(err.message));
  }
}

export function table(headers, rows, opts = {}) {
  // wrapped so a wide table scrolls inside its box instead of widening the page
  return el("div", { class: "table-wrap" }, el("table", { class: opts.class || null },
    el("thead", {}, el("tr", {}, headers.map((h) => el("th", {}, h)))),
    el("tbody", {}, rows.map((cells) => el("tr", {}, cells.map((cell) =>
      el("td", {}, cell instanceof Node ? cell : String(cell ?? "—"))))))));
}

/* A row of label/value pairs. Values that are null show as not known. */
export function detailRows(pairs) {
  return el("div", { class: "rows" }, pairs.filter(Boolean).map(([label, value, mono]) =>
    el("div", { class: "row" },
      el("span", { class: "row-label" }, label),
      el("span", { class: `row-value${mono ? " mono" : ""}${known(value) ? "" : " unknown"}`,
        title: typeof value === "string" ? value : "" },
        known(value) ? value : t("value.unknown")))));
}
