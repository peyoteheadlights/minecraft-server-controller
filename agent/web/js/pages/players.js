/* Players: who is online, everyone seen, and the buttons to whitelist,
   make operator, kick, ban and unban.

   A button sends the normal Minecraft command. The page shows it as
   "Sent" until the server's console confirms it, then "Done" (or what the
   server said instead). Who is on the whitelist, an operator or banned
   comes from Minecraft's own files, not from what was sent. */

import { api, serverPath } from "../api.js";
import { render } from "../nav.js";
import { can, renderers, state } from "../state.js";
import { t, technical } from "../strings.js";
import { busy, card, confirmDialog, el, emptyState, fmt, known, loadInto, table, toast } from "../ui.js";

const POLL_MS = 1000;
const POLL_FOR_MS = 22000;
// What each action is called on its button and in the "Sent" line.
const ACTION_WORDS = {
  whitelist_add: "players.do_whitelist_add",
  whitelist_remove: "players.do_whitelist_remove",
  op: "players.do_op",
  deop: "players.do_deop",
  kick: "players.do_kick",
  ban: "players.do_ban",
  pardon: "players.do_pardon",
};
const STATE_WORDS = {
  sent: ["players.state_sent", "warning", "warn"],
  done: ["players.state_done", "success", "ok"],
  unchanged: ["players.state_unchanged", "neutral", "off"],
  failed: ["players.state_failed", "danger", "error"],
  no_answer: ["players.state_no_answer", "warning", "warn"],
};
// Actions that ask first, with the dialog's words.
const CONFIRM = {
  kick: ["players.kick_title", "players.kick_body", "players.do_kick"],
  ban: ["players.ban_title", "players.ban_body", "players.do_ban"],
};

/* A player's name exactly as the server printed it, with a badge when the
   server said they came in from Bedrock. "java" and null look the same on
   purpose: with crossplay off everyone is a Java player, and when nothing
   said otherwise the name stands on its own rather than being labelled on
   a guess. */
function playerName(player) {
  return el("div", { class: "player-name" },
    el("span", {}, player.username),
    player.edition === "bedrock"
      ? el("span", { class: "tag", title: t("players.bedrock_hint") }, t("players.bedrock"))
      : null);
}

function names(list) {
  // Bedrock's permissions.json names players only by xuid; one this app
  // never saw join has no name.
  return new Set(((list && list.players) || []).filter((p) => p.name).map((p) => p.name.toLowerCase()));
}

/* The line at the top saying what was sent and what the server answered. */
function actionLine(action) {
  const [stateKey, tone, tag] = STATE_WORDS[action.state] || STATE_WORDS.sent;
  return el("li", { class: "action-line" },
    el("span", { class: `status-dot tone-${tone}`, "aria-hidden": "true" }),
    el("span", {}, t(ACTION_WORDS[action.kind]), " ", el("strong", {}, action.name)),
    el("span", { class: `tag ${tag}` }, t(stateKey)),
    technical() && action.message ? el("span", { class: "hint mono" }, action.message) : null);
}

async function follow(actionId, line, serverId) {
  const until = Date.now() + POLL_FOR_MS;
  while (Date.now() < until) {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    let found;
    try {
      // The server it was sent to, even if another server's tab is open now.
      found = (await api(serverPath(`/players/actions/${encodeURIComponent(actionId)}`, serverId))).action;
    } catch (err) { return; }
    const next = actionLine(found);
    if (line.isConnected) line.replaceWith(next);
    line = next;
    if (found.state !== "sent") {
      const [stateKey] = STATE_WORDS[found.state];
      const level = { done: "success", failed: "error", no_answer: "warn" }[found.state] || "info";
      toast(`${t(ACTION_WORDS[found.kind])} ${found.name}: ${t(stateKey)}`, level, 6000);
      if (found.state === "done" && state.page === "players" && state.serverId === serverId) render();
      return;
    }
  }
}

async function act(kind, name, button, log) {
  let reason = "";
  if (CONFIRM[kind]) {
    const [titleKey, bodyKey, buttonKey] = CONFIRM[kind];
    const input = el("input", { id: "player-reason", maxlength: "100", autocomplete: "off" });
    const ok = await confirmDialog({
      title: t(titleKey, { name }),
      body: el("div", {}, el("p", {}, t(bodyKey, { name })),
        el("div", { class: "field" }, el("label", { for: "player-reason" }, t("players.reason")), input)),
      confirmLabel: t(buttonKey), danger: true,
    });
    if (!ok) return;
    reason = input.value.trim();
  }
  const serverId = state.serverId;
  await busy(button, t("players.sending"), async () => {
    try {
      const result = await api("/players/actions", { method: "POST",
        body: { action: kind, name, reason: reason || null, confirm: Boolean(CONFIRM[kind]) } });
      const line = actionLine(result.action);
      log.prepend(line);
      log.closest("section").hidden = false;
      follow(result.action.id, line, serverId);
    } catch (err) { toast(err.message, "error", 9000); }
  });
}

// Making someone an operator is the owner's alone (players.op): an operator
// can type any command in the game.
const OPERATOR = new Set(["op", "deop"]);

function actionButton(kind, name, enabled, log, extra = "") {
  if (OPERATOR.has(kind) && !can("players.op")) return null;
  return el("button", {
    class: `btn small${extra}`, type: "button", disabled: enabled ? false : "disabled",
    onclick: (e) => act(kind, name, e.currentTarget, log),
  }, t(ACTION_WORDS[kind]));
}

function tags(name, sets) {
  const lower = name.toLowerCase();
  return [
    sets.whitelist.has(lower) ? el("span", { class: "tag" }, t("players.tag_whitelisted")) : null,
    sets.ops.has(lower) ? el("span", { class: "tag" }, t("players.tag_op")) : null,
    sets.banned.has(lower) ? el("span", { class: "tag error" }, t("players.tag_banned")) : null,
  ];
}

function rowButtons(name, sets, running, log, online) {
  const lower = name.toLowerCase();
  return el("div", { class: "btn-row" },
    sets.whitelist.has(lower)
      ? actionButton("whitelist_remove", name, running, log)
      : actionButton("whitelist_add", name, running, log),
    sets.ops.has(lower) ? actionButton("deop", name, running, log) : actionButton("op", name, running, log),
    online ? actionButton("kick", name, running, log, " danger") : null,
    // Bedrock servers have no ban list.
    !sets.bans ? null
      : sets.banned.has(lower)
        ? actionButton("pardon", name, running, log)
        : actionButton("ban", name, running, log, " danger"));
}

/* Add someone by name who may never have joined. */
// A Java name, or an Xbox gamertag (letters, numbers and single spaces).
const NAME_PATTERNS = {
  java: /^\.?[A-Za-z0-9_]{1,16}$/,
  bedrock: /^[A-Za-z0-9](?:[A-Za-z0-9]| (?! )){0,19}$/,
};

function addCard(running, log, sets) {
  const bedrock = sets.edition === "bedrock";
  const input = el("input", { id: "player-add-name", maxlength: bedrock ? "20" : "17", autocomplete: "off",
    placeholder: bedrock ? "Steve Gamer" : "Alex", class: "mono" });
  const button = (kind, extra = "") => (OPERATOR.has(kind) && !can("players.op") ? null : el("button", {
    class: `btn${extra}`, type: "button", disabled: running ? false : "disabled",
    onclick: (e) => {
      const name = input.value.trim();
      if (!NAME_PATTERNS[bedrock ? "bedrock" : "java"].test(name) || name.endsWith(" ")) {
        toast(t(bedrock ? "players.bad_gamertag" : "players.bad_name"), "warn");
        input.focus();
        return;
      }
      act(kind, name, e.currentTarget, log);
    },
  }, t(ACTION_WORDS[kind])));
  return card(t("players.add_title"),
    el("div", { class: "field" }, el("label", { for: "player-add-name" }, t("players.add_name")), input,
      el("div", { class: "hint" }, t("players.add_hint"))),
    el("div", { class: "btn-row" }, button("whitelist_add", " primary"), button("op"),
      sets.bans ? button("ban", " danger") : null),
    bedrock && can("players.op") ? el("p", { class: "hint" }, t("players.bedrock_op_online")) : null);
}

/* One of Minecraft's lists, read from its file. */
function listCard(titleKey, list, removeKind, running, log, emptyKey, columns = null) {
  if (!list || list.players === null) {
    return card(t(titleKey), el("p", { class: "hint mt-0" }, (list && list.reason) || t("value.unknown")));
  }
  if (!list.players.length) return card(t(titleKey), emptyState(t(emptyKey)));
  const headers = [t("players.col_player"), ...(columns ? columns.headers : []), ""];
  return card(t(titleKey), table(headers, list.players.map((p) => [
    p.name ? el("span", {}, p.name) : el("span", { class: "mono hint", title: t("players.xuid_only") }, p.uuid || "—"),
    ...(columns ? columns.cells(p) : []),
    p.name ? actionButton(removeKind, p.name, running, log) : null,
  ])), technical() ? el("p", { class: "hint mono" }, t("players.from_file", { file: list.file })) : null);
}

renderers.players = (page) => loadInto(page, async () => {
  const data = await api("/players");
  const running = data.running;
  const sets = {
    whitelist: names(data.lists.whitelist), ops: names(data.lists.ops), banned: names(data.lists.banned),
    bans: data.bans !== false, edition: data.edition,
  };
  const log = el("ul", { class: "action-lines", "aria-live": "polite" },
    (data.actions || []).map(actionLine));
  const logCard = card(t("players.recent_actions"), log);
  logCard.hidden = !(data.actions || []).length;

  const holder = el("div", { class: "stack" });
  if (!running) holder.append(el("div", { class: "banner", role: "status" }, t("players.start_first")));
  holder.append(logCard);
  const uuid = technical();
  // The count is null until the agent has read the list; a missing number
  // shows as Unknown, never as the length of a list that may be stale.
  const unknown = t("value.unknown");
  holder.append(card(t("players.online", {
    count: known(data.online_count) ? data.online_count : unknown,
    max: known(data.max_players) ? data.max_players : unknown,
  }),
    data.online.length
      ? table([t("players.col_player"), ...(uuid ? [t("players.col_uuid")] : []), t("players.col_session"), ""],
          data.online.map((p) => [
            el("div", {}, playerName(p), el("div", { class: "tag-row" }, tags(p.username, sets))),
            ...(uuid ? [el("span", { class: "mono" }, p.uuid || "—")] : []),
            fmt.duration(p.session_seconds),
            rowButtons(p.username, sets, running, log, true)]))
      : emptyState(t("players.nobody"))));
  holder.append(addCard(running, log, sets));
  const online = new Set(data.online.map((p) => p.username));
  holder.append(card(t("players.everyone"),
    data.known.length
      ? table([t("players.col_player"), t("players.col_first"), t("players.col_last"),
          t("players.col_sessions"), t("players.col_total"), ""],
          data.known.map((p) => [
            el("div", {}, el("span", {}, p.username), el("div", { class: "tag-row" }, tags(p.username, sets))),
            fmt.time(p.first_seen), fmt.time(p.last_seen),
            String(p.sessions), fmt.duration(p.total_seconds_live),
            rowButtons(p.username, sets, running, log, online.has(p.username))]))
      : emptyState(t("players.none"), t("players.none_hint"))));
  holder.append(el("div", { class: "columns three gap-section" },
    listCard("players.whitelist", data.lists.whitelist, "whitelist_remove", running, log, "players.whitelist_empty"),
    listCard("players.ops", data.lists.ops, "deop", running, log, "players.ops_empty"),
    listCard("players.banned", data.lists.banned, "pardon", running, log, "players.banned_empty", {
      headers: [t("players.col_reason")],
      cells: (p) => [el("span", { class: "hint" }, p.reason || "—")],
    })));
  holder.append(el("p", { class: "hint" }, t("players.whitelist_note")));
  holder.append(el("p", { class: "hint" }, t("players.no_ip")));
  return holder;
});
