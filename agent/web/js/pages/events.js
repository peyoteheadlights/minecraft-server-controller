import { api } from "../api.js";
import { renderers } from "../state.js";
import { t, technical } from "../strings.js";
import { card, el, emptyState, fmt, loadInto, table } from "../ui.js";

const LEVELS = { error: ["error", "events.level_error"], warn: ["warn", "events.level_warn"] };

function message(e) {
  const level = LEVELS[e.level];
  return el("span", {}, level ? el("span", { class: `tag ${level[0]}` }, t(level[1])) : null,
    level ? " " : null, e.message);
}

renderers.events = (page) => loadInto(page, async () => {
  const data = await api("/events?limit=200");
  if (!data.events.length) return card(t("events.title"), emptyState(t("events.none")));
  const headers = [t("events.col_when"), ...(technical() ? [t("events.col_type")] : []), t("events.col_message")];
  return card(t("events.title"), table(headers, data.events.map((e) => [
    fmt.time(e.ts),
    ...(technical() ? [el("span", { class: "mono" }, e.type)] : []),
    message(e),
  ])));
});
