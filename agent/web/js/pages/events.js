import { api } from "../api.js";
import { renderers } from "../state.js";
import { card, el, fmt, loadInto, table } from "../ui.js";

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
