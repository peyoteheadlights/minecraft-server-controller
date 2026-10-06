import { api } from "../api.js";
import { renderers } from "../state.js";
import { t, technical } from "../strings.js";
import { card, el, emptyState, fmt, loadInto, table } from "../ui.js";

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

renderers.players = (page) => loadInto(page, async () => {
  const data = await api("/players");
  const holder = el("div", { class: "stack" });
  const uuid = technical();
  holder.append(card(t("players.online", { count: data.online.length, max: data.max_players }),
    data.online.length
      ? table([t("players.col_player"), ...(uuid ? [t("players.col_uuid")] : []), t("players.col_session")],
          data.online.map((p) => [
            playerName(p),
            ...(uuid ? [el("span", { class: "mono" }, p.uuid || "—")] : []),
            fmt.duration(p.session_seconds)]))
      : emptyState(t("players.nobody"))));
  holder.append(card(t("players.everyone"),
    data.known.length
      ? table([t("players.col_player"), t("players.col_first"), t("players.col_last"),
          t("players.col_sessions"), t("players.col_total")],
          data.known.map((p) => [
            p.username, fmt.time(p.first_seen), fmt.time(p.last_seen),
            String(p.sessions), fmt.duration(p.total_seconds_live)]))
      : emptyState(t("players.none"), t("players.none_hint"))));
  holder.append(el("p", { class: "hint" }, t("players.no_ip")));
  return holder;
});
