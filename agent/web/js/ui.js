export const $ = (sel) => document.querySelector(sel);

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
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
  security: [["path", { d: "M12 3l7.5 3v5.5c0 4.5-3.1 8.2-7.5 9.5-4.4-1.3-7.5-5-7.5-9.5V6z" }], ["path", { d: "M9 12l2 2 4-4" }]],
  system: [["circle", { cx: 12, cy: 12, r: 8 }], ["path", { d: "M12 4a8 8 0 0 1 0 16z", fill: "currentColor", stroke: "none" }]],
  sun: [["circle", { cx: 12, cy: 12, r: 3.8 }], ["path", { d: "M12 2.8v2M12 19.2v2M2.8 12h2M19.2 12h2M5.5 5.5l1.4 1.4M17.1 17.1l1.4 1.4M5.5 18.5l1.4-1.4M17.1 6.9l1.4-1.4" }]],
  moon: [["path", { d: "M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z" }]],
  menu: [["path", { d: "M4 7h16M4 12h16M4 17h16" }]],
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

export const fmt = {
  bytes(n) {
    if (n === null || n === undefined) return "Unknown";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = Number(n), i = 0;
    while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
    return `${value.toFixed(value >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
  },
  gb(n) { return n === null || n === undefined ? "Unknown" : `${Number(n).toFixed(1)} GB`; },
  pct(n) { return n === null || n === undefined ? "Unknown" : `${Number(n).toFixed(0)}%`; },
  memory(mb) {
    if (mb === null || mb === undefined) return null;
    return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
  },
  duration(seconds) {
    if (seconds === null || seconds === undefined) return "Unknown";
    const s = Math.max(0, Math.floor(seconds));
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d) return `${d}d ${h}h`;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${s % 60}s`;
    return `${s}s`;
  },
  time(ts) {
    if (!ts) return "Never";
    return new Date(ts * 1000).toLocaleString(undefined,
      { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  },
  clock(ts) {
    return new Date(ts * 1000).toLocaleTimeString(undefined,
      { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  },
  ago(ts) {
    if (!ts) return "never";
    return `${fmt.duration(Date.now() / 1000 - ts)} ago`;
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

export const known = (v) => v !== null && v !== undefined;

export function announce(text) {
  const node = $("#announcer");
  node.textContent = "";
  setTimeout(() => { node.textContent = text; }, 50);
}

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

/* An Apple-style alert. Body may be a string (shown as text, never parsed
   as markup) or a DOM node. Resolves true when confirmed. */
export function confirmDialog({ title, body, confirmLabel = "Confirm", danger = false, extra = null,
                         cancelLabel = "Cancel", wide = false }) {
  const acknowledge = confirmLabel === "Close" || confirmLabel === "OK";
  return new Promise((resolve) => {
    const root = $("#modal-root");
    const previous = document.activeElement;
    const bodyNode = el("div", { class: "body", id: "dialog-body" });
    if (typeof body === "string") bodyNode.append(el("p", {}, body));
    else if (body) bodyNode.append(body);
    const close = (value) => {
      document.removeEventListener("keydown", onKey, true);
      root.innerHTML = "";
      if (previous && previous.focus) previous.focus();
      resolve(value);
    };
    const cancel = acknowledge ? null
      : el("button", { class: "btn", type: "button", onclick: () => close(false) }, cancelLabel);
    const confirm = el("button", {
      class: `btn ${danger ? "danger-filled" : "primary"}`, type: "button",
      onclick: () => close(true),
    }, confirmLabel);
    const onKey = (event) => {
      if (event.key === "Escape") { event.preventDefault(); close(false); }
      if (event.key === "Tab") {  // keep focus inside the dialog
        const focusable = [...root.querySelectorAll("button, input, select, textarea, a[href]")];
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
    // A destructive action starts on Cancel, as macOS does.
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

/* A titled group in the macOS "grouped form" style: the heading sits
   above the box, not inside it. Used by every page. */
export function card(title, ...children) {
  return el("section", { class: "section" },
    title ? el("div", { class: "section-head" }, el("h2", {}, title)) : null,
    el("div", { class: "group-box" }, ...children));
}

/* A small statistic. Unknown values are shown as "Unknown", never as 0. */
export function metric(label, value, note, opts = {}) {
  const unknown = !known(value);
  return el("div", { class: "stat" },
    el("div", { class: "label" }, label),
    el("div", { class: `value ${unknown ? "unknown" : ""}` },
      unknown ? "Unknown" : value,
      opts.unit && !unknown ? el("small", {}, ` ${opts.unit}`) : null),
    note ? el("div", { class: "note", title: note }, note) : null,
    opts.bar !== undefined && !unknown
      ? el("div", { class: `meter ${opts.barLevel || ""}` },
          el("span", { style: `width:${Math.min(100, Math.max(0, opts.bar))}%` }))
      : null);
}

export function emptyState(title, detail) {
  return el("div", { class: "empty" }, el("strong", {}, title), detail || null);
}

export async function loadInto(node, loader) {
  node.append(el("div", { class: "empty", "aria-busy": "true" }, "Loading…"));
  try {
    const content = await loader();
    node.replaceChildren(content);
  } catch (err) {
    node.replaceChildren(el("div", { class: "banner error", role: "alert" }, err.message));
  }
}

export function table(headers, rows) {
  // wrapped so a wide table scrolls inside its box instead of widening the page
  return el("div", { class: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, headers.map((h) => el("th", {}, h)))),
    el("tbody", {}, rows.map((cells) => el("tr", {}, cells.map((cell) =>
      el("td", {}, cell instanceof Node ? cell : String(cell ?? "—"))))))));
}
