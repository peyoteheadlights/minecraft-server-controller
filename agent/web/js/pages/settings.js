/* One server's own settings, in its sheet: name and color, what happens
   after a crash, memory, CPU cores, how many backups to keep, and taking
   it off the list. App-wide settings are behind the gear. */

import { api } from "../api.js";
import { render } from "../nav.js";
import { loadServers, serverRow } from "../servers.js";
import { renderers, state } from "../state.js";
import { t, technical } from "../strings.js";
import { advanced, busy, card, confirmDialog, el, loadInto, toast } from "../ui.js";

const serverUrl = (path) => `/servers/${encodeURIComponent(state.serverId)}${path}`;

// Keys the agent-wide /settings accepts. With only one server they are
// saved there, so a config.yaml with a single server: block keeps its shape.
const AGENT_KEYS = /^(monitor\.|backups\.|mods\.|server\.(max_players|stop_timeout|start_timeout|autostart_minecraft|jvm_args)$)/;

export async function saveServerSettings(updates) {
  const own = {}, agent = {};
  for (const [key, value] of Object.entries(updates)) {
    (state.servers.length < 2 && AGENT_KEYS.test(key) ? agent : own)[key] = value;
  }
  const results = [];
  if (Object.keys(own).length) {
    results.push(await api(serverUrl("/settings"), { method: "PUT", body: { updates: own } }));
  }
  if (Object.keys(agent).length) {
    results.push(await api("/settings", { method: "PUT", body: { updates: agent } }));
  }
  const rejected = results.flatMap((r) => Object.values(r.rejected));
  if (rejected.length) toast(rejected.join(" "), "error", 9000);
  return { results, ok: !rejected.length };
}

function saveButton(label, collect) {
  return el("button", {
    class: "btn primary", type: "button",
    onclick: (e) => busy(e.currentTarget, t("action.saving"), async () => {
      const updates = collect();
      if (!updates || !Object.keys(updates).length) { toast(t("settings.nothing_changed")); return; }
      try {
        const { ok } = await saveServerSettings(updates);
        if (ok) toast(t("settings.saved"), "success");
        await loadServers();
        render();
      } catch (err) { toast(err.message, "error"); }
    }),
  }, label);
}

function field(id, label, input, hint = null) {
  input.id = id;
  return el("div", { class: "field" }, el("label", { for: id }, label), input,
    hint ? el("div", { class: "hint" }, hint) : null);
}

/* ------------------------------------------------------------ name and color */

function identityCard(own) {
  const row = serverRow() || {};
  const name = el("input", { maxlength: "60", value: row.name || own.server.name });
  let chosen = own.color;
  const custom = el("input", { type: "color", value: (own.color || "#808080").toLowerCase(),
    "aria-label": t("serverset.custom_color") });
  const swatches = el("div", { class: "swatches", role: "radiogroup", "aria-label": t("serverset.color") },
    own.palette.map((p) => {
      const input = el("input", {
        type: "radio", name: "server-color", value: p.hex,
        checked: p.hex === own.color ? "checked" : false,
        "aria-label": t(`color.${p.id}`),
        onchange: () => { chosen = p.hex; custom.value = p.hex.toLowerCase(); },
      });
      const label = el("label", { class: "swatch-choice", title: t(`color.${p.id}`) }, input,
        el("span", { class: "swatch", "aria-hidden": "true" }));
      label.style.setProperty("--swatch", p.hex);
      return label;
    }),
    el("label", { class: "swatch-choice custom", title: t("serverset.custom_color") }, custom));
  custom.addEventListener("input", () => {
    chosen = custom.value.toUpperCase();
    for (const radio of swatches.querySelectorAll("input[type=radio]")) radio.checked = false;
  });
  return card(t("serverset.identity"),
    field("server-name", t("serverset.name"), name),
    el("div", { class: "field" }, el("span", { class: "field-label" }, t("serverset.color")), swatches),
    el("div", { class: "btn-row" },
      el("button", {
        class: "btn primary", type: "button",
        onclick: (e) => busy(e.currentTarget, t("action.saving"), async () => {
          try {
            if (name.value.trim() && name.value.trim() !== (row.name || own.server.name)) {
              await api(serverUrl("/settings"), { method: "PUT",
                body: { updates: { "server.name": name.value.trim() } } });
            }
            if (chosen && chosen !== own.color) {
              await api(serverUrl("/color"), { method: "PUT", body: { color: chosen } });
            }
            toast(t("settings.saved"), "success");
            await loadServers();
            render();
          } catch (err) { toast(err.message, "error"); }
        }),
      }, t("serverset.save_identity"))));
}

/* ------------------------------------------------------------ crashes */

function crashCard(own) {
  const m = own.monitor;
  const auto = el("input", { type: "checkbox", checked: m.auto_restart ? "checked" : false });
  const delay = el("input", { type: "number", min: "0", step: "1", value: String(m.restart_delay) });
  const max = el("input", { type: "number", min: "1", step: "1", value: String(m.max_crashes) });
  return card(t("serverset.crashes"),
    el("label", { class: "switch" }, auto, t("serverset.auto_restart")),
    advanced(t("serverset.crash_details"),
      el("div", { class: "grid cols-2" },
        field("restart-delay", t("serverset.restart_delay"), delay),
        field("max-crashes", t("serverset.max_crashes"), max,
          t("serverset.max_crashes_hint", { minutes: m.crash_window_minutes })))),
    el("div", { class: "btn-row mt-12" }, saveButton(t("action.save"), () => {
      const updates = {};
      if (auto.checked !== Boolean(m.auto_restart)) updates["monitor.auto_restart"] = auto.checked;
      if (Number(delay.value) !== Number(m.restart_delay)) updates["monitor.restart_delay"] = Number(delay.value);
      if (Number(max.value) !== Number(m.max_crashes)) updates["monitor.max_crashes"] = Number(max.value);
      return updates;
    })));
}

/* ------------------------------------------------------------ memory */

function xmxGb(args) {
  const found = args.map((a) => /^-Xmx(\d+)([mMgG])$/.exec(String(a))).filter(Boolean).pop();
  if (!found) return null;
  const n = Number(found[1]);
  return found[2].toLowerCase() === "g" ? n : Math.round((n / 1024) * 10) / 10;
}

function memoryCard(own) {
  const args = (own.server.jvm_args || []).map(String);
  const current = xmxGb(args);
  const gb = el("input", { type: "number", min: "1", max: "256", step: "0.5",
    value: current === null ? "" : String(current) });
  const raw = el("input", { class: "mono", value: args.join(" ") });
  return card(t("serverset.memory"),
    field("memory-limit", t("serverset.memory_limit"), gb,
      current === null ? t("serverset.memory_unset") : t("serverset.memory_hint")),
    advanced(t("serverset.launch_args"),
      field("jvm-args", t("serverset.jvm_args"), raw, t("serverset.jvm_args_hint"))),
    el("div", { class: "btn-row mt-12" }, saveButton(t("action.save"), () => {
      let next = raw.value.trim() ? raw.value.trim().split(/\s+/) : [];
      if (next.join(" ") === args.join(" ") && gb.value && Number(gb.value) !== current) {
        const value = Number(gb.value);
        const flag = Number.isInteger(value) ? `-Xmx${value}G` : `-Xmx${Math.round(value * 1024)}M`;
        next = next.filter((a) => !/^-Xmx/i.test(a)).concat(flag);
      }
      return next.join(" ") === args.join(" ") ? {} : { "server.jvm_args": next };
    })));
}

/* ------------------------------------------------------------ CPU cores */

/* Which CPU cores this server may use. What it really uses is read back
   from the running process; the boxes are only the setting. */
function cpuCard(info, configured) {
  const count = info.logical_cores;
  if (!info.supported || !count) {
    return card(t("serverset.cpu"), el("p", { class: "hint mt-0" },
      info.unsupported_reason || t("serverset.cpu_unreadable")));
  }
  const usedBy = {};
  for (const other of info.others) {
    for (const core of other.cores || []) (usedBy[core] = usedBy[core] || []).push(other.name);
  }
  const all = el("input", { type: "checkbox", checked: configured.length ? false : "checked" });
  const boxes = [];
  const grid = el("div", { class: "core-grid" });
  for (let core = 0; core < count; core += 1) {
    const box = el("input", {
      type: "checkbox", checked: configured.includes(core) ? "checked" : false,
      disabled: configured.length ? false : "disabled", "aria-label": t("serverset.core", { n: core + 1 }),
    });
    boxes.push(box);
    grid.append(el("label", { class: "core" }, box, t("serverset.core", { n: core + 1 }),
      usedBy[core] ? el("span", { class: "hint" }, t("serverset.core_shared", { names: usedBy[core].join(", ") })) : null));
  }
  grid.hidden = !configured.length;
  all.addEventListener("change", () => {
    grid.hidden = all.checked;
    for (const box of boxes) { box.disabled = all.checked; if (all.checked) box.checked = false; }
  });
  const status = info.status;
  const now = status.applied
    ? t("serverset.cores_now", {
      cores: status.applied.length === count ? t("serverset.every_core") : describe(status.applied),
    })
    : t("serverset.cores_unknown", { reason: status.applied_reason });
  return card(t("serverset.cpu"),
    el("label", { class: "check-row pad-y" }, all, t("serverset.all_cores", { count })),
    grid,
    el("p", { class: "hint mt-8" }, now),
    (status.problems || []).length ? el("div", { class: "banner error mt-8" }, status.problems[0]) : null,
    el("div", { class: "btn-row mt-10" },
      el("button", {
        class: "btn primary", type: "button",
        onclick: (e) => busy(e.currentTarget, t("action.saving"), async () => {
          const chosen = all.checked ? [] : boxes.flatMap((box, core) => (box.checked ? [core] : []));
          if (!all.checked && !chosen.length) { toast(t("serverset.pick_a_core"), "warn"); return; }
          try {
            const result = await api(serverUrl("/settings"),
              { method: "PUT", body: { updates: { "server.cpu_cores": chosen } } });
            if (result.rejected["server.cpu_cores"]) {
              toast(result.rejected["server.cpu_cores"], "error", 9000);
              return;
            }
            const live = result.cpu_cores;
            if (live && !live.ok) toast(t("serverset.cores_not_applied", { reason: live.reason }), "warn", 9000);
            else toast(live ? t("serverset.cores_applied") : t("serverset.cores_next_start"), "success");
            render();
          } catch (err) { toast(err.message, "error"); }
        }),
      }, t("action.save")),
      el("button", {
        class: "btn plain", type: "button",
        onclick: () => {
          all.checked = false;
          grid.hidden = false;
          boxes.forEach((box, core) => { box.disabled = false; box.checked = core < Math.ceil(count / 2); });
        },
      }, t("serverset.half_cores"))));
}

/* Cores as people count them, from 1, with runs shortened: "1-4, 7". */
function describe(cores) {
  const numbers = [...cores].sort((a, b) => a - b).map((c) => c + 1);
  const runs = [];
  let start = numbers[0], prev = numbers[0];
  for (const n of numbers.slice(1).concat([null])) {
    if (n !== null && n === prev + 1) { prev = n; continue; }
    runs.push(start === prev ? String(start) : `${start}-${prev}`);
    start = prev = n;
  }
  return runs.join(", ");
}

/* ------------------------------------------------------------ backups */

function backupsCard(own) {
  const b = own.backups;
  const inputs = ["daily", "weekly", "monthly"].map((kind) =>
    [kind, el("input", { type: "number", min: "0", step: "1", value: String(b[`keep_${kind}`]) })]);
  return card(t("serverset.backups"),
    el("div", { class: "grid cols-3" }, inputs.map(([kind, input]) =>
      field(`keep-${kind}`, t(`serverset.keep_${kind}`), input))),
    el("div", { class: "btn-row" }, saveButton(t("action.save"), () => {
      const updates = {};
      for (const [kind, input] of inputs) {
        if (Number(input.value) !== Number(b[`keep_${kind}`])) updates[`backups.keep_${kind}`] = Number(input.value);
      }
      return updates;
    })));
}

/* ------------------------------------------------------------ advanced, removal */

function advancedCard(own) {
  const s = own.server;
  const start = el("input", { type: "number", min: "10", step: "1", value: String(s.start_timeout) });
  const stop = el("input", { type: "number", min: "5", step: "1", value: String(s.stop_timeout) });
  return advanced(t("serverset.timing"),
    el("div", { class: "grid cols-2" },
      field("start-timeout", t("serverset.start_timeout"), start),
      field("stop-timeout", t("serverset.stop_timeout"), stop, t("serverset.stop_timeout_hint"))),
    el("div", { class: "btn-row" }, saveButton(t("action.save"), () => {
      const updates = {};
      if (Number(start.value) !== Number(s.start_timeout)) updates["server.start_timeout"] = Number(start.value);
      if (Number(stop.value) !== Number(s.stop_timeout)) updates["server.stop_timeout"] = Number(stop.value);
      return updates;
    })),
    technical() ? el("p", { class: "hint mono" }, t("serverset.folder", { folder: s.directory || "—" })) : null);
}

function removeCard() {
  const row = serverRow() || {};
  const last = state.servers.length < 2;
  return card(t("serverset.remove"),
    el("p", { class: "hint mt-0" }, last ? t("serverset.remove_last") : t("serverset.remove_hint")),
    el("button", {
      class: "btn danger", type: "button", disabled: last ? "disabled" : false,
      onclick: async () => {
        const ok = await confirmDialog({
          title: t("serverset.remove_title", { name: row.name }),
          body: t("serverset.remove_body"),
          confirmLabel: t("serverset.remove_confirm"), danger: true,
        });
        if (!ok) return;
        try {
          await api(`/servers/${encodeURIComponent(row.id)}`, { method: "DELETE" });
          toast(t("serverset.removed", { name: row.name }), "success");
          await loadServers();
          state.page = "servers";
          location.hash = "servers";
        } catch (err) { toast(err.message, "error", 9000); }
      },
    }, t("serverset.remove_button")));
}

renderers.settings = (page) => loadInto(page, async () => {
  await loadServers();
  const own = await api(serverUrl("/settings"));
  return el("div", { class: "stack" },
    identityCard(own),
    crashCard(own),
    memoryCard(own),
    cpuCard(own.cpu, own.server.cpu_cores || []),
    backupsCard(own),
    advancedCard(own),
    removeCard());
});
