import { api } from "../api.js";
import { renderers } from "../state.js";
import { card, el, fmt, loadInto, table } from "../ui.js";

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
