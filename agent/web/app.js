/* Minecraft Server Control - dashboard.
   Plain JavaScript served by the agent itself: no build step, no framework,
   nothing to install on the Minecraft PC. The session token lives in
   sessionStorage and travels in an Authorization header, never in a URL.

   Every value shown comes from the agent. When the agent does not know
   something, the interface says "Unknown" rather than showing a default. */

(function () {
  "use strict";

  // ==================================================================
  // state
  // ==================================================================
  const state = {
    token: sessionStorage.getItem("mcsc_token") || "",
    user: "",
    status: null,
    console: [],
    consoleLimit: 1000,
    autoscroll: true,
    paused: false,
    filter: "",
    page: "dashboard",
    socket: null,
    connected: false,
    reconnectDelay: 1000,
    pageTimer: null,
    clock: null,
    pendingAction: null,
    startingSince: null,
    latestCrash: null,
    refreshTimer: null,
  };

  // [key, label, group, icon]. Keys are the URL hashes and must not change.
  const PAGES = [
    ["dashboard", "Overview", "Server", "overview"],
    ["console", "Console", "Server", "console"],
    ["players", "Players", "Server", "players"],
    ["performance", "Performance", "Server", "performance"],
    ["backups", "Backups", "Manage", "backups"],
    ["mods", "Mods", "Manage", "mods"],
    ["schedules", "Schedules", "Manage", "schedules"],
    ["events", "Events", "Activity", "events"],
    ["crashes", "Crash history", "Activity", "crashes"],
    ["settings", "Settings", "System", "settings"],
    ["security", "Security", "System", "security"],
  ];

  const STATES = {
    ONLINE: { label: "Online", tone: "success" },
    OFFLINE: { label: "Offline", tone: "danger" },
    STARTING: { label: "Starting…", tone: "warning", busy: true },
    STOPPING: { label: "Stopping…", tone: "warning", busy: true },
    RESTARTING: { label: "Restarting…", tone: "warning", busy: true },
    // crashed, with an automatic restart counting down
    RESTART_PENDING: { label: "Crashed", tone: "danger" },
    CRASHED: { label: "Crashed", tone: "danger" },
    UNKNOWN: { label: "Status unknown", tone: "neutral" },
  };

  const CAUSES = {
    OutOfMemoryError: "the server ran out of memory",
    JavaHeapError: "Java could not reserve the configured memory",
    JavaVersionIncompatible: "the installed Java version does not match this Minecraft version",
    ModDependencyError: "a mod is missing a dependency, or has the wrong version of one",
    MissingMod: "a required mod is not installed",
    IncompatibleMod: "two installed mods are incompatible",
    MixinError: "a mod failed to apply its changes to the game",
    FabricLoaderError: "Fabric Loader refused to start",
    ClassNotFoundException: "a mod was built for a different game version",
    NoSuchMethodError: "installed mods do not match each other's versions",
    WorldChunkError: "world data could not be loaded or saved",
    DiskStorageError: "the disk is full or not writable",
    PortInUse: "the server port is already in use",
    EulaNotAccepted: "the Minecraft EULA has not been accepted",
    NetworkError: "a network error",
    ServerThreadCrash: "an error in the main server thread",
  };

  const $ = (sel) => document.querySelector(sel);

  function el(tag, props = {}, ...children) {
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

  // ==================================================================
  // icons: one consistent set, 24px grid, 1.6 stroke, monochrome
  // ==================================================================
  const ICONS = {
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

  function icon(name) {
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

  // ==================================================================
  // formatting
  // ==================================================================
  const fmt = {
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
  const known = (v) => v !== null && v !== undefined;

  // ==================================================================
  // api
  // ==================================================================
  async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (options.body && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    let response;
    try {
      response = await fetch(`/api${path}`, Object.assign({}, options, { headers }));
    } catch (err) {
      throw new Error("The agent could not be reached. Check that it is running and that "
        + "this device is connected to Tailscale.");
    }
    const isJson = (response.headers.get("content-type") || "").includes("application/json");
    const payload = isJson ? await response.json() : await response.text();
    // A 401 from sign-in means the password was wrong, not that a session
    // expired, so it is reported as the server worded it.
    if (response.status === 401 && path !== "/auth/login") {
      signOut(true);
      throw new Error("Your session ended. Sign in again.");
    }
    if (!response.ok) {
      throw new Error((payload && payload.detail) || `The request failed (${response.status}).`);
    }
    return payload;
  }

  // ==================================================================
  // feedback: announcements, toasts, dialogs, busy buttons
  // ==================================================================
  function announce(text) {
    const node = $("#announcer");
    node.textContent = "";
    setTimeout(() => { node.textContent = text; }, 50);
  }

  function toast(message, level = "info", ms = 5200, action = null) {
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
  function confirmDialog({ title, body, confirmLabel = "Confirm", danger = false, extra = null,
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
  async function busy(button, label, fn) {
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

  // ==================================================================
  // appearance
  // ==================================================================
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || "system";
  }

  function setTheme(mode) {
    if (mode === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", mode);
    try {
      if (mode === "system") localStorage.removeItem("mcsc_theme");
      else localStorage.setItem("mcsc_theme", mode);
    } catch (e) { /* appearance still applies for this visit */ }
    renderRail();
  }

  // ==================================================================
  // authentication
  // ==================================================================
  $("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = $("#login-error");
    const button = event.target.querySelector("button[type=submit]");
    error.hidden = true;
    await busy(button, "Signing in…", async () => {
      try {
        const result = await api("/auth/login", {
          method: "POST",
          body: {
            username: $("#username").value,
            password: $("#password").value,
            label: navigator.userAgent.slice(0, 60),
          },
        });
        state.token = result.token;
        state.user = result.user;
        sessionStorage.setItem("mcsc_token", state.token);
        $("#password").value = "";
        startApp();
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
      }
    });
  });

  function signOut(expired) {
    if (state.socket) {
      state.socket.onclose = null;
      try { state.socket.close(); } catch (e) { /* already closed */ }
    }
    if (!expired && state.token) api("/auth/logout", { method: "POST" }).catch(() => {});
    state.token = "";
    sessionStorage.removeItem("mcsc_token");
    clearTimers();
    $("#app").classList.remove("visible");
    $("#login").style.display = "grid";
    if (expired) {
      $("#login-error").textContent = "Your session ended. Sign in again.";
      $("#login-error").hidden = false;
    }
  }

  // ==================================================================
  // live connection
  // ==================================================================
  function connectSocket() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${location.host}/ws`);
    state.socket = socket;

    socket.onopen = () => socket.send(JSON.stringify({ type: "auth", token: state.token }));
    socket.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch (e) { return; }
      if (message.type === "ready") {
        setLink(true);
        state.reconnectDelay = 1000;
        state.status = message.status;
        state.console = message.console || [];
        updateStatusViews();
        if (state.page === "console") renderConsoleLines();
        else if (state.page === "dashboard") render();
      } else if (message.type === "event" && message.event) {
        handleEvent(message.event);
      } else if (message.type === "console_tail") {
        state.console = message.lines;
        renderConsoleLines();
      } else if (message.type === "error") {
        signOut(true);
      }
    };
    socket.onclose = () => {
      if (state.socket !== socket) return;
      setLink(false);
      setTimeout(() => { if (state.token) connectSocket(); }, state.reconnectDelay);
      state.reconnectDelay = Math.min(state.reconnectDelay * 1.7, 20000);
    };
    socket.onerror = () => socket.close();
  }

  function setLink(connected) {
    if (state.connected !== connected) {
      announce(connected ? "Connected to the server agent." : "Connection to the agent lost. Reconnecting.");
    }
    state.connected = connected;
    const node = $("#connection");
    if (!node) return;
    node.replaceChildren(
      el("span", { class: `status-dot tone-${connected ? "success" : "warning"}` }),
      el("span", { class: "label" }, connected ? "Connected" : "Reconnecting…"));
    node.title = connected ? "Live updates are connected" : "Reconnecting to the agent";
  }

  const NOTABLE = {
    server_started: "success", server_stopped: "info", server_crashed: "error",
    server_recovered: "success", crash_loop: "error", restart_cancelled: "info", tps_detection_failed: "warn",
    backup_completed: "success", backup_failed: "error", backup_restored: "warn",
    mod_installed: "success", mod_removed: "warn", mod_updated: "success",
    mod_rolled_back: "warn", high_ram: "warn", high_cpu: "warn", low_disk: "warn",
    low_tps: "warn", high_mspt: "warn", notification_failed: "warn",
    maintenance_mode: "info", schedule_finished: "info", certificate_expiring: "warn",
    certificate_problem: "error",
  };

  function friendly(event) {
    const data = event.data || {};
    switch (event.type) {
      case "server_started": return "The server is online.";
      case "server_stopped": return "The server stopped.";
      case "server_crashed": {
        const code = known(data.exit_code) ? ` Exit code ${data.exit_code}.` : "";
        return `The server stopped unexpectedly.${code}`;
      }
      case "server_recovered": return "The server restarted after a crash and is online again.";
      case "crash_loop": return "Automatic restart is paused: the server crashed repeatedly.";
      default: return event.message || event.type;
    }
  }

  function handleEvent(event) {
    const data = event.data || {};
    if (event.type === "console") {
      if (state.paused) return;
      state.console.push(data);
      if (state.console.length > state.consoleLimit) state.console.splice(0, 200);
      if (state.page === "console") appendConsoleLine(data);
      if (state.page === "dashboard") overviewConsoleAppend(data);
      if (state.status && state.status.state === "STARTING") updateStatusViews();
      return;
    }
    if (event.type === "state") {
      if (state.status) {
        state.status.state = data.state;
        // Take the exit details from the event itself. Keeping the previous
        // values until the next refresh showed a stale exit code as current.
        if ("exit_code" in data) state.status.last_exit_code = data.exit_code;
        if ("reason" in data) state.status.last_exit_reason = data.reason;
        state.status.restart_at = data.state === "RESTART_PENDING" ? (data.restart_at || null) : null;
        if (data.state === "CRASHED") state.latestCrash = null;
        if (data.state === "ONLINE") state.latestCrash = null;
      }
      if (data.state === "STARTING") state.startingSince = event.ts;
      announce(`Server ${(STATES[data.state] || STATES.UNKNOWN).label.replace("…", "")}.`);
      updateStatusViews();
      scheduleRefresh();
      return;
    }
    if (event.type === "metrics") {
      if (state.status) {
        state.status.metrics = data;
        // each sample carries the latest measured tick figures
        if ("tps" in data) state.status.tps = data.tps;
        if ("mspt" in data) state.status.mspt = data.mspt;
      }
      if (state.page === "dashboard") overviewUpdate();
      return;
    }
    if (event.type.startsWith("tps_")) {
      scheduleRefresh();   // detection started, found a command, or found none
      if (event.type !== "tps_detection_failed") return;
    }
    if (event.type === "player_joined" || event.type === "player_left") {
      scheduleRefresh();
      if (state.page === "players") render();
      return;
    }
    if (event.type === "server_crashed") loadLatestCrash();  // the record now exists
    const level = NOTABLE[event.type];
    if (level) {
      const action = event.type === "server_crashed" || event.type === "crash_loop"
        ? { label: "View details", onClick: () => navigate("crashes") } : null;
      toast(friendly(event), level, level === "error" ? 9000 : 5200, action);
      scheduleRefresh();
      if (["events", "crashes", "mods", "backups"].includes(state.page)) render();
    }
  }

  function scheduleRefresh() {
    clearTimeout(state.refreshTimer);
    state.refreshTimer = setTimeout(refreshStatus, 350);
  }

  async function refreshStatus() {
    try {
      state.status = await api("/status");
      if (state.status.state === "STARTING" && !state.startingSince) state.startingSince = state.status.started_at;
      updateStatusViews();
    } catch (e) { /* the connection indicator reports the outage */ }
  }

  function renderStatus() { updateStatusViews(); }

  function updateStatusViews() {
    const status = state.status || {};
    const info = STATES[status.state] || STATES.UNKNOWN;
    const line = $("#sidebar-state");
    if (line) {
      line.replaceChildren(
        el("span", { class: `status-dot tone-${info.tone}${info.busy ? " pulse" : ""}` }),
        info.label);
    }
    const nameNode = $("#sidebar-name");
    if (nameNode && status.name) nameNode.textContent = status.name;
    if (state.page === "dashboard") overviewUpdate();
  }

  // ==================================================================
  // navigation
  // ==================================================================
  function renderRail() {
    const rail = $("#sidebar");
    rail.replaceChildren();
    const status = state.status || {};
    rail.append(el("div", { class: "sidebar-head" },
      el("div", { class: "server-name", id: "sidebar-name" }, status.name || "Minecraft server"),
      el("div", { class: "server-state", id: "sidebar-state" })));

    let group = null, list = null;
    for (const [key, label, groupName, iconName] of PAGES) {
      if (groupName !== group) {
        group = groupName;
        list = el("div", { class: "nav-group", role: "group", "aria-label": groupName },
          el("div", { class: "nav-group-label", "aria-hidden": "true" }, groupName));
        rail.append(list);
      }
      list.append(el("a", {
        class: "nav-item",
        href: `#${key}`,
        title: label,
        "aria-current": state.page === key ? "page" : null,
        onclick: (event) => { event.preventDefault(); navigate(key); },
      }, icon(iconName), el("span", { class: "label" }, label)));
    }

    const theme = currentTheme();
    const themeButton = (mode, iconName, label) => el("button", {
      type: "button", title: label, "aria-label": label,
      "aria-pressed": theme === mode ? "true" : "false",
      onclick: () => setTheme(mode),
    }, icon(iconName));
    rail.append(el("div", { class: "sidebar-foot" },
      el("div", { class: "connection", id: "connection", role: "status" }),
      el("div", { class: "segmented", role: "group", "aria-label": "Appearance" },
        themeButton("system", "system", "Match system appearance"),
        themeButton("light", "sun", "Light appearance"),
        themeButton("dark", "moon", "Dark appearance")),
      el("button", { class: "signout", type: "button", title: "Sign out", onclick: () => signOut(false) },
        icon("signout"), el("span", { class: "label" }, "Sign out"))));
    setLink(state.connected);
    updateStatusViews();
  }

  function setNavOpen(open) {
    $("#app").classList.toggle("nav-open", open);
    $("#menu-button").setAttribute("aria-expanded", open ? "true" : "false");
  }

  function navigate(page) {
    state.page = page;
    if (location.hash !== `#${page}`) history.replaceState(null, "", `#${page}`);
    setNavOpen(false);
    renderRail();
    render();
    $("#main").focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }

  window.addEventListener("hashchange", () => {
    const page = location.hash.replace("#", "");
    if (PAGES.some(([key]) => key === page) && page !== state.page) navigate(page);
  });

  $("#menu-button").append(icon("menu"));
  $("#menu-button").addEventListener("click", () =>
    setNavOpen(!$("#app").classList.contains("nav-open")));
  $("#app").addEventListener("click", (event) => {
    if ($("#app").classList.contains("nav-open") && !event.target.closest(".sidebar, #menu-button")) {
      setNavOpen(false);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("#app").classList.contains("nav-open")) setNavOpen(false);
  });

  // ==================================================================
  // page rendering and shared components
  // ==================================================================
  function clearTimers() {
    if (state.pageTimer) { clearInterval(state.pageTimer); state.pageTimer = null; }
    if (state.clock) { clearInterval(state.clock); state.clock = null; }
  }

  function render() {
    const page = $("#page");
    const entry = PAGES.find(([key]) => key === state.page) || PAGES[0];
    $("#page-title").textContent = entry[1];
    document.title = `${entry[1]} - Minecraft Server Control`;
    clearTimers();
    overview.nodes = null;
    $("#toolbar-actions").replaceChildren();
    page.replaceChildren();
    page.className = `page ${state.page}-page`;
    // restart the entrance transition
    void page.offsetWidth;
    const renderer = renderers[state.page];
    if (renderer) renderer(page, $("#toolbar-actions"));
  }

  /* A titled group in the macOS "grouped form" style: the heading sits
     above the box, not inside it. Used by every page. */
  function card(title, ...children) {
    return el("section", { class: "section" },
      title ? el("div", { class: "section-head" }, el("h2", {}, title)) : null,
      el("div", { class: "group-box" }, ...children));
  }

  /* A small statistic. Unknown values are shown as "Unknown", never as 0. */
  function metric(label, value, note, opts = {}) {
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

  function emptyState(title, detail) {
    return el("div", { class: "empty" }, el("strong", {}, title), detail || null);
  }

  async function loadInto(node, loader) {
    node.append(el("div", { class: "empty", "aria-busy": "true" }, "Loading…"));
    try {
      const content = await loader();
      node.replaceChildren(content);
    } catch (err) {
      node.replaceChildren(el("div", { class: "banner error", role: "alert" }, err.message));
    }
  }

  const renderers = {};

  // ==================================================================
  // Overview
  // ==================================================================
  const overview = { nodes: null };

  function startingStage() {
    const since = state.startingSince || 0;
    const recent = state.console.filter((l) => !l.ts || l.ts >= since - 1).slice(-60);
    const text = recent.map((l) => l.raw).join("\n");
    if (/Preparing (spawn area|level|start region)/i.test(text)) return "Loading the world";
    if (/Starting Minecraft server on|Starting minecraft server version/i.test(text)) return "Starting the server";
    if (/Loading \d+ mods|with Fabric Loader/i.test(text)) return "Loading mods";
    return "Launching Java";
  }

  function heroDetail(s) {
    const versions = s.minecraft_version
      ? `Minecraft ${s.minecraft_version}${s.fabric_loader ? ` with Fabric Loader ${s.fabric_loader}` : ""}.`
      : "";
    switch (s.state) {
      case "ONLINE":
        return [el("strong", {}, `Up for ${fmt.duration(s.uptime)}.`), " ", versions];
      case "STARTING": {
        const elapsed = state.startingSince ? ` ${Math.max(0, Math.round(Date.now() / 1000 - state.startingSince))}s` : "";
        return [el("strong", {}, `${startingStage()}…`), elapsed ? ` ${elapsed.trim()} so far.` : ""];
      }
      case "STOPPING": return ["Saving the world and shutting down."];
      case "RESTARTING": return ["Stopping the server, then starting it again."];
      case "RESTART_PENDING":
      case "CRASHED": {
        const parts = ["The server stopped unexpectedly."];
        if (known(s.last_exit_code)) parts.push(` Exit code ${s.last_exit_code}.`);
        const crash = state.latestCrash;
        if (crash && crash.category && crash.category !== "Unknown" && CAUSES[crash.category]) {
          const lead = { confirmed: "Cause", likely: "Likely cause", possible: "Possible cause" }[crash.confidence] || "Possible cause";
          parts.push(" ", el("strong", {}, `${lead}: ${CAUSES[crash.category]}.`));
        } else if (crash) {
          parts.push(" The cause could not be determined from the log.");
        } else {
          parts.push(" Reading the crash report…");
        }
        if (s.auto_restart_blocked) parts.push(" Automatic restart is paused.");
        else if (s.auto_restart_cancelled) parts.push(" Automatic restart cancelled.");
        if (s.state === "RESTART_PENDING") {
          const left = restartSecondsLeft(s);
          parts.push(el("div", { class: "countdown", role: "timer", "aria-live": "off" },
            left > 0 ? `Restarting in ${left}s` : "Starting server…"));
        }
        return parts;
      }
      case "OFFLINE":
        return [s.last_exit_reason === "force_killed" ? "The server was force stopped."
          : s.last_exit_reason ? "The server is stopped." : "The server is not running.",
          versions ? ` Last run: ${versions}` : ""];
      default:
        return ["The agent has not confirmed whether the server is running yet."];
    }
  }

  function heroActions(s) {
    const busyState = (STATES[s.state] || {}).busy || state.pendingAction;
    const buttons = [];
    if (s.state === "ONLINE") {
      buttons.push(el("button", { class: "btn", type: "button", disabled: busyState,
        onclick: (e) => serverAction("restart", e.currentTarget) }, "Restart"));
      buttons.push(el("button", { class: "btn danger", type: "button", disabled: busyState,
        onclick: (e) => serverAction("stop", e.currentTarget) }, "Stop Server"));
    } else if (s.state === "STARTING" || s.state === "STOPPING" || s.state === "RESTARTING") {
      const label = STATES[s.state].label;
      buttons.push(el("button", { class: "btn is-busy", type: "button", disabled: true, "aria-busy": "true" },
        el("span", { class: "spinner", "aria-hidden": "true" }), label));
    } else if (s.state === "RESTART_PENDING") {
      // The normal Start button is not offered here: the server enforces this
      // too, so a second start cannot race the automatic one.
      buttons.push(el("button", { class: "btn plain", type: "button",
        onclick: () => (state.latestCrash ? showCrash(state.latestCrash.id) : navigate("crashes")) },
        "View Crash Details"));
      buttons.push(el("button", { class: "btn", type: "button", disabled: state.pendingAction,
        onclick: (e) => pendingRestartAction("cancel", e.currentTarget) }, "Cancel"));
      buttons.push(el("button", { class: "btn primary", type: "button", disabled: state.pendingAction,
        onclick: (e) => pendingRestartAction("now", e.currentTarget) }, "Restart Now"));
    } else if (s.state === "CRASHED") {
      buttons.push(el("button", { class: "btn plain", type: "button",
        onclick: () => (state.latestCrash ? showCrash(state.latestCrash.id) : navigate("crashes")) },
        "View Crash Details"));
      buttons.push(el("button", { class: "btn primary", type: "button", disabled: busyState,
        onclick: (e) => serverAction("start", e.currentTarget) }, "Start Server"));
    } else {
      buttons.push(el("button", { class: "btn primary", type: "button",
        disabled: busyState || s.state === "UNKNOWN",
        onclick: (e) => serverAction("start", e.currentTarget) }, "Start Server"));
    }
    return buttons;
  }

  function tpsNote(s) {
    const t = s.tps_status || {};
    if (known(s.tps)) return t.command ? `via ${t.command}` : null;
    if (t.state === "detecting") return "Detecting…";
    if (t.state === "unavailable") return "No TPS command found";
    if (t.state === "disabled") return "Turned off";
    return s.state === "ONLINE" ? "Waiting for a reading" : "Server not running";
  }

  function overviewStats(s) {
    const m = s.metrics || {};
    const limit = fmt.xmx(s.memory);
    const proc = fmt.memory(m.proc_ram_mb);
    const players = known(s.players_online) ? `${s.players_online}` : null;
    return [
      metric("Players", players, players === null ? "Not reported yet" : null,
        { unit: players !== null && s.max_players ? `/ ${s.max_players}` : "" }),
      metric("TPS", known(s.tps) ? s.tps.toFixed(1) : null, tpsNote(s)),
      metric("MSPT", known(s.mspt) ? s.mspt.toFixed(1) : null,
        known(s.mspt) ? null : "No tick-time source", { unit: "ms" }),
      metric("Server memory", proc,
        proc ? (limit ? `of ${limit} limit` : "measured") : (s.state === "ONLINE" ? "Not measured" : "Not running")),
      metric("CPU", known(m.cpu_percent) ? `${Math.round(m.cpu_percent)}%` : null, "Whole machine",
        { bar: m.cpu_percent, barLevel: m.cpu_percent > 90 ? "danger" : m.cpu_percent > 75 ? "warn" : "" }),
    ];
  }

  function detailRows(pairs) {
    return el("div", { class: "rows" }, pairs.map(([label, value, mono]) => el("div", { class: "row" },
      el("span", { class: "row-label" }, label),
      el("span", { class: `row-value${mono ? " mono" : ""}`, title: value || "" }, value || "Unknown"))));
  }

  function logLine(line) {
    const raw = line.raw || "";
    const m = /^\[(\d{2}:\d{2}:\d{2})\]\s?(.*)$/s.exec(raw);
    const time = m ? m[1] : (line.ts ? fmt.clock(line.ts) : "");
    const text = m ? m[2] : raw;
    return el("div", { class: `log-line ${line.level || "INFO"} ${line.source || ""}` },
      el("span", { class: "time" }, time),
      el("span", { class: "msg" }, text));
  }

  function overviewUpdate() {
    const n = overview.nodes;
    if (!n || state.page !== "dashboard") return;
    const s = state.status || {};
    const info = STATES[s.state] || STATES.UNKNOWN;
    n.dot.className = `status-dot lg tone-${info.tone}${info.busy ? " pulse" : ""}`;
    n.title.textContent = info.label;
    n.title.style.color = ["CRASHED", "RESTART_PENDING"].includes(s.state) ? "var(--danger)" : "";
    n.detail.replaceChildren(...heroDetail(s));
    if (n.actionsState !== `${s.state}|${state.pendingAction}|${s.auto_restart_blocked}`) {
      n.actionsState = `${s.state}|${state.pendingAction}|${s.auto_restart_blocked}`;
      n.actions.replaceChildren(...heroActions(s));
    }
    n.stats.replaceChildren(...overviewStats(s));
    n.notices.replaceChildren(...overviewNotices(s));

    const players = s.players || [];
    n.players.replaceChildren(!known(s.players_online)
      ? emptyState("Player list not reported yet", "It appears when a player joins or the server answers /list.")
      : players.length
        ? detailRows(players.map((p) => [p.username, `Online for ${fmt.duration(p.session_seconds)}`]))
        : emptyState("No players online"));

    const m = s.metrics || {};
    n.details.replaceChildren(detailRows([
      ["Minecraft", s.minecraft_version || (s.state === "ONLINE" ? null : "Detected when the server starts")],
      ["Fabric Loader", s.fabric_loader || (s.state === "ONLINE" ? null : "Detected when the server starts")],
      ["Java", fmt.java(s.java_version)],
      ["Port", known(s.port) ? String(s.port) : null],
      ["Mods loaded", known(s.mod_count) ? String(s.mod_count) : (s.state === "ONLINE" ? null : "Reported at startup")],
      ["Disk free", known(m.disk_free_gb) ? fmt.gb(m.disk_free_gb) : null],
    ]));
  }

  function overviewNotices(s) {
    const notices = [];
    if (s.maintenance) {
      notices.push(el("div", { class: "banner info", role: "status" },
        el("div", { class: "grow" }, el("strong", {}, "Maintenance mode is on. "),
          "Automatic restarts and scheduled tasks are paused."),
        el("button", { class: "btn small", type: "button",
          onclick: (e) => busy(e.currentTarget, "Turning off…", async () => {
            await api("/maintenance", { method: "POST", body: { enabled: false } });
            toast("Maintenance mode is off.", "success");
            refreshStatus();
          }) }, "Turn Off")));
    }
    if (s.auto_restart_blocked) {
      notices.push(el("div", { class: "banner error", role: "alert" },
        el("div", { class: "grow" }, el("strong", {}, "Automatic restart is paused. "),
          `The server crashed repeatedly (${s.auto_restart_block_reason}). Fix the cause, then allow restarts again.`),
        el("button", { class: "btn small", type: "button",
          onclick: (e) => busy(e.currentTarget, "Allowing…", async () => {
            await api("/server/clear-crash-block", { method: "POST" });
            toast("Automatic restarts are allowed again.", "success");
            refreshStatus();
          }) }, "Allow Restarts")));
    }
    return notices;
  }

  function overviewConsoleAppend(line) {
    const body = overview.nodes && overview.nodes.console;
    if (!body) return;
    const empty = body.querySelector(".empty");
    if (empty) empty.remove();
    body.append(logLine(line));
    while (body.children.length > 40) body.firstChild.remove();
    body.scrollTop = body.scrollHeight;
  }

  async function loadLatestCrash() {
    try {
      const data = await api("/crashes?limit=1");
      state.latestCrash = (data.crashes || [])[0] || null;
      overviewUpdate();
    } catch (e) { state.latestCrash = null; }
  }

  renderers.dashboard = (page) => {
    const s = state.status || {};
    const nodes = {
      dot: el("span", { class: "status-dot lg", "aria-hidden": "true" }),
      title: el("h2", { id: "server-state-title" }),
      detail: el("p", { class: "hero-detail", id: "server-state-detail" }),
      actions: el("div", { class: "hero-actions" }),
      notices: el("div"),
      stats: el("div", { class: "stats", role: "group", "aria-label": "Server statistics" }),
      players: el("div"),
      details: el("div"),
      console: el("div", { class: "console-body", role: "log", "aria-label": "Recent console output" }),
    };
    overview.nodes = nodes;

    page.append(
      nodes.notices,
      el("div", { class: "hero", role: "region", "aria-labelledby": "server-state-title" },
        el("div", { class: "hero-main" },
          el("div", { class: "hero-state" }, nodes.dot, nodes.title),
          nodes.detail),
        nodes.actions),
      nodes.stats,
      el("div", { class: "columns gap-section" },
        el("section", { class: "section" },
          el("div", { class: "section-head" }, el("h2", {}, "Players online")),
          el("div", { class: "group-box" }, nodes.players)),
        el("section", { class: "section" },
          el("div", { class: "section-head" }, el("h2", {}, "Server")),
          el("div", { class: "group-box" }, nodes.details))),
      el("section", { class: "section gap-section" },
        el("div", { class: "section-head" }, el("h2", {}, "Recent console"), el("div", { class: "grow" }),
          el("button", { class: "btn plain small", type: "button", onclick: () => navigate("console") },
            "Open Console")),
        el("div", { class: "console console-preview" }, nodes.console)));

    const lines = state.console.slice(-12);
    if (lines.length) lines.forEach((l) => nodes.console.append(logLine(l)));
    else nodes.console.append(emptyState("No console output yet", "Start the server to see its log here."));

    overviewUpdate();
    requestAnimationFrame(() => { nodes.console.scrollTop = nodes.console.scrollHeight; });
    if (s.state === "CRASHED" || s.state === "RESTART_PENDING") loadLatestCrash();

    state.clock = setInterval(() => {
      const st = state.status || {};
      if (st.state === "ONLINE" && known(st.uptime)) {
        st.uptime += 1;
        if (overview.nodes) overview.nodes.detail.replaceChildren(...heroDetail(st));
      } else if ((st.state === "STARTING" || st.state === "RESTART_PENDING") && overview.nodes) {
        overview.nodes.detail.replaceChildren(...heroDetail(st));
      }
    }, 1000);
    // live events keep this current; a slow poll covers anything missed
    state.pageTimer = setInterval(refreshStatus, 15000);
  };

  // The deadline comes from the agent (restart_at), so every open dashboard
  // counts down to the same moment; the browser only formats it.
  function restartSecondsLeft(s) {
    if (known(s.restart_at)) return Math.max(0, Math.ceil(s.restart_at - Date.now() / 1000));
    if (known(s.restart_in)) return Math.max(0, Math.ceil(s.restart_in));
    return 0;
  }

  async function pendingRestartAction(kind, button) {
    if (state.pendingAction) return;
    state.pendingAction = kind;
    try {
      await busy(button, kind === "now" ? "Starting…" : "Cancelling…", async () => {
        try {
          await api(kind === "now" ? "/server/restart-now" : "/server/cancel-restart", { method: "POST" });
          // no local toast: the restart_cancelled event notifies every open dashboard
        } catch (err) {
          toast(err.message, "error", 8000);
        }
      });
    } finally {
      state.pendingAction = null;
      await refreshStatus();
    }
  }

  async function serverAction(action, button) {
    if (state.pendingAction) return;
    if (action === "stop") {
      const ok = await confirmDialog({
        title: "Stop the Minecraft server?",
        body: "Players will be disconnected. The world is saved before the server shuts down.",
        confirmLabel: "Stop Server",
        danger: true,
      });
      if (!ok) return;
    } else if (action === "restart") {
      const ok = await confirmDialog({
        title: "Restart the Minecraft server?",
        body: "Players will be disconnected while the server stops and starts again.",
        confirmLabel: "Restart",
      });
      if (!ok) return;
    }
    const labels = { start: "Starting…", stop: "Stopping…", restart: "Restarting…" };
    state.pendingAction = action;
    if (action === "start") state.startingSince = Date.now() / 1000;
    overviewUpdate();
    const target = (overview.nodes && overview.nodes.actions.querySelector("button:not(.plain)")) || button;
    try {
      await busy(target, labels[action], async () => {
        try {
          const result = await api(`/server/${action}`, { method: "POST", body: {} });
          // success is announced by the server_stopped event, once, on every dashboard
          if (action === "restart" && result.result !== "VERIFIED") {
            toast("Restart requested. The server is starting.", "info");
          }
        } catch (err) {
          toast(err.message, "error", 9000);
        }
      });
    } finally {
      state.pendingAction = null;
      await refreshStatus();
    }
  }

  // ==================================================================
  // Console
  // ==================================================================
  function consoleVisible() {
    const needle = state.filter.toLowerCase();
    return needle
      ? state.console.filter((line) => (line.raw || "").toLowerCase().includes(needle))
      : state.console;
  }

  function nearBottom(node) {
    return node.scrollHeight - node.scrollTop - node.clientHeight < 40;
  }

  function renderConsoleLines() {
    const wrap = $("#console-wrap");
    if (!wrap) return;
    const lines = consoleVisible().slice(-state.consoleLimit);
    if (!lines.length) {
      wrap.replaceChildren(state.filter
        ? emptyState("No matching lines", `Nothing in the recent output contains "${state.filter}".`)
        : emptyState("No console output yet", "Start the server to see its log here."));
      return;
    }
    const fragment = document.createDocumentFragment();
    lines.forEach((line) => fragment.append(logLine(line)));
    wrap.replaceChildren(fragment);
    if (state.autoscroll) wrap.scrollTop = wrap.scrollHeight;
  }

  function appendConsoleLine(line) {
    const wrap = $("#console-wrap");
    if (!wrap) return;
    if (state.filter && !(line.raw || "").toLowerCase().includes(state.filter.toLowerCase())) return;
    // follow the newest line only when the reader has not scrolled up
    const follow = state.autoscroll && nearBottom(wrap);
    const empty = wrap.querySelector(".empty");
    if (empty) empty.remove();
    wrap.append(logLine(line));
    while (wrap.children.length > state.consoleLimit) wrap.firstChild.remove();
    if (follow) wrap.scrollTop = wrap.scrollHeight;
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      const area = el("textarea", { style: "position:fixed;opacity:0" });
      area.value = text;
      document.body.append(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      return ok;
    }
  }

  renderers.console = (page, toolbar) => {
    const toggle = (label, iconName, key, title) => {
      const button = el("button", {
        class: "btn small", type: "button", title, "aria-pressed": state[key] ? "true" : "false",
        onclick: () => {
          state[key] = !state[key];
          button.setAttribute("aria-pressed", state[key] ? "true" : "false");
          if (key === "autoscroll" && state.autoscroll) {
            const wrap = $("#console-wrap");
            if (wrap) wrap.scrollTop = wrap.scrollHeight;
          }
          if (key === "paused" && !state.paused) renderConsoleLines();
          announce(`${label} ${state[key] ? "on" : "off"}.`);
        },
      }, icon(iconName), label);
      return button;
    };

    const filter = el("input", {
      class: "input", type: "search", placeholder: "Filter", "aria-label": "Filter console lines",
      value: state.filter,
      oninput: (e) => { state.filter = e.target.value; renderConsoleLines(); },
    });
    toolbar.append(
      el("div", { class: "search" }, icon("search"), filter),
      toggle("Auto-scroll", "follow", "autoscroll", "Follow new lines as they arrive"),
      toggle("Pause", "pause", "paused", "Stop adding new lines while you read"),
      el("button", {
        class: "btn small", type: "button", title: "Copy the visible lines",
        onclick: async () => {
          const ok = await copyText(consoleVisible().map((l) => l.raw).join("\n"));
          toast(ok ? "Copied the visible console lines." : "Copying is not available in this browser.",
            ok ? "success" : "warn");
        },
      }, icon("copy"), "Copy"),
      el("button", {
        class: "btn small", type: "button", title: "Download the recent console output",
        onclick: () => {
          const body = consoleVisible().map((l) => l.raw).join("\n");
          const url = URL.createObjectURL(new Blob([body], { type: "text/plain" }));
          const link = el("a", { href: url, download: `console-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.log` });
          document.body.append(link); link.click(); link.remove();
          URL.revokeObjectURL(url);
        },
      }, icon("download"), "Download"),
      el("button", {
        class: "btn small", type: "button",
        title: "Clear this view. The server's own log files are not changed.",
        onclick: async (e) => {
          await busy(e.currentTarget, "Clearing…", async () => {
            await api("/logs/clear", { method: "POST" });
            state.console = [];
            renderConsoleLines();
          });
          toast("Console view cleared. The server's log files are unchanged.", "info");
        },
      }, icon("clear"), "Clear"));

    const wrap = el("div", { class: "console-body", id: "console-wrap", role: "log",
                             "aria-label": "Server console output", tabindex: "0" });
    const input = el("input", {
      class: "input", type: "text", placeholder: "Type a Minecraft command, for example: say Hello",
      "aria-label": "Minecraft command", autocomplete: "off", spellcheck: "false",
      onkeydown: (event) => { if (event.key === "Enter") sendCommand(input, send); },
    });
    const send = el("button", { class: "btn primary small", type: "button",
                                onclick: () => sendCommand(input, send) }, "Send");
    page.append(
      el("div", { class: "console" },
        wrap,
        el("div", { class: "console-foot" }, el("span", { class: "prompt", "aria-hidden": "true" }, ">"), input, send)),
      el("p", { class: "hint" },
        "Commands go to the Minecraft server only, never to Windows. Commands that affect players ask for confirmation first. ",
        el("button", {
          class: "btn plain small", type: "button",
          onclick: async (e) => {
            await busy(e.currentTarget, "Loading…", async () => {
              const data = await api("/logs?lines=500");
              state.console = data.lines;
              renderConsoleLines();
            });
          },
        }, "Load the last 500 lines")));
    renderConsoleLines();
    input.focus({ preventScroll: true });
  };

  async function sendCommand(input, button) {
    const command = input.value.trim();
    if (!command) return;
    try {
      const check = await api(`/server/command/check?command=${encodeURIComponent(command)}`);
      if (!check.valid && check.error && !check.danger_reason) {
        toast(check.error, "error", 8000);
        return;
      }
      if (check.danger_reason) {
        const ok = await confirmDialog({
          title: `Run "${command}"?`,
          body: check.danger_reason,
          confirmLabel: "Run Command",
          danger: true,
        });
        if (!ok) return;
      }
      await busy(button, "Sending…", async () => {
        await api("/server/command", { method: "POST", body: { command, confirm: true } });
      });
      input.value = "";
      input.focus();
    } catch (err) {
      toast(err.message, "error", 8000);
    }
  }

  // ---------------- players ----------------
  renderers.players = (page) => loadInto(page, async () => {
    const data = await api("/players");
    const holder = el("div");
    holder.append(card(`Online now (${data.online.length} of ${data.max_players})`,
      data.online.length
        ? table(["Player", "UUID", "This session"], data.online.map((p) => [
            p.username, el("span", { class: "mono" }, p.uuid || "—"), fmt.duration(p.session_seconds)]))
        : el("div", { class: "empty" }, "Nobody is online")));
    holder.append(el("div", { class: "gap-section" },
      card("Everyone seen on this server",
        data.known.length
          ? table(["Player", "First seen", "Last seen", "Sessions", "Total playtime"],
              data.known.map((p) => [
                p.username, fmt.time(p.first_seen), fmt.time(p.last_seen),
                String(p.sessions), fmt.duration(p.total_seconds_live)]))
          : el("div", { class: "empty" }, "No players recorded yet"))));
    holder.append(el("p", { class: "hint", style: "margin-top:12px" },
      "Player IP addresses are deliberately not recorded."));
    return holder;
  });

  function table(headers, rows) {
    // wrapped so a wide table scrolls inside its box instead of widening the page
    return el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {}, headers.map((h) => el("th", {}, h)))),
      el("tbody", {}, rows.map((cells) => el("tr", {}, cells.map((cell) =>
        el("td", {}, cell instanceof Node ? cell : String(cell ?? "—"))))))));
  }

  // ---------------- performance ----------------
  renderers.performance = (page) => {
    const tpsPanel = el("div");
    const rest = el("div", { class: "gap-section" });
    page.append(tpsPanel, rest);
    if (window.MCSC.ext.tps) window.MCSC.ext.tps(tpsPanel);
    return renderPerformance(rest);
  };

  const renderPerformance = (page) => loadInto(page, async () => {
    const [data, health] = await Promise.all([api("/performance?hours=6"), api("/health/server")]);
    const holder = el("div");
    const current = data.current;

    holder.append(el("div", { class: "grid cols-4" },
      metric("CPU", fmt.pct(current.cpu_percent), `threshold ${data.thresholds.cpu_percent}%`,
        { bar: current.cpu_percent }),
      metric("RAM", fmt.pct(current.ram_percent), `threshold ${data.thresholds.ram_percent}%`,
        { bar: current.ram_percent }),
      metric("Disk free", fmt.gb(current.disk_free_gb), `alert under ${data.thresholds.disk_free_gb} GB`),
      metric("Network", `${(current.net_recv_mb_s || 0).toFixed(2)}`, "MB/s received", {})));

    holder.append(el("div", { class: "gap-section" },
      card("Last 6 hours",
        chart(data.history, "cpu_percent", "CPU %"),
        chart(data.history, "ram_used_mb", "RAM used (MB)"),
        data.history.some((h) => h.tps !== null)
          ? chart(data.history, "tps", "TPS")
          : el("p", { class: "hint" },
              "No TPS samples: no tick-rate command answered on this server."))));

    holder.append(el("div", { class: "grid cols-2", style: "margin-top:14px" },
      card("Health checks",
        el("div", { class: "banner", style: "margin-bottom:10px" },
          el("strong", {}, ({
            "ALL CHECKS VERIFIED": "All checks verified",
            "PARTIALLY VERIFIED": "Partially verified",
            "ATTENTION NEEDED": "Attention needed",
          })[health.overall] || health.overall),
          health.note ? el("div", { class: "hint" }, health.note) : null,
          health.unverified && health.unverified.length
            ? el("div", { class: "hint" }, `Not verified: ${health.unverified.join(", ")}`)
            : null),
        health.checks.map((check) => el("div", { class: "check" },
          el("span", { class: "name" }, check.name),
          el("span", { class: `val tag ${check.status === "ok" ? "ok" : check.status === "unknown" ? "off" : "warn"}` },
            check.value === null || check.value === undefined ? "unknown" : String(check.value)),
          el("span", { class: "detail" },
            check.detail
            + (check.threshold !== null && check.threshold !== undefined ? ` (limit ${check.threshold})` : "")
            + (check.source ? ` [source: ${check.source}]` : ""))))),
      card("Storage", table(["Category", "Size"], [
        ["Worlds", fmt.gb(data.storage.worlds_gb)],
        ["Backups", fmt.gb(data.storage.backups_gb)],
        ["Mods", fmt.gb(data.storage.mods_gb)],
        ["Logs", fmt.gb(data.storage.logs_gb)],
        ["Other server files", fmt.gb(data.storage.other_gb)],
        ["Free on drive", fmt.gb(data.storage.free_gb)],
      ]))));
    return holder;
  });

  function chart(history, key, label) {
    const width = 560, height = 140, pad = 4;
    const points = history.map((h) => h[key]).filter((v) => v !== null && v !== undefined);
    if (points.length < 2) return el("p", { class: "hint" }, `${label}: not enough samples yet`);
    const max = Math.max(...points) * 1.15 || 1;
    const step = (width - pad * 2) / (points.length - 1);
    const path = points.map((value, index) =>
      `${index === 0 ? "M" : "L"}${(pad + index * step).toFixed(1)},${(height - pad - (value / max) * (height - pad * 2)).toFixed(1)}`
    ).join(" ");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("class", "chart");
    svg.setAttribute("preserveAspectRatio", "none");
    const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
    line.setAttribute("d", path);
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", "var(--accent)");
    line.setAttribute("stroke-width", "1.6");
    svg.append(line);
    return el("div", { style: "margin-bottom:14px" },
      el("div", { class: "chart-legend" },
        el("span", {}, label),
        el("span", {}, `peak ${Math.max(...points).toFixed(1)}`)),
      svg);
  }

  // ---------------- backups ----------------
  renderers.backups = (page) => loadInto(page, async () => {
    const [data, worlds] = await Promise.all([api("/backups"), api("/worlds")]);
    const holder = el("div");

    holder.append(el("div", { class: "btn-row", style: "margin-bottom:14px" },
      el("button", {
        class: "btn primary",
        onclick: async () => {
          toast("Backup started. Large worlds take a while.");
          try {
            const result = await api("/backups", { method: "POST", body: {} });
            toast(`Backup verified: ${result.name} `
              + `(${result.verification ? result.verification.entries + " entries" : ""})`,
              "info", 8000);
            render();
          } catch (err) { toast(err.message, "error"); }
        },
      }, "Back up now"),
      el("button", {
        class: "btn",
        onclick: async () => {
          try { await api("/worlds/save", { method: "POST" }); toast("save-all flush sent"); }
          catch (err) { toast(err.message, "error"); }
        },
      }, "Save world now")));

    holder.append(card("Worlds", table(["World", "Size", "Last modified", "Last backup"],
      worlds.worlds.map((w) => [
        w.label,
        w.exists ? fmt.bytes(w.size_bytes) : "not present",
        w.exists ? fmt.time(w.modified) : "—",
        w.last_backup ? `${w.last_backup.name} (${fmt.ago(w.last_backup.created_at)})` : "never",
      ]))));

    holder.append(el("div", { class: "gap-section" },
      card(`Backups (keeping ${data.retention.daily} daily, ${data.retention.weekly} weekly, ${data.retention.monthly} monthly)`,
        data.backups.length
          ? table(["Name", "Type", "Created", "Size", ""], data.backups.map((b) => [
              el("span", { class: "mono" }, b.name),
              el("span", { class: `tag ${b.kind === "manual" ? "ok" : b.kind === "safety" ? "warn" : ""}` }, b.kind),
              fmt.time(b.created_at),
              fmt.bytes(b.size_bytes),
              el("div", { class: "btn-row" },
                el("button", {
                  class: "btn small",
                  onclick: async () => {
                    const result = await api(`/backups/${b.id}/verify`);
                    toast(result.ok ? "Backup verified: archive and checksum are intact"
                                    : `Verify failed: ${result.reason}`, result.ok ? "info" : "error");
                  },
                }, "Verify"),
                el("a", { class: "btn small", href: `/api/backups/${b.id}/download`,
                          onclick: downloadWithToken }, "Download"),
                el("button", { class: "btn small", onclick: () => restoreBackup(b) }, "Restore"),
                el("button", {
                  class: "btn small danger",
                  onclick: async () => {
                    const ok = await confirmDialog({
                      title: `Delete ${b.name}?`,
                      body: "The archive file is deleted from disk. This cannot be undone.",
                      confirmLabel: "Delete backup", danger: true,
                    });
                    if (!ok) return;
                    await api(`/backups/${b.id}`, { method: "DELETE" });
                    toast("Backup deleted"); render();
                  },
                }, "Delete")),
            ]))
          : el("div", { class: "empty" }, "No backups yet"))));
    return holder;
  });

  async function downloadWithToken(event) {
    // Fetch with the bearer header, then hand the blob to the browser, so the
    // token never travels in a URL.
    event.preventDefault();
    const href = event.currentTarget.getAttribute("href");
    toast("Preparing download…");
    const response = await fetch(href, { headers: { Authorization: `Bearer ${state.token}` } });
    if (!response.ok) { toast("Download failed", "error"); return; }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = el("a", { href: url, download: href.split("/").pop() });
    document.body.append(link); link.click(); link.remove();
    URL.revokeObjectURL(url);
  }

  async function restoreBackup(backup) {
    const preview = await api(`/backups/${backup.id}/restore`, { method: "POST", body: { confirm: false } });
    const startAfter = el("input", { type: "checkbox" });
    const body = el("div", {},
      el("p", {}, `Restore ${backup.name} from ${fmt.time(backup.created_at)}?`),
      el("ul", {}, preview.will_happen.map((item) => el("li", {}, item))),
      el("label", { style: "display:flex;gap:8px;align-items:center;margin-top:10px" },
        startAfter, "Start the server when the restore finishes"));
    const ok = await confirmDialog({
      title: "Restore this backup?", body, confirmLabel: "Verify and restore", danger: true,
    });
    if (!ok) return;
    toast("Restoring. The server will stop first.");
    try {
      const result = await api(`/backups/${backup.id}/restore`, {
        method: "POST",
        body: { confirm: true, start_after: startAfter.checked, safety_backup: true },
      });
      toast(`Restored ${result.restored}. Safety copy: ${result.safety_backup.name}`);
      render();
    } catch (err) { toast(err.message, "error"); }
  }

  // ---------------- mods ----------------
  renderers.mods = (page) => loadInto(page, async () => {
    const data = await api("/mods");
    const holder = el("div");
    const offline = data.server_state === "OFFLINE" || data.server_state === "CRASHED";

    if (!offline) {
      holder.append(el("div", { class: "banner" },
        `The server is ${(STATES[data.server_state] || STATES.UNKNOWN).label.replace("…", "").toLowerCase()}. `
        + "You can browse mods now. Installing, removing, enabling, disabling and updating "
        + "need the server stopped first."));
    }
    const others = data.problems.filter((p) => !["missing_dependency", "dependency_version"].includes(p.kind));
    if (others.length) {
      holder.append(el("div", { class: "banner error" },
        el("strong", {}, `${others.length} mod problem(s) found: `),
        el("ul", {}, others.slice(0, 6).map((p) => el("li", {}, p.detail)))));
    }
    const depPanel = el("div");
    holder.append(depPanel);
    if (window.MCSC.ext.dependencies) window.MCSC.ext.dependencies(depPanel, { offline: offline });

    const search = el("input", { type: "text", placeholder: "Search Modrinth for Fabric mods…",
      class: "mono", style: "flex:1;min-width:200px;padding:8px 11px;background:var(--bg);border:1px solid var(--line);border-radius:8px" });
    const results = el("div", { style: "margin-top:12px" });
    holder.append(card("Install from Modrinth",
      el("div", { class: "btn-row" }, search,
        el("button", {
          class: "btn primary",
          onclick: async () => {
            results.innerHTML = "";
            results.append(el("div", { class: "empty" }, "Searching Modrinth…"));
            try {
              const found = await api(`/mods/search?q=${encodeURIComponent(search.value)}&limit=10`);
              results.innerHTML = "";
              if (!found.hits.length) { results.append(el("div", { class: "empty" }, "Nothing found")); return; }
              results.append(table(["Mod", "Downloads", "Server side", ""], found.hits.map((hit) => [
                el("div", {}, el("strong", {}, hit.title),
                  el("div", { class: "hint" }, (hit.description || "").slice(0, 110))),
                Number(hit.downloads).toLocaleString(),
                hit.server_side || "?",
                el("button", { class: "btn small", disabled: !offline,
                  onclick: () => installMod(hit) }, "Install"),
              ])));
            } catch (err) {
              results.innerHTML = "";
              results.append(el("div", { class: "banner error" }, err.message));
            }
          },
        }, "Search")),
      results,
      el("p", { class: "hint", style: "margin-top:10px" },
        `Downloads are checked against the SHA-512 Modrinth publishes, and only .jar files from
         Modrinth's own CDN are accepted. Minecraft version in use: ${data.minecraft_version || "unknown"}.`)));

    holder.append(el("div", { class: "gap-section" },
      card(`Installed mods (${data.mods.length})`, !data.mods.length
        ? emptyState("No mods installed", "Search Modrinth above, or place .jar files in the mods folder.")
        : table(
        ["Mod", "Version", "Minecraft", "Status", "Update", ""],
        data.mods.map((mod) => [
          el("div", {}, el("strong", {}, mod.name),
            el("div", { class: "hint mono" }, mod.mod_id)),
          el("span", { class: "mono" }, mod.version || "—"),
          el("span", { class: "mono" }, mod.minecraft_range || "—"),
          el("span", { class: `tag ${mod.status === "ok" ? "ok" : mod.status === "disabled" ? "off" : mod.status}` },
            mod.enabled ? mod.status : "disabled"),
          mod.update_available
            ? el("span", { class: "tag warn" }, mod.update_available.latest_version)
            : "—",
          el("div", { class: "btn-row" },
            mod.update_available
              ? el("button", { class: "btn small", disabled: !offline,
                  onclick: () => updateMod(mod) }, "Update")
              : null,
            el("button", {
              class: "btn small", disabled: !offline,
              onclick: async () => {
                try {
                  await api(mod.enabled ? "/mods/disable" : "/mods/enable",
                    { method: "POST", body: { filename: mod.filename } });
                  toast(`${mod.name} ${mod.enabled ? "disabled" : "enabled"}`);
                  render();
                } catch (err) { toast(err.message, "error"); }
              },
            }, mod.enabled ? "Disable" : "Enable"),
            el("button", { class: "btn small", onclick: () => showVersions(mod) }, "History"),
            el("button", { class: "btn small danger", disabled: !offline,
              onclick: () => removeMod(mod) }, "Remove")),
        ])),
      el("p", { class: "hint", style: "margin-top:10px" },
        (data.claim || "") + ". " + (data.claim_note || "")),
      el("p", { class: "hint" },
        "What this checker cannot see: " + data.limitations.join(" ")))));

    holder.append(el("div", { class: "gap-section" }, await modHistoryCard()));
    return holder;
  });

  async function modHistoryCard() {
    const data = await api("/mods/history?limit=25");
    return card("Mod audit history", data.history.length
      ? table(["When", "Who", "Action", "Mod", "Change", "Result"], data.history.map((h) => [
          fmt.time(h.ts), h.user || "—", h.action, h.mod_name || h.mod_id || "—",
          h.old_version || h.new_version
            ? `${h.old_version || "—"} → ${h.new_version || "—"}` : "—",
          el("span", { class: `tag ${h.result === "ok" ? "ok" : "error"}` }, h.result),
        ]))
      : el("div", { class: "empty" }, "No mod changes recorded yet"));
  }

  async function installMod(hit) {
    let detail;
    try { detail = await api(`/mods/project/${hit.slug}`); }
    catch (err) { toast(err.message, "error"); return; }
    const latest = detail.versions[0];
    if (!latest) { toast("No Fabric build for this Minecraft version", "error"); return; }
    const deps = latest.dependencies.filter((d) => d.type === "required");
    const installDeps = el("input", { type: "checkbox" });
    const body = el("div", {},
      el("p", {}, `Install ${detail.project.title} ${latest.version_number} (${latest.release_type}).`),
      el("ul", {},
        el("li", {}, `File: ${latest.file.filename} (${fmt.bytes(latest.file.size)})`),
        el("li", {}, `Minecraft: ${latest.game_versions.join(", ")}`),
        el("li", {}, `Server side: ${detail.project.server_side}`),
        el("li", {}, `Licence: ${detail.project.license || "unknown"}`)),
      deps.length
        ? el("div", {},
            el("p", {}, el("strong", {}, `${deps.length} required dependency/dependencies declared.`)),
            el("label", { style: "display:flex;gap:8px;align-items:center" },
              installDeps, "Install required dependencies too"))
        : el("p", { class: "hint" }, "No required dependencies declared."),
      el("p", { class: "hint" },
        "The jar is downloaded from Modrinth's CDN and its checksum is verified before it is written."));
    const ok = await confirmDialog({ title: "Install this mod?", body, confirmLabel: "Back up and install" });
    if (!ok) return;
    try {
      const result = await api("/mods/install", {
        method: "POST",
        body: { project: hit.slug, version_id: latest.version_id,
                install_dependencies: installDeps.checked },
      });
      toast(`Installed ${result.installed.name} ${result.installed.version}. `
        + "Loaded by Minecraft: not verified - start the server to confirm.", "info", 9000);
      if (result.dependencies_required.some((d) => !d.installed) && !installDeps.checked) {
        toast("Required dependencies are missing. Open the mod list to see which.", "warn", 9000);
      }
      render();
    } catch (err) { toast(err.message, "error", 9000); }
  }

  async function updateMod(mod) {
    const ok = await confirmDialog({
      title: `Update ${mod.name}?`,
      // Built from text nodes, not an HTML string: version strings come from
      // a mod's own metadata and must never be parsed as markup.
      body: el("div", {},
        el("p", {}, `${mod.version} → ${mod.update_available.latest_version} `,
          `(${mod.update_available.release_type}).`),
        el("p", { class: "hint" },
          "The current jar is archived first, so you can roll back from History.")),
      confirmLabel: "Update mod",
    });
    if (!ok) return;
    try {
      const result = await api("/mods/update", {
        method: "POST",
        body: { filename: mod.filename, version_id: mod.update_available.version_id },
      });
      toast(`Updated to ${result.updated.version}. Loaded by Minecraft: not verified `
        + "- start the server to confirm, and roll back from History if startup fails.",
        "info", 9000);
      render();
    } catch (err) { toast(err.message, "error", 9000); }
  }

  async function removeMod(mod) {
    let impact;
    try { impact = await api(`/mods/impact?filename=${encodeURIComponent(mod.filename)}`); }
    catch (err) { toast(err.message, "error"); return; }
    const body = el("div", {},
      el("p", {}, `Remove ${mod.name} ${mod.version}?`),
      impact.warning ? el("div", { class: "banner error" }, impact.warning) : null,
      impact.dependents.length
        ? el("ul", {}, impact.dependents.map((d) => el("li", {}, `${d.name} requires ${d.requires}`)))
        : el("p", { class: "hint" }, "No installed mod declares this as a dependency."),
      el("p", { class: "hint" },
        "The jar is copied to mod-backups and then moved to mod-trash. It is not deleted outright."));
    const ok = await confirmDialog({
      title: "Remove this mod?", body, confirmLabel: "Back up and remove", danger: true,
    });
    if (!ok) return;
    try {
      await api("/mods/remove", { method: "POST", body: { filename: mod.filename } });
      toast(`${mod.name} removed and archived`);
      render();
    } catch (err) { toast(err.message, "error"); }
  }

  async function showVersions(mod) {
    const data = await api(`/mods/versions/${encodeURIComponent(mod.mod_id)}`);
    const body = data.versions.length
      ? table(["Version", "Archived", "File", ""], data.versions.map((v) => [
          el("span", { class: "mono" }, v.version || "—"),
          fmt.time(v.created_at),
          v.exists ? "on disk" : el("span", { class: "tag error" }, "missing"),
          v.is_current || !v.exists ? (v.is_current ? el("span", { class: "tag ok" }, "current") : "—")
            : el("button", {
                class: "btn small",
                onclick: async () => {
                  $("#modal-root").innerHTML = "";
                  const ok = await confirmDialog({
                    title: `Roll back to ${v.version}?`,
                    body: "The current jar is archived first, and the archived jar's SHA-256 "
                          + "is verified before it is restored.",
                    confirmLabel: "Roll back", danger: true,
                  });
                  if (!ok) return;
                  try {
                    await api("/mods/rollback", {
                      method: "POST",
                      body: { mod_id: mod.mod_id, archive_path: v.archive_path },
                    });
                    toast(`Rolled back to ${v.version}`);
                    render();
                  } catch (err) { toast(err.message, "error"); }
                },
              }, "Roll back"),
        ]))
      : el("div", { class: "empty" }, "No archived versions yet");
    await confirmDialog({ title: `${mod.name} version history`, body, confirmLabel: "Close" });
  }

  // ---------------- schedules ----------------
  renderers.schedules = (page) => loadInto(page, async () => {
    const data = await api("/schedules");
    const holder = el("div");
    const name = el("input", { type: "text", placeholder: "Nightly backup" });
    const task = el("select", {}, data.tasks.map((t) => el("option", { value: t }, t)));
    const kind = el("select", {}, ["daily", "weekly", "interval"].map((k) => el("option", { value: k }, k)));
    const expr = el("input", { type: "text", placeholder: "23:00 / sun 04:00 / 6h", class: "mono" });

    holder.append(card("Add a schedule",
      el("div", { class: "grid cols-4" },
        el("div", { class: "field" }, el("label", {}, "Name"), name),
        el("div", { class: "field" }, el("label", {}, "Task"), task),
        el("div", { class: "field" }, el("label", {}, "Repeat"), kind),
        el("div", { class: "field" }, el("label", {}, "When"), expr)),
      el("button", {
        class: "btn primary",
        onclick: async () => {
          try {
            await api("/schedules", {
              method: "POST",
              body: { name: name.value || task.value, task: task.value,
                      kind: kind.value, expr: expr.value, enabled: true, payload: {} },
            });
            toast("Schedule created"); render();
          } catch (err) { toast(err.message, "error"); }
        },
      }, "Create schedule")));

    holder.append(el("div", { class: "gap-section" },
      card("Schedules", data.schedules.length
        ? table(["Name", "Task", "When", "Next run", "Last result", ""], data.schedules.map((s) => [
            s.name, el("span", { class: "mono" }, s.task), el("span", { class: "mono" }, `${s.kind} ${s.expr}`),
            s.enabled ? fmt.time(s.next_run) : el("span", { class: "tag off" }, "disabled"),
            s.last_result || "—",
            el("div", { class: "btn-row" },
              el("button", {
                class: "btn small",
                onclick: async () => {
                  await api(`/schedules/${s.id}`, {
                    method: "PUT",
                    body: { name: s.name, task: s.task, kind: s.kind, expr: s.expr,
                            payload: s.payload, enabled: !s.enabled },
                  });
                  render();
                },
              }, s.enabled ? "Disable" : "Enable"),
              el("button", {
                class: "btn small",
                onclick: async () => {
                  const result = await api(`/schedules/${s.id}/run`, { method: "POST" });
                  toast(result.result);
                },
              }, "Run now"),
              el("button", {
                class: "btn small danger",
                onclick: async () => {
                  await api(`/schedules/${s.id}`, { method: "DELETE" });
                  toast("Schedule deleted"); render();
                },
              }, "Delete")),
          ]))
        : el("div", { class: "empty" }, "No schedules"))));
    return holder;
  });

  // ---------------- events ----------------
  renderers.events = (page) => loadInto(page, async () => {
    const data = await api("/events?limit=200");
    return card("Recent events", data.events.length
      ? table(["When", "Type", "Message"], data.events.map((e) => [
          fmt.time(e.ts),
          el("span", { class: `tag ${e.level === "error" ? "error" : e.level === "warn" ? "warn" : ""}` }, e.type),
          e.message,
        ]))
      : el("div", { class: "empty" }, "No events recorded"));
  });

  // ---------------- crashes ----------------
  renderers.crashes = (page) => loadInto(page, async () => {
    const data = await api("/crashes");
    if (!data.crashes.length) {
      return card("Crash history", el("div", { class: "empty" }, "No crashes recorded. Good."));
    }
    return card("Crash history", table(
      ["When", "Exit code", "Likely cause", "Confidence", ""],
      data.crashes.map((crash) => [
        fmt.time(crash.ts),
        el("span", { class: "mono" }, String(crash.exit_code)),
        crash.category,
        el("span", { class: `tag ${crash.confidence === "likely" ? "warn" : "off"}` }, crash.confidence),
        el("button", { class: "btn small", onclick: () => showCrash(crash.id) }, "Details"),
      ])));
  });

  async function showCrash(id) {
    const crash = await api(`/crashes/${id}`);
    const context = crash.context || {};
    const analysis = context.analysis || {};
    const body = el("div", {},
      el("p", {},
        el("strong", {}, `${(analysis.confidence || "unknown")}: `),
        analysis.category),
      analysis.evidence_basis ? el("p", { class: "hint" }, analysis.evidence_basis) : null,
      el("p", {}, analysis.summary || ""),
      analysis.advice ? el("p", { class: "hint" }, analysis.advice) : null,
      analysis.suspect_mods && analysis.suspect_mods.length
        ? el("p", {}, "Installed mods mentioned in the log: ",
            el("span", { class: "mono" }, analysis.suspect_mods.join(", ")),
            el("span", { class: "hint" },
              " - appearing in a stack trace is not evidence of causing the crash"))
        : null,
      el("h3", { style: "margin-top:16px;font-size:14px" }, "Evidence"),
      el("div", { class: "console-wrap", style: "height:auto;max-height:200px" },
        (crash.evidence || []).map((line) => el("div", { class: "console-line ERROR" }, line))),
      el("h3", { style: "margin-top:16px;font-size:14px" }, "Context"),
      table(["Field", "Value"], [
        ["Exit code", String(crash.exit_code)],
        ["Minecraft", context.minecraft_version || "unknown"],
        ["Fabric loader", context.fabric_loader || "unknown"],
        ["Java", context.java_version || "unknown"],
        ["Players online", (context.players_online || []).join(", ") || "none"],
        ["Crash report", context.crash_report || "none written by Minecraft"],
        ["Saved log", context.log_file || context.console_file || "—"],
      ]),
      el("p", { class: "hint", style: "margin-top:12px" },
        "This is a rule match on the log text, not a certainty. Check the evidence before acting."));
    await confirmDialog({ title: `Crash on ${fmt.time(crash.ts)}`, body, confirmLabel: "Close" });
  }

  // ---------------- settings ----------------
  renderers.settings = (page) => loadInto(page, async () => {
    const data = await api("/settings");
    const config = data.config;
    const holder = el("div");
    const pending = {};
    const track = (key, input, parse = (v) => v) => {
      input.addEventListener("change", () => { pending[key] = parse(input.value ?? input.checked); });
      return input;
    };

    const numberField = (key, label, value, note) => {
      const input = el("input", { type: "number", value: String(value), step: "any" });
      track(key, input, Number);
      return el("div", { class: "field" }, el("label", {}, label), input,
        note ? el("div", { class: "hint" }, note) : null);
    };
    const checkField = (key, label, checked) => {
      const input = el("input", { type: "checkbox", checked: checked ? "checked" : false });
      input.addEventListener("change", () => { pending[key] = input.checked; });
      return el("label", { style: "display:flex;gap:8px;align-items:center;padding:5px 0" }, input, label);
    };

    holder.append(card("Crash handling and restarts",
      el("div", { class: "grid cols-3" },
        el("div", {}, checkField("monitor.auto_restart", "Restart automatically after a crash", config.monitor.auto_restart)),
        numberField("monitor.restart_delay", "Delay before restart (seconds)", config.monitor.restart_delay),
        numberField("monitor.max_crashes", "Stop retrying after this many crashes", config.monitor.max_crashes,
          `within ${config.monitor.crash_window_minutes} minutes`))));

    holder.append(el("div", { class: "gap-section" }, card("Alert thresholds",
      el("div", { class: "grid cols-3" },
        numberField("thresholds.cpu_percent", "CPU alert above (%)", config.thresholds.cpu_percent),
        numberField("thresholds.ram_percent", "RAM alert above (%)", config.thresholds.ram_percent),
        numberField("thresholds.disk_free_gb", "Disk alert below (GB)", config.thresholds.disk_free_gb),
        numberField("thresholds.tps_min", "TPS alert below", config.thresholds.tps_min),
        numberField("thresholds.mspt_max", "MSPT alert above (ms)", config.thresholds.mspt_max),
        numberField("notifications.min_interval_seconds", "Minimum seconds between repeat alerts",
          config.notifications.min_interval_seconds)))));

    const eventChecks = Object.entries(config.notifications.events).map(([key, value]) =>
      checkField(`notifications.events.${key}`, key.replace(/_/g, " "), value));
    holder.append(el("div", { class: "gap-section" }, card("Notifications",
      el("div", { class: "grid cols-2" },
        el("div", {},
          checkField("notifications.discord_enabled", "Send to Discord", config.notifications.discord_enabled),
          el("div", { class: "hint" }, data.secrets.discord_webhook_configured
            ? "Webhook URL is configured in the agent's .env file."
            : "No webhook URL configured. Add MCSC_DISCORD_WEBHOOK to the agent's .env file."),
          el("button", {
            class: "btn small", style: "margin-top:8px",
            onclick: async () => {
              const result = await api("/notifications/test?channel=discord", { method: "POST" });
              toast(result.sent ? "Discord test sent" : "Discord test failed, see notification history",
                result.sent ? "info" : "error");
            },
          }, "Send test")),
        el("div", {},
          checkField("notifications.email_enabled", "Send email", config.notifications.email_enabled),
          el("div", { class: "hint" }, data.secrets.smtp_configured
            ? "SMTP credentials are configured in the agent's .env file."
            : "No SMTP password configured. Add MCSC_SMTP_USERNAME and MCSC_SMTP_PASSWORD to .env."),
          el("button", {
            class: "btn small", style: "margin-top:8px",
            onclick: async () => {
              const result = await api("/notifications/test?channel=email", { method: "POST" });
              toast(result.sent ? "Email test sent" : "Email test failed, see notification history",
                result.sent ? "info" : "error");
            },
          }, "Send test"))),
      el("h3", { class: "subheading" }, "Which events to send"),
      el("div", { class: "grid cols-3" }, eventChecks))));

    const startupResult = el("div", { style: "margin-top:10px" });
    holder.append(el("div", { class: "gap-section" }, card("Windows startup",
      el("p", { class: "hint" },
        "Checks the scheduled task that starts this agent with Windows, reads it back from "
        + "Windows, and shows what happened the last time the agent started."),
      el("button", {
        class: "btn small",
        onclick: async () => {
          startupResult.innerHTML = "";
          startupResult.append(el("div", { class: "empty" }, "Asking Windows..."));
          try {
            const r = await api("/system/startup");
            startupResult.innerHTML = "";
            const yesNo = (v) => v === true ? "yes" : v === false ? "no" : "unknown";
            const task = r.task || {};
            const runtime = r.runtime || {};
            const last = r.last_startup || {};
            const initialised = (last.events || []).some((e) => e.event === "controller_initialized");
            const verdictClass = r.verdict === "registered correctly" ? "ok"
              : r.verdict === "unsupported" ? "" : "error";
            startupResult.append(
              el("div", { class: `banner ${verdictClass}` }, el("strong", {}, r.verdict.toUpperCase())),
              table(["Check", "Result"], [
                ["Startup registration", r.registered === true ? "found"
                  : r.registered === false ? "not found" : "unknown"],
                ["Mechanism", r.mechanism || "none"],
                ["Mode", task.mode === "boot" ? "at boot (no login needed)"
                  : task.mode === "logon" ? "when you log in" : "-"],
                ["Registered executable", el("span", { class: "mono" }, task.command || "-")],
                ["Registered working directory", el("span", { class: "mono" }, task.working_directory || "-")],
                ["Points to this installation", yesNo(r.points_to_current_app)],
                ["Windows last run", runtime.last_run_time || "unknown"],
                ["Windows last result", runtime.last_result || "unknown"],
                ["Last startup recorded by agent", last.started_at
                  ? `${last.started_at} (launched by ${last.launched_by})` : "none recorded"],
                ["Controller initialised on that start", last.started_at ? (initialised ? "yes" : "no") : "-"],
              ]),
              (r.problems || []).length
                ? el("div", { class: "banner error", style: "margin-top:10px" },
                    el("strong", {}, "Problems"),
                    el("ul", {}, r.problems.map((p) => el("li", {}, p))))
                : null,
              el("p", { class: "hint" }, `Full log: ${r.startup_log}`));
          } catch (err) {
            startupResult.innerHTML = "";
            startupResult.append(el("div", { class: "banner error" }, err.message));
          }
        },
      }, "Test Windows Startup"),
      startupResult)));

    holder.append(el("div", { class: "gap-section" }, card("Maintenance mode",
      checkField("maintenance.enabled", "Pause automatic restarts and scheduled tasks",
        config.maintenance.enabled),
      el("button", {
        class: "btn small", style: "margin-top:8px",
        onclick: async () => {
          const next = !(state.status && state.status.maintenance);
          await api("/maintenance", { method: "POST", body: { enabled: next } });
          toast(`Maintenance mode ${next ? "on" : "off"}`);
          refreshStatus();
        },
      }, "Toggle maintenance mode now"))));

    holder.append(el("div", { style: "margin-top:16px" },
      el("button", {
        class: "btn primary",
        onclick: async () => {
          if (!Object.keys(pending).length) { toast("Nothing changed"); return; }
          try {
            const result = await api("/settings", { method: "PUT", body: { updates: pending } });
            toast(`Saved ${Object.keys(result.applied).length} setting(s)`);
            if (Object.keys(result.rejected).length) {
              toast(`Rejected: ${Object.keys(result.rejected).join(", ")}`, "warn");
            }
          } catch (err) { toast(err.message, "error"); }
        },
      }, "Save settings"),
      el("p", { class: "hint", style: "margin-top:10px" },
        "Secrets (Discord webhook, SMTP password, API token) are never edited here. "
        + "They live in the agent's .env file on the Minecraft PC.")));
    return holder;
  });

  // ---------------- security ----------------
  renderers.security = (page) => loadInto(page, async () => {
    const [data, audit] = await Promise.all([api("/security"), api("/security/audit?limit=100")]);
    const holder = el("div");
    const tls = data.tls || {};
    const certDays = tls.days_remaining;
    holder.append(el("div", { class: "grid cols-4" },
      metric("Agent", "connected", "this dashboard is talking to it"),
      metric("HTTPS",
        data.https_enabled === false ? "disabled"
          : (tls.parsed ? "certificate loaded" : null),
        data.https_enabled === false
          ? "plain HTTP - loopback only"
          : (tls.parsed
              ? `issued by ${tls.issuer || "unknown issuer"}`
              : (tls.parse_error || "the certificate could not be read"))),
      metric("Certificate expiry",
        certDays === null || certDays === undefined ? null : `${Math.round(certDays)}`,
        certDays === null || certDays === undefined
          ? "could not be read from the certificate file"
          : `days remaining (${tls.expiry_severity})`),
      metric("Tailscale",
        data.tailscale.connected === null ? null
          : (data.tailscale.connected ? "connected" : "not connected"),
        data.tailscale.detail),
      metric("Authentication", data.authentication.enabled ? "enabled" : "NOT SET",
        `sessions last ${data.authentication.session_hours}h`)));
    holder.append(el("div", { class: "grid cols-3", style: "margin-top:14px" },
      metric("Failed sign-ins", String(data.failed_logins_24h), "in the last 24 hours"),
      metric("Certificate covers", tls.covers_hostname === true ? "yes"
        : tls.covers_hostname === false ? "no" : null,
        data.dashboard_hostname
          ? `checked against ${data.dashboard_hostname}`
          : "tls.hostname is not configured, so this cannot be checked"),
      metric("Key matches certificate",
        tls.key_matches_certificate === true ? "yes"
          : tls.key_matches_certificate === false ? "no" : null,
        tls.key_check_error || "compared as public keys; the private key is never exposed")));

    holder.append(el("div", { class: "gap-section" }, card(
      `Active sessions (${data.active_sessions.length})`,
      data.active_sessions.length
        ? table(["User", "Signed in", "Last used", "From", "Device"], data.active_sessions.map((s) => [
            s.user, fmt.time(s.created_at), fmt.ago(s.last_used),
            el("span", { class: "mono" }, s.source_ip || "—"), (s.label || "").slice(0, 40)]))
        : el("div", { class: "empty" }, "No active sessions"),
      el("div", { class: "btn-row", style: "margin-top:12px" },
        el("button", {
          class: "btn small",
          onclick: async () => {
            const result = await api("/auth/rotate", { method: "POST" });
            state.token = result.token;
            sessionStorage.setItem("mcsc_token", state.token);
            toast("This session's token was rotated");
          },
        }, "Rotate my token"),
        el("button", {
          class: "btn small danger",
          onclick: async () => {
            const ok = await confirmDialog({
              title: "Sign every session out?",
              body: "All sessions, including this one, are revoked. You will sign in again.",
              confirmLabel: "Revoke all sessions", danger: true,
            });
            if (!ok) return;
            await api("/security/revoke-sessions", { method: "POST" });
            signOut(true);
          },
        }, "Revoke all sessions")))));

    holder.append(el("div", { class: "gap-section" }, card("Audit log",
      audit.entries.length
        ? table(["When", "User", "Action", "Target", "Result"], audit.entries.map((e) => [
            fmt.time(e.ts), e.user || "—", e.action, e.target || "—",
            el("span", { class: `tag ${e.result === "ok" ? "ok" : "error"}` }, e.result)]))
        : el("div", { class: "empty" }, "Nothing logged yet"))));

    holder.append(el("p", { class: "hint", style: "margin-top:12px" },
      `The agent is bound to ${data.bind_address}. Keep that address private to your tailnet;
       do not port-forward it.`));
    return holder;
  });

  // ------------------------------------------------------------------
  // boot
  // ------------------------------------------------------------------
  async function startApp() {
    $("#login").style.display = "none";
    $("#app").classList.add("visible");
    const hash = location.hash.replace("#", "");
    if (PAGES.some(([key]) => key === hash)) state.page = hash;
    try { state.status = await api("/status"); } catch (e) { return; }
    renderStatus();
    renderRail();
    render();
    connectSocket();
  }

  window.MCSC = {
    el, api, icon, card, metric, table, toast, confirmDialog, busy, emptyState, fmt, known,
    navigate, render, refreshStatus, getState: () => state, ext: window.MCSC_EXT || {},
  };

  if (state.token) {
    api("/auth/me").then(startApp).catch(() => signOut(true));
  }
})();
