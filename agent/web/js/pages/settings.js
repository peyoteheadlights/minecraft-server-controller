/* One server's own settings, in its sheet: name and color, what happens
   after a crash, memory, CPU cores, how many backups to keep, and taking
   it off the list. App-wide settings are behind the gear. */

import { api } from "../api.js";
import { render } from "../nav.js";
import { crossplayPanel } from "../panels/crossplay.js";
import { loadServerTypes, versionCard } from "../panels/version.js";
import { loadServers, serverRow } from "../servers.js";
import { renderers, state } from "../state.js";
import { t, technical } from "../strings.js";
import { advanced, busy, card, confirmDialog, el, fmt, loadInto, section, toast, withHelp } from "../ui.js";

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

/* ------------------------------------------------------------ sleep when empty */

function sleepCard(own) {
  const settings = own.server;
  const sleep = state.status && state.status.sleep;
  const on = el("input", { type: "checkbox", checked: settings.autosleep ? "checked" : false });
  const minutes = el("input", { type: "number", min: "1", max: "1440", step: "1",
    value: String(settings.autosleep_minutes) });
  // Only what was measured: the count, and what it is waiting for.
  const live = !settings.autosleep ? t("serverset.sleep_off")
    : !sleep ? t("value.unknown")
    : sleep.list_answered === false ? t("serverset.sleep_no_answer")
    : sleep.players_online === null ? t("serverset.sleep_unknown_players")
    : sleep.players_online > 0 ? t("serverset.sleep_players", { count: sleep.players_online })
    : sleep.stops_in !== null ? t("serverset.sleep_countdown", { duration: fmt.duration(sleep.stops_in) })
    : t("serverset.sleep_waiting");
  return section(t("serverset.sleep"), null,
    withHelp(el("label", { class: "switch" }, on, t("serverset.sleep_label")), "autosleep", "configuration"),
    el("div", { class: "grid cols-2 mt-10" },
      field("sleep-minutes", t("serverset.sleep_minutes"), minutes, t("serverset.sleep_minutes_hint"))),
    el("p", { class: "hint" }, live),
    el("p", { class: "hint" }, t("serverset.sleep_restart_note")),
    el("div", { class: "btn-row mt-12" }, saveButton(t("action.save"), () => {
      const updates = {};
      if (on.checked !== Boolean(settings.autosleep)) updates["server.autosleep"] = on.checked;
      if (Number(minutes.value) !== Number(settings.autosleep_minutes)) {
        updates["server.autosleep_minutes"] = Number(minutes.value);
      }
      return updates;
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
    withHelp(el("span", { class: "help-label" }, t("serverset.keep_label")), "keep_backups", "backups"),
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

/* ------------------------------------------------------------ duplicate */

/* A new server with the same software, add-ons and game settings. The
   copy runs as a job; the new server's tab appears when it is checked. */
async function duplicateCard() {
  let suggestion;
  try {
    suggestion = await api(serverUrl("/duplicate"));
  } catch (err) {
    return card(t("dup.title"), el("p", { class: "hint mt-0" }, err.message));
  }
  const name = el("input", { id: "dup-name", maxlength: "60", value: suggestion.name, autocomplete: "off" });
  const folder = el("input", { id: "dup-folder", maxlength: "400", class: "mono",
    value: suggestion.directory, autocomplete: "off" });
  const choice = (value, labelKey, hintKey, checked) => el("label", { class: "choice" },
    el("input", { type: "radio", name: "dup-world", value, checked: checked ? "checked" : false }),
    el("span", { class: "choice-text" }, el("strong", {}, t(labelKey)), el("span", { class: "hint" }, t(hintKey))));
  const world = el("div", { class: "choices", role: "radiogroup", "aria-label": t("dup.world") },
    choice("copy", "dup.world_copy", "dup.world_copy_hint", true),
    choice("fresh", "dup.world_fresh", "dup.world_fresh_hint", false));
  const button = el("button", { class: "btn primary", type: "button" }, t("dup.button"));
  button.addEventListener("click", () => {
    if (!name.value.trim() || !folder.value.trim()) { toast(t("add.need_name_and_folder"), "warn"); return; }
    const picked = world.querySelector("input:checked");
    busy(button, t("dup.starting"), async () => {
      try {
        await api(serverUrl("/duplicate"), { method: "POST",
          body: { name: name.value.trim(), directory: folder.value.trim(), world: picked ? picked.value : "copy" } });
        toast(t("dup.started", { name: name.value.trim() }), "success", 9000);
      } catch (err) { toast(err.message, "error", 12000); }
    });
  });
  return card(t("dup.title"),
    el("p", { class: "hint mt-0" }, t("dup.intro")),
    el("div", { class: "grid cols-2" },
      field("dup-name", t("dup.name"), name),
      field("dup-folder", t("dup.folder"), folder, t("dup.folder_hint"))),
    el("div", { class: "field" }, el("span", { class: "field-label" }, t("dup.world")), world),
    suggestion.running ? el("p", { class: "hint" }, t("dup.running")) : null,
    suggestion.crossplay ? el("p", { class: "hint" }, t("dup.crossplay")) : null,
    el("div", { class: "btn-row mt-12" }, button, el("span", { class: "hint" }, t("dup.after"))));
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
  await loadServerTypes();
  const [own, version, crossplay, duplicate] = await Promise.all([
    api(serverUrl("/settings")),
    api(serverUrl("/version")),
    crossplayPanel(() => render()),
    duplicateCard(),
  ]);
  return el("div", { class: "stack" },
    identityCard(own),
    versionCard(version, () => render()),
    crossplay,
    crashCard(own),
    sleepCard(own),
    cpuCard(own.cpu, own.server.cpu_cores || []),
    backupsCard(own),
    advancedCard(own),
    duplicate,
    removeCard());
});
