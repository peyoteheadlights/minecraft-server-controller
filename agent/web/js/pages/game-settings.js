/* Game settings: the common server.properties values with normal
   controls. Only what the file says is shown; a key the file doesn't set
   says so, with the value Minecraft uses then. Saving checks every value
   on the agent first and keeps a copy of the old file (its undo is on the
   Backups page). Minecraft reads the file when it starts, so while the
   server runs the page says the change waits for a restart.

   The memory slider sits here too: it sets only the -Xmx limit, bounded by
   the PC's memory as measured, and leaves every other Java option alone. */

import { api } from "../api.js";
import { render } from "../nav.js";
import { serverAction } from "./overview.js";
import { can, renderers, state } from "../state.js";
import { t, technical } from "../strings.js";
import { busy, card, el, fmt, loadInto, problem, toast, withHelp } from "../ui.js";
import { serverRow } from "../servers.js";
import { saveServerSettings } from "./settings.js";

const serverUrl = (path) => `/servers/${encodeURIComponent(state.serverId)}${path}`;

// Each key's label and hint, and the words for each choice.
const LABELS = {
  "difficulty": ["game.difficulty", "game.difficulty_hint"],
  "gamemode": ["game.gamemode", "game.gamemode_hint"],
  "max-players": ["game.max_players", "game.max_players_hint"],
  "level-seed": ["game.seed", "game.seed_hint"],
  "white-list": ["game.whitelist", "game.whitelist_hint"],
  "pvp": ["game.pvp", "game.pvp_hint"],
  "view-distance": ["game.view_distance", "game.view_distance_hint"],
  "motd": ["game.motd", "game.motd_hint"],
  "server-port": ["game.port", "game.port_hint"],
  // Bedrock's own keys.
  "allow-list": ["game.whitelist", "game.allowlist_hint"],
  "allow-cheats": ["game.cheats", "game.cheats_hint"],
  "server-name": ["game.server_name", "game.server_name_hint"],
};
const CHOICE_WORDS = {
  peaceful: "game.peaceful", easy: "game.easy", normal: "game.normal", hard: "game.hard",
  survival: "game.survival", creative: "game.creative", adventure: "game.adventure",
  spectator: "game.spectator",
};
// The order the form shows them in: how the game plays, who can join, then
// the technical bits.
const ORDER = [
  ["game.group_play", ["gamemode", "difficulty", "pvp", "allow-cheats"]],
  ["game.group_who", ["motd", "server-name", "max-players", "white-list", "allow-list"]],
  ["game.group_world", ["level-seed", "view-distance", "server-port"]],
];

function choiceLabel(value) {
  return CHOICE_WORDS[value] ? t(CHOICE_WORDS[value]) : value;
}

/* The control for one field, and a function giving its value back. */
function control(field) {
  const id = `game-${field.key}`;
  const shown = field.set && !field.problem ? field.value : null;
  if (field.kind === "choice") {
    const current = shown ?? field.minecraft_default;
    const select = el("select", { id }, field.choices.map((choice) =>
      el("option", { value: choice, selected: choice === current ? "selected" : false }, choiceLabel(choice))));
    return { node: select, read: () => select.value, initial: current };
  }
  if (field.kind === "bool") {
    const current = shown ?? field.minecraft_default === "true";
    const box = el("input", { id, type: "checkbox", checked: current ? "checked" : false });
    const word = el("span", {}, t(current ? "game.on" : "game.off"));
    box.addEventListener("change", () => { word.textContent = t(box.checked ? "game.on" : "game.off"); });
    return { node: el("label", { class: "switch" }, box, word), read: () => box.checked, initial: current };
  }
  if (field.kind === "int" || field.kind === "port") {
    const current = shown ?? Number(field.minecraft_default);
    const input = el("input", { id, type: "number", step: "1", min: String(field.min), max: String(field.max),
      value: String(current), class: "num" });
    return { node: input, read: () => input.value.trim(), initial: String(current) };
  }
  const current = shown ?? (field.kind === "seed" ? "" : field.minecraft_default);
  const input = el("input", { id, maxlength: String(field.max_length), value: current,
    readonly: field.read_only ? "readonly" : false, class: field.kind === "seed" ? "mono" : null });
  return { node: input, read: () => input.value, initial: current };
}

function fieldRow(field, ctl) {
  const [labelKey, hintKey] = LABELS[field.key];
  const notes = [];
  if (field.read_only === "world_exists") notes.push(t("game.seed_locked"));
  else notes.push(t(hintKey));
  if (!field.set) {
    notes.push(t("game.not_set", { value: field.kind === "choice" ? choiceLabel(field.minecraft_default)
      : (field.minecraft_default || t("game.blank")) }));
  }
  const error = el("div", { class: "field-error", id: `game-${field.key}-error`, role: "alert" });
  if (field.problem) error.textContent = t("game.file_problem", { problem: field.problem });
  return {
    node: el("div", { class: "field" },
      el("label", { for: `game-${field.key}` }, t(labelKey),
        technical() ? el("span", { class: "hint mono key-name" }, ` ${field.key}`) : null),
      ctl.node,
      el("div", { class: "hint" }, notes.join(" ")),
      error),
    error,
  };
}

function restartBanner(data) {
  if (!data.running) return null;
  return el("div", { class: `banner ${data.restart_needed ? "warn" : ""}`, role: "status" },
    el("div", { class: "grow" }, data.restart_needed ? t("game.restart_needed") : t("game.after_restart")),
    data.restart_needed
      ? el("button", { class: "btn small", type: "button",
          onclick: (e) => serverAction("restart", e.currentTarget) }, t("action.restart_now"))
      : null);
}

function formCard(data) {
  const controls = {}, errors = {};
  const groups = ORDER.map(([groupKey, keys]) => {
    const rows = keys.map((key) => data.fields.find((f) => f.key === key)).filter(Boolean).map((field) => {
      const ctl = control(field);
      controls[field.key] = { ctl, field };
      const row = fieldRow(field, ctl);
      errors[field.key] = row.error;
      return row.node;
    });
    return el("fieldset", { class: "field-group" }, el("legend", {}, t(groupKey)),
      el("div", { class: "grid cols-3" }, rows));
  });
  const save = el("button", { class: "btn primary", type: "button" }, t("game.save"));
  save.addEventListener("click", () => busy(save, t("action.saving"), async () => {
    for (const node of Object.values(errors)) node.textContent = "";
    const values = {};
    for (const [key, { ctl, field }] of Object.entries(controls)) {
      if (field.read_only) continue;
      const value = ctl.read();
      if (String(value) !== String(ctl.initial)) values[key] = value;
    }
    if (!Object.keys(values).length) { toast(t("settings.nothing_changed")); return; }
    try {
      const result = await api(serverUrl("/game-settings"), { method: "PUT", body: { values } });
      toast(result.running ? t("game.saved_running") : t("game.saved"), "success", 7000);
      render();
    } catch (err) {
      if (err.problems) {
        for (const [key, reason] of Object.entries(err.problems)) {
          if (errors[key]) errors[key].textContent = reason;
        }
        toast(t("game.fix_marked"), "error");
      } else toast(err.message, "error", 9000);
    }
  }));
  return card(t("game.title"),
    el("p", { class: "hint mt-0" }, data.exists ? t("game.intro") : t("game.no_file")),
    ...groups,
    el("div", { class: "btn-row mt-12" }, save, el("span", { class: "hint" }, t("game.copy_kept"))));
}

/* Technical mode: the whole file as text, for every other key. The known
   keys in it are still checked like the form's. */
function rawCard(data) {
  const area = el("textarea", { id: "game-raw", class: "mono raw-text", rows: "18", spellcheck: "false",
    "aria-label": t("game.raw_label") }, data.text);
  const save = el("button", { class: "btn", type: "button" }, t("game.save_raw"));
  save.addEventListener("click", () => busy(save, t("action.saving"), async () => {
    try {
      const result = await api(serverUrl("/game-settings/raw"), { method: "PUT", body: { text: area.value } });
      if (result.nothing_changed) { toast(t("settings.nothing_changed")); return; }
      toast(result.running ? t("game.saved_running") : t("game.saved"), "success", 7000);
      render();
    } catch (err) { toast(err.message, "error", 12000); }
  }));
  return card(t("game.raw_title"),
    el("p", { class: "hint mt-0" }, t("game.raw_hint", { file: data.file })),
    area,
    el("div", { class: "btn-row mt-12" }, save));
}

/* ------------------------------------------------------------ memory */

const gb = (mb) => `${(mb / 1024).toFixed(mb % 1024 ? 1 : 0)} GB`;

/* What running everything at once adds up to, against the PC's memory. */
function memoryWarning(data, chosen) {
  if (!data.total_mb) return null;
  const others = data.servers.filter((s) => !s.this && s.running);
  const together = others.reduce((sum, s) => sum + (s.limit_mb || 0), 0) + chosen;
  if (together <= data.total_mb) return null;
  return el("div", { class: "banner warn", role: "status" }, others.length
    ? t("memory.over_together", { names: others.map((s) => s.name).join(", "), total: gb(together),
        pc: gb(data.total_mb) })
    : t("memory.over_alone", { total: gb(together), pc: gb(data.total_mb) }));
}

function memoryCard(data) {
  const label = withHelp(el("span", { class: "help-label" }, t("memory.label")), "memory", "configuration");
  const measured = data.total_mb
    ? el("p", { class: "hint mt-0" }, t("memory.pc_has", { total: gb(data.total_mb) }))
    : el("p", { class: "hint mt-0" }, t("memory.pc_unknown"));
  if (!data.takes_memory_limit) {
    const bedrock = (serverRow() || {}).edition === "bedrock";
    return card(t("memory.title"), label,
      el("p", { class: "hint" }, t(bedrock ? "memory.not_bedrock" : "memory.not_used")));
  }
  const current = data.limit_mb;
  const warning = el("div");
  let slider = null, value = null;
  if (data.total_mb) {
    const start = Math.min(data.total_mb, Math.max(data.min_mb, current || 2048));
    value = el("output", { class: "memory-value", for: "memory-slider" }, gb(start));
    slider = el("input", {
      type: "range", id: "memory-slider", min: String(data.min_mb), max: String(data.total_mb),
      step: String(data.step_mb), value: String(start), "aria-describedby": "memory-now",
      disabled: can("settings.edit") ? false : "disabled",
    });
    const update = () => {
      value.textContent = gb(Number(slider.value));
      warning.replaceChildren(memoryWarning(data, Number(slider.value)) || "");
    };
    slider.addEventListener("input", update);
    update();
  }
  const save = slider && can("settings.edit") ? el("button", { class: "btn primary", type: "button",
    onclick: (e) => busy(e.currentTarget, t("action.saving"), async () => {
      const mb = Number(slider.value);
      if (mb === current) { toast(t("settings.nothing_changed")); return; }
      try {
        const result = await api(serverUrl("/memory"), { method: "PUT", body: { memory_mb: mb } });
        toast(result.running ? t("memory.saved_running") : t("memory.saved"), "success", 7000);
        render();
      } catch (err) { toast(err.message, "error", 9000); }
    }) }, t("memory.save")) : null;
  const raw = el("input", { class: "mono", id: "jvm-args", value: data.jvm_args.join(" ") });
  return card(t("memory.title"),
    label,
    measured,
    slider ? el("div", { class: "memory-slider" }, slider, value) : null,
    el("p", { class: "hint", id: "memory-now" }, current
      ? t("memory.now", { limit: gb(current) }) : t("memory.unset")),
    warning,
    save ? el("div", { class: "btn-row mt-12" }, save) : null,
    technical() ? el("div", { class: "field mt-12" },
      el("label", { for: "jvm-args" }, t("memory.raw_args")), raw,
      el("div", { class: "hint" }, t("memory.raw_hint")),
      can("settings.edit") ? el("div", { class: "btn-row mt-10" }, el("button", { class: "btn", type: "button",
        onclick: (e) => busy(e.currentTarget, t("action.saving"), async () => {
          const next = raw.value.trim() ? raw.value.trim().split(/\s+/) : [];
          if (next.join(" ") === data.jvm_args.join(" ")) { toast(t("settings.nothing_changed")); return; }
          try {
            const { ok } = await saveServerSettings({ "server.jvm_args": next });
            if (ok) toast(t("settings.saved"), "success");
            render();
          } catch (err) { toast(err.message, "error"); }
        }) }, t("memory.save_raw"))) : null) : null);
}

renderers["game-settings"] = (page) => loadInto(page, async () => {
  let data;
  try {
    data = await api(serverUrl("/game-settings"));
  } catch (err) {
    return problem(err.message);
  }
  const memory = await api(serverUrl("/memory")).catch((err) => ({ error: err.message }));
  return el("div", { class: "stack" },
    restartBanner(data),
    formCard(data),
    memory.error ? problem(memory.error) : memoryCard(memory),
    technical() ? rawCard(data) : null);
});
